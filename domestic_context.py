"""
domestic_context.py
Mantém o contexto macroeconômico doméstico atualizado em tempo real.
Consulta o PostgreSQL com índices ultra-rápidos para obter a variação intradiária (delta desde a abertura)
do Mini Índice (WIN) e dos Juros Futuros (DI1).
"""

import time
import threading
import logging
from datetime import datetime, date
import psycopg2
from config import DB_DSN, ASSETS
from price_utils import to_real_points

log = logging.getLogger("DomesticContext")


def _get_active_tickers():
    """Identifica os tickers vigentes de WIN e DI configurados."""
    win_ticker = "WINV26"
    di_ticker = "DI1F29"
    for item in ASSETS:
        t = item["ticker"] if isinstance(item, dict) else item
        if t.startswith("WIN"):
            win_ticker = t
        elif t.startswith("DI1") and (t.endswith("29") or t.endswith("27")):
            di_ticker = t
    return win_ticker, di_ticker


class DomesticContextManager:
    """
    Mantém o contexto macroeconômico doméstico em tempo real consultando o PostgreSQL.
    Neste projeto, WIN (Mini Índice) e DI1 (Juros Futuros) são bússolas direcionais:
      - WIN em alta forte / DI1 em queda forte = Apetite a risco (Dólar tende a cair).
      - WIN em queda forte / DI1 em alta forte = Aversão a risco (Dólar tende a subir).
    """
    def __init__(self, update_interval_sec=10, dsn: str = DB_DSN):
        self.update_interval_sec = update_interval_sec
        self.dsn = dsn
        self.win_delta_pts = 0.0
        self.di1_delta_pts = 0.0
        self.win_price = 0.0
        self.win_open = 0.0
        self.di1_price = 0.0
        self.di1_open = 0.0
        self.last_update = None
        self._running = False
        self._thread = None
        self.win_ticker, self.di_ticker = _get_active_tickers()

    def start(self):
        if not self._running:
            self._running = True
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="DomesticContextThread"
            )
            self._thread.start()
            log.info(f"Thread de contexto doméstico iniciada ({self.win_ticker} / {self.di_ticker}).")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _loop(self):
        self._update_from_db()
        while self._running:
            time.sleep(self.update_interval_sec)
            self._update_from_db()

    def _update_from_db(self):
        try:
            today_str = date.today().isoformat()
            d_start = f"{today_str} 00:00:00"
            d_end = f"{today_str} 23:59:59"

            with psycopg2.connect(self.dsn) as conn:
                with conn.cursor() as cur:
                    # 1. Buscar WIN do dia (abertura e último preço usando índice (ticker, ts))
                    cur.execute("""
                        SELECT price 
                        FROM trades 
                        WHERE ticker = %s AND ts >= %s AND ts <= %s 
                        ORDER BY ts ASC LIMIT 1;
                    """, (self.win_ticker, d_start, d_end))
                    row_win_open = cur.fetchone()

                    cur.execute("""
                        SELECT price 
                        FROM trades 
                        WHERE ticker = %s AND ts >= %s AND ts <= %s 
                        ORDER BY ts DESC LIMIT 1;
                    """, (self.win_ticker, d_start, d_end))
                    row_win_last = cur.fetchone()

                    if row_win_open and row_win_last:
                        self.win_open = to_real_points(row_win_open[0], self.win_ticker)
                        self.win_price = to_real_points(row_win_last[0], self.win_ticker)
                        self.win_delta_pts = round(self.win_price - self.win_open, 1)

                    # 2. Buscar DI1 do dia (abertura e último preço usando índice (ticker, ts))
                    cur.execute("""
                        SELECT price 
                        FROM trades 
                        WHERE ticker = %s AND ts >= %s AND ts <= %s 
                        ORDER BY ts ASC LIMIT 1;
                    """, (self.di_ticker, d_start, d_end))
                    row_di_open = cur.fetchone()

                    cur.execute("""
                        SELECT price 
                        FROM trades 
                        WHERE ticker = %s AND ts >= %s AND ts <= %s 
                        ORDER BY ts DESC LIMIT 1;
                    """, (self.di_ticker, d_start, d_end))
                    row_di_last = cur.fetchone()

                    if row_di_open and row_di_last:
                        self.di1_open = to_real_points(row_di_open[0], self.di_ticker)
                        self.di1_price = to_real_points(row_di_last[0], self.di_ticker)
                        # Em bps (1% = 100 bps)
                        self.di1_delta_pts = round((self.di1_price - self.di1_open) * 100.0, 2)

            self.last_update = datetime.now()
            log.debug(
                f"Contexto doméstico atualizado — {self.win_ticker}: {self.win_price:.0f} ({self.win_delta_pts:+.0f} pts) | "
                f"{self.di_ticker}: {self.di1_price:.3f}% ({self.di1_delta_pts:+.1f} bps)"
            )

        except Exception as e:
            log.debug(f"Erro ao atualizar contexto doméstico via DB: {e}")

    def get_context(self) -> dict:
        """Retorna o contexto doméstico instantâneo, garantindo que o serviço esteja ativo."""
        if not self._running:
            self.start()
            if self.last_update is None:
                self._update_from_db()

        return {
            "win_delta_pts": self.win_delta_pts,
            "di1_delta_pts": self.di1_delta_pts,
            "win_price":     self.win_price,
            "di1_price":     self.di1_price,
            "win_ticker":    self.win_ticker,
            "di_ticker":     self.di_ticker,
            "last_update":   self.last_update.isoformat() if self.last_update else None
        }


# Instância Singleton
_domestic_context = DomesticContextManager()


def start_domestic_context():
    _domestic_context.start()


def stop_domestic_context():
    _domestic_context.stop()


def get_domestic_context() -> dict:
    return _domestic_context.get_context()


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    print(json.dumps(get_domestic_context(), indent=2, default=str))
