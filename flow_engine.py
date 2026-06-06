"""
flow_engine.py
Motor de análise de fluxo de ordens em tempo real.

Métricas calculadas por ativo:
  - Delta por trade (compra agredida - venda agredida)
  - CVD — Cumulative Volume Delta (delta acumulado da sessão)
  - Footprint: volume comprador e vendedor por nível de preço
  - Book Imbalance: pressão no topo do book (bid vs ask)
  - Resumo de sessão (via daily callback da DLL)
"""

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from profit_bridge import (
    TradeEvent, BookEvent, DailyEvent,
    TRADE_TYPE_BUY, TRADE_TYPE_SELL,
    BookEvent as BE,
)


# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------

@dataclass
class FootprintLevel:
    """Volume comprador e vendedor num único nível de preço."""
    price:      float
    buy_qty:    int = 0
    sell_qty:   int = 0

    @property
    def delta(self) -> int:
        return self.buy_qty - self.sell_qty

    @property
    def total_qty(self) -> int:
        return self.buy_qty + self.sell_qty

    @property
    def imbalance_pct(self) -> float:
        """% de dominância compradora. 50 = neutro."""
        total = self.total_qty
        return (self.buy_qty / total * 100) if total else 50.0


@dataclass
class BookLevel:
    """Nível do book de ofertas (bid ou ask)."""
    price: float
    qty:   int


