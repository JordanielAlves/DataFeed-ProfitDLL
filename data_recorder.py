"""
data_recorder.py
Gravação persistente de todos os eventos de mercado no PostgreSQL.

Arquitetura:
  - Callbacks da DLL → fila em memória (thread-safe, sem bloqueio)
  - Thread escritora → drena a fila em batches → PostgreSQL

Isso garante que os callbacks da DLL nunca esperam o banco de dados.
"""

import threading
import time
import logging
from collections import defaultdict
from datetime import date, datetime
from queue import Queue, Full, Empty
from typing import Optional

import psycopg2
import psycopg2.extras

from config import DB_DSN, RECORDER, ASSETS
from profit_bridge import TradeEvent, BookEvent, DailyEvent, BookEvent as BE

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("recorder")


# ---------------------------------------------------------------------------
# Tipos de evento na fila
# ---------------------------------------------------------------------------
_EVT_TRADE = "trade"
_EVT_BOOK  = "book"
_EVT_STOP  = "__stop__"


# ---------------------------------------------------------------------------
# Recorder principal
# ---------------------------------------------------------------------------
class DataRecorder:
    """
    Recebe eventos do ProfitBridge e os persiste no PostgreSQL.

    Uso:
        recorder = DataRecorder()
        recorder.start()

        bridge.on_trade  = recorder.on_trade
        bridge.on_book   = recorder.on_book
        bridge.on_daily  = recorder.on_daily

        # ... ao encerrar:
        recorder.stop()
    """

    def __init__(self):
        self._queue:   Queue = Queue(maxsize=RECORDER["max_queue_size"])
        self._thread:  Optional[threading.Thread] = None
        self._running: bool = False

        # Sessões abertas: ticker → session_id
        self._sessions: dict[str, int] = {}

        # Cache de saldo por agente (atualizado em memória, persistido em batch)
        # { (date, ticker, agent_id) → {buy_qty, sell_qty, ...} }
        self._agent_cache: dict = defaultdict(lambda: {
            "buy_qty": 0, "sell_qty": 0,
            "buy_trades": 0, "sell_trades": 0,
            "buy_volume": 0.0, "sell_volume": 0.0,
            "cross_qty": 0, "dirty": False,
        })
        self._agent_flush_interval = 10  # segundos
        self._last_agent_flush = time.time()

        # Buffers de batch
        self._trade_buffer: list = []
        self._book_buffer:  list = []

        # Estatísticas
        self._stats = {"trades": 0, "book_events": 0, "flushes": 0, "errors": 0}

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def start(self):
        """Inicializa sessões no banco e inicia a thread escritora."""
        self._running = True
        self._init_db()
        self._open_sessions()
        self._thread = threading.Thread(target=self._writer_loop, daemon=True, name="recorder-writer")
        self._thread.start()
        log.info("DataRecorder iniciado.")

    def stop(self, timeout: float = 10.0):
        """Para a thread escritora e faz flush final."""
        log.info("Encerrando DataRecorder...")
        self._queue.put((_EVT_STOP, None))
        if self._thread:
            self._thread.join(timeout=timeout)
        self._close_sessions()
        log.info(f"DataRecorder encerrado. Stats: {self._stats}")

    # ------------------------------------------------------------------
    # Handlers (registrar no bridge)
    # ------------------------------------------------------------------

    def on_trade(self, event: TradeEvent):
        try:
            self._queue.put_nowait((_EVT_TRADE, event))
        except Full:
            log.warning("Fila de trades cheia — evento descartado.")

    def on_book(self, event: BookEvent):
        try:
            self._queue.put_nowait((_EVT_BOOK, event))
        except Full:
            pass  # book events são de alto volume; descartar silenciosamente

    def on_daily(self, event: DailyEvent):
        # DailyEvent atualiza apenas o cache de sessão — não vai para fila
        pass

    # ------------------------------------------------------------------
    # Thread escritora
    # ------------------------------------------------------------------

    def _writer_loop(self):
        last_flush = time.time()

        while True:
            # Drenar a fila com timeout
            try:
                evt_type, evt = self._queue.get(timeout=RECORDER["flush_interval_sec"])
            except Empty:
                evt_type, evt = None, None

            if evt_type == _EVT_STOP:
                break

            if evt_type == _EVT_TRADE and evt:
                self._buffer_trade(evt)
            elif evt_type == _EVT_BOOK and evt:
                self._buffer_book(evt)

            # Flush por tamanho de batch
            now = time.time()
            should_flush = (
                len(self._trade_buffer) >= RECORDER["trade_batch_size"]
                or len(self._book_buffer)  >= RECORDER["book_batch_size"]
                or (now - last_flush) >= RECORDER["flush_interval_sec"]
            )

            if should_flush:
                self._flush()
                last_flush = now

            # Flush de agentes (menos frequente)
            if now - self._last_agent_flush >= self._agent_flush_interval:
                self._flush_agents()
                self._last_agent_flush = now

        # Flush final ao encerrar
        self._flush()
        self._flush_agents()

    # ------------------------------------------------------------------
    # Buffering
    # ------------------------------------------------------------------

    def _buffer_trade(self, event: TradeEvent):
        session_id = self._sessions.get(event.ticker)
        self._trade_buffer.append({
            "session_id":    session_id,
            "ticker":        event.ticker,
            "trade_number":  event.trade_number,
            "ts":            event.ts,
            "price":         event.price,
            "qty":           event.qty,
            "volume":        event.volume,
            "buy_agent":     event.buy_agent,
            "sell_agent":    event.sell_agent,
            "trade_type":    event.trade_type,
        })

        # Atualizar cache de agente
        today = date.today()
        from profit_bridge import TRADE_TYPE_BUY, TRADE_TYPE_SELL

        if event.buy_agent:
            key = (today, event.ticker, event.buy_agent)
            c = self._agent_cache[key]
            if event.trade_type == TRADE_TYPE_BUY:
                c["buy_qty"]    += event.qty
                c["buy_trades"] += 1
                c["buy_volume"] += event.volume or 0
            else:
                c["cross_qty"]  += event.qty
            c["dirty"] = True

        if event.sell_agent:
            key = (today, event.ticker, event.sell_agent)
            c = self._agent_cache[key]
            if event.trade_type == TRADE_TYPE_SELL:
                c["sell_qty"]    += event.qty
                c["sell_trades"] += 1
                c["sell_volume"] += event.volume or 0
            else:
                c["cross_qty"]   += event.qty
            c["dirty"] = True

        self._stats["trades"] += 1

    def _buffer_book(self, event: BookEvent):
        session_id = self._sessions.get(event.ticker)
        self._book_buffer.append({
            "session_id": session_id,
            "ticker":     event.ticker,
            "ts":         event.ts,
            "action":     event.action,
            "position":   event.position,
            "side":       event.side,
            "qty":        event.qty,
            "agent":      event.agent,
            "offer_id":   event.offer_id if event.offer_id != 0 else None,
            "price":      event.price if event.price > 0 else None,
        })
        self._stats["book_events"] += 1

    # ------------------------------------------------------------------
    # Flush para o banco
    # ------------------------------------------------------------------

    def _flush(self):
        if not self._trade_buffer and not self._book_buffer:
            return

        try:
            with psycopg2.connect(DB_DSN) as conn:
                with conn.cursor() as cur:
                    if self._trade_buffer:
                        psycopg2.extras.execute_values(cur, """
                            INSERT INTO trades
                                (session_id, ticker, trade_number, ts, price, qty,
                                 volume, buy_agent, sell_agent, trade_type)
                            VALUES %s
                            ON CONFLICT DO NOTHING
                        """, [
                            (r["session_id"], r["ticker"], r["trade_number"],
                             r["ts"], r["price"], r["qty"], r["volume"],
                             r["buy_agent"], r["sell_agent"], r["trade_type"])
                            for r in self._trade_buffer
                        ])
                        self._trade_buffer.clear()

                    if self._book_buffer:
                        psycopg2.extras.execute_values(cur, """
                            INSERT INTO book_events
                                (session_id, ticker, ts, action, position, side,
                                 qty, agent, offer_id, price)
                            VALUES %s
                        """, [
                            (r["session_id"], r["ticker"], r["ts"], r["action"],
                             r["position"], r["side"], r["qty"], r["agent"],
                             r["offer_id"], r["price"])
                            for r in self._book_buffer
                        ])
                        self._book_buffer.clear()

                conn.commit()
                self._stats["flushes"] += 1

        except Exception as e:
            log.error(f"Erro no flush: {e}")
            self._stats["errors"] += 1

    def _flush_agents(self):
        """Upsert do saldo por agente no banco."""
        dirty = {k: v for k, v in self._agent_cache.items() if v["dirty"]}
        if not dirty:
            return

        rows = []
        for (dt, ticker, agent_id), c in dirty.items():
            rows.append((
                dt, ticker, agent_id,
                c["buy_qty"], c["sell_qty"],
                c["buy_trades"], c["sell_trades"],
                c["buy_volume"], c["sell_volume"],
                c["cross_qty"],
            ))
            c["dirty"] = False

        try:
            with psycopg2.connect(DB_DSN) as conn:
                with conn.cursor() as cur:
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO agent_daily
                            (date, ticker, agent_id,
                             buy_qty, sell_qty, buy_trades, sell_trades,
                             buy_volume, sell_volume, cross_qty, updated_at)
                        VALUES %s
                        ON CONFLICT (date, ticker, agent_id) DO UPDATE SET
                            buy_qty     = agent_daily.buy_qty     + EXCLUDED.buy_qty,
                            sell_qty    = agent_daily.sell_qty    + EXCLUDED.sell_qty,
                            buy_trades  = agent_daily.buy_trades  + EXCLUDED.buy_trades,
                            sell_trades = agent_daily.sell_trades + EXCLUDED.sell_trades,
                            buy_volume  = agent_daily.buy_volume  + EXCLUDED.buy_volume,
                            sell_volume = agent_daily.sell_volume + EXCLUDED.sell_volume,
                            cross_qty   = agent_daily.cross_qty   + EXCLUDED.cross_qty,
                            updated_at  = NOW()
                    """, rows)
                conn.commit()
        except Exception as e:
            log.error(f"Erro no flush de agentes: {e}")

    # ------------------------------------------------------------------
    # Sessões
    # ------------------------------------------------------------------

    def _init_db(self):
        """Aplica o schema se as tabelas não existirem."""
        import os
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        if not os.path.isfile(schema_path):
            log.warning("schema.sql não encontrado — tabelas devem existir.")
            return
        try:
            with psycopg2.connect(DB_DSN) as conn:
                with conn.cursor() as cur:
                    with open(schema_path, "r", encoding="utf-8") as f:
                        sql = f.read()
                    # Remover linhas de CREATE DATABASE (requerem conexão fora de transação)
                    lines = [l for l in sql.splitlines()
                             if not l.strip().upper().startswith("CREATE DATABASE")]
                    cur.execute("\n".join(lines))
                conn.commit()
            log.info("Schema verificado/criado com sucesso.")
        except Exception as e:
            log.error(f"Erro ao aplicar schema: {e}")

    def _open_sessions(self):
        today = date.today()
        try:
            with psycopg2.connect(DB_DSN) as conn:
                with conn.cursor() as cur:
                    for asset in ASSETS:
                        ticker = asset["ticker"]
                        cur.execute("""
                            INSERT INTO sessions (date, ticker, started_at)
                            VALUES (%s, %s, NOW())
                            ON CONFLICT (date, ticker) DO UPDATE
                                SET started_at = NOW(), ended_at = NULL
                            RETURNING id
                        """, (today, ticker))
                        session_id = cur.fetchone()[0]
                        self._sessions[ticker] = session_id
                        log.info(f"Sessão aberta: {ticker} → session_id={session_id}")
                conn.commit()
        except Exception as e:
            log.error(f"Erro ao abrir sessões: {e}")

    def _close_sessions(self):
        if not self._sessions:
            return
        try:
            with psycopg2.connect(DB_DSN) as conn:
                with conn.cursor() as cur:
                    for ticker, session_id in self._sessions.items():
                        cur.execute("""
                            UPDATE sessions
                            SET ended_at     = NOW(),
                                total_trades = (
                                    SELECT COUNT(*) FROM trades WHERE session_id = %s
                                ),
                                total_qty    = (
                                    SELECT COALESCE(SUM(qty), 0) FROM trades WHERE session_id = %s
                                ),
                                total_volume = (
                                    SELECT COALESCE(SUM(volume), 0) FROM trades WHERE session_id = %s
                                )
                            WHERE id = %s
                        """, (session_id, session_id, session_id, session_id))
                        log.info(f"Sessão fechada: {ticker} (id={session_id})")
                conn.commit()
        except Exception as e:
            log.error(f"Erro ao fechar sessões: {e}")

    # ------------------------------------------------------------------
    # Status em tempo real
    # ------------------------------------------------------------------

    def status(self) -> str:
        q = self._queue.qsize()
        return (
            f"Trades gravados: {self._stats['trades']}  |  "
            f"Book events: {self._stats['book_events']}  |  "
            f"Flushes: {self._stats['flushes']}  |  "
            f"Erros: {self._stats['errors']}  |  "
            f"Fila: {q}"
        )
