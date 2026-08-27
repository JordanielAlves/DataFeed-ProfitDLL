"""
global_context.py
Mantém o contexto macroeconômico global atualizado em background.
Busca DXY (Índice do Dólar) e SPX (S&P 500) via yfinance (API do Yahoo Finance).
"""

import time
import threading
import logging
from datetime import datetime

log = logging.getLogger("GlobalContext")

# Símbolos no Yahoo Finance
_SYMBOLS = {
    "DXY": "DX-Y.NYB",  # US Dollar Index (ICE)
    "SPX": "^GSPC",     # S&P 500
}


class GlobalContextManager:
    """
    Mantém o contexto macroeconômico global atualizado em background usando yfinance.
    Busca a variação % no dia do DXY (Índice Dólar) e do SPX (S&P 500).
    """
    def __init__(self, update_interval_sec=60):
        self.update_interval_sec = update_interval_sec
        self.dxy_var = 0.0
        self.spx_var = 0.0
        self.dxy_price = 0.0
        self.spx_price = 0.0
        self.last_update = None
        self._running = False
        self._thread = None
        self._yf_available = False

        try:
            import yfinance as yf  # noqa: F401
            logging.getLogger("yfinance").setLevel(logging.CRITICAL)
            logging.getLogger("urllib3").setLevel(logging.CRITICAL)
            self._yf_available = True
            log.info("yfinance inicializado — contexto macro DXY/SPX ativo.")
        except ImportError:
            log.warning("yfinance nao encontrado. Instale com: pip install yfinance")

    def start(self):
        if not self._yf_available:
            return
        if not self._running:
            self._running = True
            # Inicia thread em background
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="GlobalContextThread"
            )
            self._thread.start()
            log.info("Thread de contexto global iniciada.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _loop(self):
        # Atualizar imediatamente ao iniciar
        self._update_all()
        while self._running:
            time.sleep(self.update_interval_sec)
            self._update_all()

    def _update_all(self):
        try:
            import yfinance as yf

            for key, symbol in _SYMBOLS.items():
                try:
                    info = yf.Ticker(symbol).fast_info
                    last_price = info.last_price
                    open_price = info.open

                    if last_price and open_price and open_price != 0:
                        var_pct = ((last_price - open_price) / open_price) * 100.0
                    else:
                        var_pct = 0.0

                    if key == "DXY":
                        self.dxy_var = round(var_pct, 3)
                        self.dxy_price = round(last_price or 0.0, 4)
                    elif key == "SPX":
                        self.spx_var = round(var_pct, 3)
                        self.spx_price = round(last_price or 0.0, 2)

                except Exception as e:
                    log.debug(f"Erro ao atualizar {key} ({symbol}): {e}")

            self.last_update = datetime.now()
            log.debug(
                f"Contexto macro atualizado — DXY: {self.dxy_price:.4f} ({self.dxy_var:+.2f}%) | "
                f"SPX: {self.spx_price:.2f} ({self.spx_var:+.2f}%)"
            )

        except Exception as e:
            log.debug(f"Erro no loop de Global Context: {e}")

    def get_context(self) -> dict:
        """Retorna o contexto global instantâneo, garantindo que o serviço esteja ativo."""
        if not self._running and self._yf_available:
            self.start()
        return {
            "dxy_var":    self.dxy_var,
            "spx_var":    self.spx_var,
            "dxy_price":  self.dxy_price,
            "spx_price":  self.spx_price,
            "last_update": self.last_update.isoformat() if self.last_update else None,
        }


# Instância Singleton
_global_context = GlobalContextManager()


def start_global_context():
    _global_context.start()


def stop_global_context():
    _global_context.stop()


def get_global_context():
    return _global_context.get_context()


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    start_global_context()
    time.sleep(2)
    print(json.dumps(get_global_context(), indent=2, default=str))