@dataclass
class FlowSnapshot:
    """
    Estado atual de um ativo — lido a qualquer momento pela interface.
    Thread-safe via lock do ativo.
    """
    ticker: str

    # -- Fluxo acumulado na sessão --
    cvd:            int   = 0    # Cumulative Volume Delta
    buy_vol:        float = 0.0  # Volume financeiro comprador
    sell_vol:       float = 0.0  # Volume financeiro vendedor
    buy_qty:        int   = 0    # Contratos comprados (agressões)
    sell_qty:       int   = 0    # Contratos vendidos (agressões)
    cross_qty:      int   = 0    # Cruzamentos sem agressor
    total_trades:   int   = 0

    # -- Último trade --
    last_price:     float = 0.0
    last_qty:       int   = 0
    last_side:      str   = ""   # "BUY" | "SELL" | "CROSS"
    last_ts:        Optional[datetime] = None

    # -- Footprint: price -> FootprintLevel --
    footprint: Dict[float, FootprintLevel] = field(default_factory=dict)

    # -- Book (listas ordenadas) --
    bids: List[BookLevel] = field(default_factory=list)  # melhor bid primeiro
    asks: List[BookLevel] = field(default_factory=list)  # melhor ask primeiro

    # -- Daily (da DLL) --
    daily_open:    float = 0.0
    daily_high:    float = 0.0
    daily_low:     float = 0.0
    daily_close:   float = 0.0
    daily_delta:   int   = 0    # direto da DLL (qty_buyer - qty_seller)
    daily_vol:     float = 0.0
    contracts_open:int   = 0

    @property
    def book_imbalance(self) -> Optional[float]:
        """
        Imbalance do topo do book: (bid_qty - ask_qty) / (bid_qty + ask_qty).
        Positivo = pressão compradora. Range: -1.0 a +1.0.
        """
        if not self.bids or not self.asks:
            return None
        b = self.bids[0].qty
        a = self.asks[0].qty
        total = b + a
        return (b - a) / total if total else 0.0

    @property
    def bid_price(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def ask_price(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Optional[float]:
        if self.bids and self.asks:
            return self.asks[0].price - self.bids[0].price
        return None

    def top_footprint_levels(self, n: int = 10) -> List[FootprintLevel]:
        """Retorna os N níveis com maior volume total, ordenados por preço desc."""
        sorted_levels = sorted(
            self.footprint.values(),
            key=lambda x: x.price,
            reverse=True
        )
        return sorted_levels[:n]

    def summary(self) -> str:
        """Resumo legível para console/log."""
        imb = self.book_imbalance
        imb_str = f"{imb:+.2f}" if imb is not None else "n/a"
        spread_str = f"{self.spread:.2f}" if self.spread else "n/a"
        return (
            f"[{self.ticker}] "
            f"Last={self.last_price:.2f} ({self.last_side}) "
            f"CVD={self.cvd:+d} "
            f"DailyΔ={self.daily_delta:+d} "
            f"Imb={imb_str} "
            f"Spread={spread_str} "
            f"Trades={self.total_trades}"
        )


# ---------------------------------------------------------------------------
# Motor principal
# ---------------------------------------------------------------------------

class FlowEngine:
    """
    Recebe eventos do ProfitBridge e mantém o estado de fluxo
    de cada ativo em FlowSnapshot.

    Uso:
        engine = FlowEngine()
        bridge.on_trade   = engine.on_trade
        bridge.on_book    = engine.on_book
        bridge.on_daily   = engine.on_daily

        snap = engine.snapshot("WDOK25")
    """

    def __init__(self):
        self._snapshots: Dict[str, FlowSnapshot] = {}
        self._locks:     Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

        # Callbacks opcionais chamados após cada atualização
        # Assinatura: (snapshot: FlowSnapshot) -> None
        self.on_trade_update: Optional[callable] = None
        self.on_book_update:  Optional[callable] = None
        self.on_daily_update: Optional[callable] = None

    # ------------------------------------------------------------------
    # Acesso ao snapshot
    # ------------------------------------------------------------------

    def snapshot(self, ticker: str) -> Optional[FlowSnapshot]:
        """Retorna o snapshot atual do ativo (ou None se não existir)."""
        return self._snapshots.get(ticker)

    def all_snapshots(self) -> Dict[str, FlowSnapshot]:
        return dict(self._snapshots)

    def tickers(self) -> List[str]:
        return list(self._snapshots.keys())

    # ------------------------------------------------------------------
    # Handlers (registrar no bridge)
    # ------------------------------------------------------------------

    def on_trade(self, event: TradeEvent):
        snap = self._get_or_create(event.ticker)
        lock = self._locks[event.ticker]

        with lock:
            # Delta e volume
            if event.is_buy_aggression:
                snap.cvd      += event.qty
                snap.buy_qty  += event.qty
                snap.buy_vol  += event.volume
                snap.last_side = "BUY"
            elif event.is_sell_aggression:
                snap.cvd      -= event.qty
                snap.sell_qty += event.qty
                snap.sell_vol += event.volume
                snap.last_side = "SELL"
            else:
                snap.cross_qty += event.qty
                snap.last_side  = "CROSS"

            snap.last_price = event.price
            snap.last_qty   = event.qty
            snap.last_ts    = event.ts
            snap.total_trades += 1

            # Footprint
            price_key = round(event.price, 2)
            if price_key not in snap.footprint:
                snap.footprint[price_key] = FootprintLevel(price=price_key)
            lvl = snap.footprint[price_key]
            if event.is_buy_aggression:
                lvl.buy_qty += event.qty
            elif event.is_sell_aggression:
                lvl.sell_qty += event.qty

        if self.on_trade_update:
            self.on_trade_update(snap)

    def on_book(self, event: BookEvent):
        snap = self._get_or_create(event.ticker)
        lock = self._locks[event.ticker]

        with lock:
            lst = snap.bids if event.side == BE.SIDE_BUY else snap.asks
            self._apply_book_action(lst, event)

        if self.on_book_update:
            self.on_book_update(snap)

    def on_daily(self, event: DailyEvent):
        snap = self._get_or_create(event.ticker)
        lock = self._locks[event.ticker]

        with lock:
            snap.daily_open     = event.open_
            snap.daily_high     = event.high
            snap.daily_low      = event.low
            snap.daily_close    = event.close
            snap.daily_delta    = event.daily_delta
            snap.daily_vol      = event.vol
            snap.contracts_open = event.contracts_open

        if self.on_daily_update:
            self.on_daily_update(snap)

    def update_price_depth(self, ticker: str, depth: dict):
        """
        Atualiza o snapshot com os dados do livro de profundidade (price depth).
        'depth' tem o formato retornado por ProfitBridge.get_price_depth():
            {"bid": [{"price": float, "qty": int, "count": int, ...}], "ask": [...]}

        Este método substitui as listas de bids/asks do offer book com dados
        do price depth (mais preciso — DLL mantém o estado).
        """
        snap = self._get_or_create(ticker)
        lock = self._locks[ticker]

        with lock:
            snap.bids = [
                BookLevel(price=lvl["price"], qty=lvl["qty"])
                for lvl in depth.get("bid", [])
                if lvl["price"] is not None and not lvl["is_theoric"]
            ]
            snap.asks = [
                BookLevel(price=lvl["price"], qty=lvl["qty"])
                for lvl in depth.get("ask", [])
                if lvl["price"] is not None and not lvl["is_theoric"]
            ]

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _get_or_create(self, ticker: str) -> FlowSnapshot:
        if ticker not in self._snapshots:
            with self._global_lock:
                if ticker not in self._snapshots:
                    self._snapshots[ticker] = FlowSnapshot(ticker=ticker)
                    self._locks[ticker]     = threading.Lock()
        return self._snapshots[ticker]

    @staticmethod
    def _apply_book_action(lst: List[BookLevel], event: BookEvent):
        """Aplica a ação do book (add/edit/delete/full) na lista."""
        action = event.action

        if action == BE.ACTION_FULL_BOOK:
            # Snapshot completo: substituir lista inteira
            lst.clear()
            if event.qty > 0 and event.price > 0:
                lst.append(BookLevel(price=event.price, qty=event.qty))

        elif action == BE.ACTION_ADD:
            lvl = BookLevel(price=event.price, qty=event.qty)
            # Inserir na posição correta (0 = melhor)
            pos = min(event.position, len(lst))
            lst.insert(pos, lvl)

        elif action == BE.ACTION_EDIT:
            pos = event.position
            if 0 <= pos < len(lst):
                lst[pos].qty   = event.qty
                lst[pos].price = event.price

        elif action == BE.ACTION_DELETE:
            pos = event.position
            if 0 <= pos < len(lst):
                del lst[pos]

        elif action == BE.ACTION_DELETE_FROM:
            pos = event.position
            if 0 <= pos < len(lst):
                del lst[pos:]

        # Limitar profundidade a 20 níveis por lado
        if len(lst) > 20:
            del lst[20:]
