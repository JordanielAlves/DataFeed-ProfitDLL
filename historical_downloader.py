"""
historical_downloader.py
Baixa histórico de trades com agente via GetHistoryTrades da ProfitDLL.

Funciona INDEPENDENTE do gravador em tempo real.
Execute após conectar a DLL para backfill de dados históricos.

Uso:
    python historical_downloader.py --dias 30
    python historical_downloader.py --inicio 01/04/2025 --fim 30/05/2025
"""

import argparse
import logging
import threading
import time
from collections import defaultdict
from ctypes import *
from datetime import date, datetime, timedelta
from typing import Optional

import psycopg2
import psycopg2.extras

from config import DB_DSN, ASSETS
from profit_bridge import (
    TAssetID, ProfitBridge,
    TRADE_TYPE_BUY, TRADE_TYPE_SELL, TRADE_TYPE_CROSS,
    is_buy_aggression, is_sell_aggression, is_relevant,
)

log = logging.getLogger("historical")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

# ---------------------------------------------------------------------------
# Feriados B3 — atualizar anualmente
# ---------------------------------------------------------------------------
FERIADOS_B3 = {
    date(2025, 1, 1),   # Ano Novo
    date(2025, 3, 3),   # Carnaval
    date(2025, 3, 4),   # Carnaval
    date(2025, 4, 18),  # Sexta-feira Santa
    date(2025, 4, 21),  # Tiradentes
    date(2025, 5, 1),   # Dia do Trabalho
    date(2025, 6, 19),  # Corpus Christi
    date(2025, 9, 7),   # Independência
    date(2025, 10, 12), # Nossa Senhora Aparecida
    date(2025, 11, 2),  # Finados
    date(2025, 11, 15), # Proclamação República
    date(2025, 11, 20), # Consciência Negra
    date(2025, 12, 25), # Natal
    date(2026, 1, 1),
    date(2026, 2, 16),  # Carnaval
    date(2026, 2, 17),
    date(2026, 4, 3),   # Sexta-feira Santa
    date(2026, 4, 21),
    date(2026, 5, 1),
    date(2026, 6, 4),   # Corpus Christi
    date(2026, 9, 7),
    date(2026, 10, 12),
    date(2026, 11, 2),
    date(2026, 11, 15),
    date(2026, 11, 20),
    date(2026, 12, 25),
}

def is_pregao(d: date) -> bool:
    return d.weekday() < 5 and d not in FERIADOS_B3


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------
class HistoricalDownloader:

    # Horários do pregão por ativo (ajustar se necessário)
    HORARIOS = {
        "DOLPRO": ("09:00:00", "18:15:00"),
        "WDOK25": ("09:00:00", "18:15:00"),
        "WDOJ25": ("09:00:00", "18:15:00"),
        "DOLK25": ("09:00:00", "18:15:00"),
        "DOLJ25": ("09:00:00", "18:15:00"),
        "_default": ("09:00:00", "18:15:00"),
    }

    def __init__(self, dll: WinDLL):
        self._dll = dll

        # Estado por requisição
        self._trades:   list  = []
        self._done:     threading.Event = threading.Event()
        self._lock:     threading.Lock  = threading.Lock()
        self._progress: int   = 0

        # Manter referências dos callbacks (evitar GC)
        self._cb_trade    = self._make_trade_callback()
        self._cb_progress = self._make_progress_callback()

        # Registrar callbacks na DLL
        self._dll.SetHistoryTradeCallback(self._cb_trade)
        self._dll.SetSerieProgressCallback(self._cb_progress)

        log.info("HistoricalDownloader inicializado.")

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def baixar_dia(self, ticker: str, exchange: str, data: date) -> list:
        """
        Baixa todos os trades de um ativo em uma data.
        Retorna lista de dicts com os campos do trade.
        """
        h_ini, h_fim = self.HORARIOS.get(ticker, self.HORARIOS["_default"])
        data_str = data.strftime("%d/%m/%Y")
        inicio   = f"{data_str} {h_ini}"
        fim      = f"{data_str} {h_fim}"

        with self._lock:
            self._trades.clear()
            self._done.clear()
            self._progress = 0

        ret = self._dll.GetHistoryTrades(
            c_wchar_p(ticker),
            c_wchar_p(exchange),
            c_wchar_p(inicio),
            c_wchar_p(fim),
        )

        if ret != 0:
            log.warning(f"{ticker} {data_str}: GetHistoryTrades retornou {ret}")
            return []

        # Aguardar progresso atingir 100
        if not self._done.wait(timeout=300):
            log.error(f"{ticker} {data_str}: timeout aguardando histórico")
            return []

        return list(self._trades)

    def baixar_periodo(
        self,
        ticker: str,
        exchange: str,
        data_ini: date,
        data_fim: date,
        persistir: bool = True,
    ) -> int:
        """
        Baixa e persiste histórico para um intervalo de datas.
        Retorna total de trades gravados.
        """
        total = 0
        d = data_ini

        while d <= data_fim:
            if not is_pregao(d):
                d += timedelta(days=1)
                continue

            # Verificar se já temos dados desse dia
            if persistir and self._dia_ja_gravado(ticker, d):
                log.info(f"  {ticker} {d}: já gravado — pulando.")
                d += timedelta(days=1)
                continue

            log.info(f"  Baixando {ticker} {d.strftime('%d/%m/%Y')}...")
            trades = self.baixar_dia(ticker, exchange, d)

            if trades:
                log.info(f"    {len(trades)} trades recebidos.")
                if persistir:
                    gravados = self._persistir(ticker, d, trades)
                    total += gravados
                else:
                    total += len(trades)
            else:
                log.info(f"    Sem trades (feriado ou mercado fechado).")

            # Pausa entre requisições para não sobrecarregar a DLL
            time.sleep(0.5)
            d += timedelta(days=1)

        return total

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    def _dia_ja_gravado(self, ticker: str, d: date) -> bool:
        """Verifica se já existe pelo menos um trade gravado para esse dia."""
        try:
            with psycopg2.connect(DB_DSN) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 1 FROM trades
                        WHERE ticker = %s
                          AND ts::date = %s
                        LIMIT 1
                    """, (ticker, d))
                    return cur.fetchone() is not None
        except Exception:
            return False

    def _persistir(self, ticker: str, d: date, trades: list) -> int:
        """
        Persiste lista de trades no PostgreSQL.
        Atualiza também o agent_daily.
        Retorna número de trades inseridos.
        """
        # Garantir sessão histórica para esse dia
        session_id = self._garantir_sessao(ticker, d)

        # Preparar rows de trades (filtrar tipos irrelevantes)
        rows_trades = []
        agent_acc   = defaultdict(lambda: {
            "buy_qty": 0, "sell_qty": 0,
            "buy_trades": 0, "sell_trades": 0,
            "buy_volume": 0.0, "sell_volume": 0.0,
            "cross_qty": 0,
        })

        for t in trades:
            trade_type = t["trade_type"]

            # Parse do timestamp
            try:
                ts = datetime.strptime(t["date"], "%d/%m/%Y %H:%M:%S.%f")
            except ValueError:
                try:
                    ts = datetime.strptime(t["date"], "%d/%m/%Y %H:%M:%S")
                except ValueError:
                    continue

            rows_trades.append((
                session_id,
                ticker,
                t["trade_number"],
                ts,
                t["price"],
                t["qtd"],
                t["vol"],
                t["buy_agent"],
                t["sell_agent"],
                trade_type,
            ))

            # Acumular saldo por agente (apenas fluxo real)
            if not is_relevant(trade_type):
                continue

            if t["buy_agent"]:
                c = agent_acc[(t["buy_agent"], "buy")]
                if is_buy_aggression(trade_type):
                    c["buy_qty"]    += t["qtd"]
                    c["buy_trades"] += 1
                    c["buy_volume"] += t["vol"] or 0
                else:
                    c["cross_qty"]  += t["qtd"]

            if t["sell_agent"]:
                c = agent_acc[(t["sell_agent"], "sell")]
                if is_sell_aggression(trade_type):
                    c["sell_qty"]    += t["qtd"]
                    c["sell_trades"] += 1
                    c["sell_volume"] += t["vol"] or 0
                else:
                    c["cross_qty"]   += t["qtd"]

        if not rows_trades:
            return 0

        try:
            with psycopg2.connect(DB_DSN) as conn:
                with conn.cursor() as cur:
                    # Trades
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO trades
                            (session_id, ticker, trade_number, ts, price, qty,
                             volume, buy_agent, sell_agent, trade_type)
                        VALUES %s
                        ON CONFLICT DO NOTHING
                    """, rows_trades)

                    # Agent daily
                    agent_rows = []
                    # Consolidar por agent_id
                    consolidated = defaultdict(lambda: {
                        "buy_qty": 0, "sell_qty": 0,
                        "buy_trades": 0, "sell_trades": 0,
                        "buy_volume": 0.0, "sell_volume": 0.0,
                        "cross_qty": 0,
                    })
                    for (agent_id, side), c in agent_acc.items():
                        cc = consolidated[agent_id]
                        for k in c:
                            cc[k] += c[k]

                    for agent_id, c in consolidated.items():
                        agent_rows.append((
                            d, ticker, agent_id,
                            c["buy_qty"], c["sell_qty"],
                            c["buy_trades"], c["sell_trades"],
                            c["buy_volume"], c["sell_volume"],
                            c["cross_qty"],
                        ))

                    if agent_rows:
                        psycopg2.extras.execute_values(cur, """
                            INSERT INTO agent_daily
                                (date, ticker, agent_id,
                                 buy_qty, sell_qty, buy_trades, sell_trades,
                                 buy_volume, sell_volume, cross_qty)
                            VALUES %s
                            ON CONFLICT (date, ticker, agent_id) DO UPDATE SET
                                buy_qty     = EXCLUDED.buy_qty,
                                sell_qty    = EXCLUDED.sell_qty,
                                buy_trades  = EXCLUDED.buy_trades,
                                sell_trades = EXCLUDED.sell_trades,
                                buy_volume  = EXCLUDED.buy_volume,
                                sell_volume = EXCLUDED.sell_volume,
                                cross_qty   = EXCLUDED.cross_qty,
                                updated_at  = NOW()
                        """, agent_rows)

                conn.commit()
            return len(rows_trades)

        except Exception as e:
            log.error(f"Erro ao persistir {ticker} {d}: {e}")
            return 0

    def _garantir_sessao(self, ticker: str, d: date) -> int:
        """Cria ou retorna a sessão histórica para ticker+data."""
        try:
            with psycopg2.connect(DB_DSN) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO sessions (date, ticker, started_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (date, ticker) DO UPDATE
                            SET started_at = EXCLUDED.started_at
                        RETURNING id
                    """, (d, ticker, datetime.combine(d, datetime.min.time())))
                    session_id = cur.fetchone()[0]
                conn.commit()
            return session_id
        except Exception as e:
            log.error(f"Erro ao criar sessão para {ticker} {d}: {e}")
            return None

    # ------------------------------------------------------------------
    # Callbacks da DLL
    # ------------------------------------------------------------------

    def _make_trade_callback(self):
        downloader = self

        @WINFUNCTYPE(None,
                     TAssetID,   # asset (por valor)
                     c_wchar_p,  # date
                     c_uint,     # tradeNumber
                     c_double,   # price
                     c_double,   # vol
                     c_int,      # qtd
                     c_int,      # buyAgent
                     c_int,      # sellAgent
                     c_int)      # tradeType
        def _cb(asset, date_str, trade_number, price, vol,
                qtd, buy_agent, sell_agent, trade_type):
            downloader._trades.append({
                "date":         date_str,
                "trade_number": trade_number,
                "price":        price,
                "vol":          vol,
                "qtd":          qtd,
                "buy_agent":    buy_agent,
                "sell_agent":   sell_agent,
                "trade_type":   trade_type,
            })

        return _cb

    def _make_progress_callback(self):
        downloader = self

        @WINFUNCTYPE(None, TAssetID, c_int)
        def _cb(asset, progress):
            downloader._progress = progress
            if progress >= 100:
                downloader._done.set()

        return _cb


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Download de histórico de trades — ProfitDLL"
    )
    parser.add_argument("--dias", type=int, default=30,
                        help="Quantos dias retroativos baixar (padrão: 30)")
    parser.add_argument("--inicio", type=str, default=None,
                        help="Data inicial DD/MM/YYYY")
    parser.add_argument("--fim", type=str, default=None,
                        help="Data final DD/MM/YYYY (padrão: hoje)")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Baixar só este ticker (padrão: todos de config.py)")
    args = parser.parse_args()

    # Determinar intervalo
    hoje = date.today()
    if args.inicio:
        data_ini = datetime.strptime(args.inicio, "%d/%m/%Y").date()
        data_fim = datetime.strptime(args.fim, "%d/%m/%Y").date() if args.fim else hoje
    else:
        data_fim = hoje
        data_ini = hoje - timedelta(days=args.dias)

    log.info(f"Intervalo: {data_ini.strftime('%d/%m/%Y')} → {data_fim.strftime('%d/%m/%Y')}")

    # Conectar DLL
    from config import DLL_PATH
    import getpass, os

    if not os.path.isfile(DLL_PATH):
        print(f"DLL não encontrada: {DLL_PATH}")
        return

    key      = input("Chave de acesso: ").strip()
    user     = input("Usuário: ").strip()
    password = getpass.getpass("Senha: ")

    bridge = ProfitBridge(DLL_PATH)
    bridge.on_connected = lambda ok: log.info(
        f"{'Conectado' if ok else 'Desconectado'}"
    )

    from profit_bridge import TRADE_TYPE_BUY
    result = bridge.initialize(key, user, password, market_only=True)
    if result != 0:
        log.error(f"Falha na inicialização: {result}")
        return

    log.info("Aguardando conexão...")
    if not bridge.wait_connected(timeout=30):
        log.error("Timeout na conexão.")
        return

    downloader = HistoricalDownloader(bridge._dll)

    # Ativos a baixar
    assets = ASSETS
    if args.ticker:
        assets = [a for a in ASSETS if a["ticker"] == args.ticker.upper()]
        if not assets:
            assets = [{"ticker": args.ticker.upper(), "exchange": "F"}]

    total_geral = 0
    for asset in assets:
        ticker   = asset["ticker"]
        exchange = asset["exchange"]
        log.info(f"\n=== {ticker} ===")
        total = downloader.baixar_periodo(ticker, exchange, data_ini, data_fim)
        log.info(f"  Total gravado: {total} trades")
        total_geral += total

    log.info(f"\nConcluído. Total geral: {total_geral} trades.")
    bridge.finalize()


if __name__ == "__main__":
    main()
