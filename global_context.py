import time
import threading
import logging
from tvDatafeed import TvDatafeed, Interval
from datetime import datetime

log = logging.getLogger("GlobalContext")

class GlobalContextManager:
    """
    Mantém o contexto macroeconômico global atualizado em background usando TradingView.
    Busca a variação % no dia do DXY (Índice Dólar) e do SPX (S&P 500).
    """
    def __init__(self, update_interval_sec=10):
        self.update_interval_sec = update_interval_sec
        self.dxy_var = 0.0
        self.spx_var = 0.0
        self.dxy_price = 0.0
        self.spx_price = 0.0
        self.last_update = None
        self._running = False
        self._thread = None
        
        try:
            # Inicializa de forma anônima
            self.tv = TvDatafeed()
            log.info("🌐 [MACRO CONTEXT] TvDatafeed inicializado.")
        except Exception as e:
            log.warning(f"Erro ao inicializar TvDatafeed: {e}")
            self.tv = None

    def start(self):
        if self.tv is None:
            return
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._loop, daemon=True, name="GlobalContextThread")
            self._thread.start()
            log.info("🌐 [MACRO CONTEXT] Thread de contexto global iniciada.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self):
        while self._running:
            try:
                self._update_asset("DXY", "TVC")
                time.sleep(1) # Rate limit gentil
                self._update_asset("SPX", "SP")
                self.last_update = datetime.now()
            except Exception as e:
                log.debug(f"Erro no loop de Global Context: {e}")
            
            time.sleep(self.update_interval_sec)

    def _update_asset(self, symbol, exchange):
        # Buscamos o diário para ter a abertura e o fechamento (atual)
        df = self.tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_daily, n_bars=1)
        if df is not None and not df.empty:
            open_p = df['open'].iloc[-1]
            close_p = df['close'].iloc[-1]
            var_pct = ((close_p - open_p) / open_p) * 100.0
            
            if symbol == "DXY":
                self.dxy_var = var_pct
                self.dxy_price = close_p
            elif symbol == "SPX":
                self.spx_var = var_pct
                self.spx_price = close_p

    def get_context(self) -> dict:
        """
        Retorna o contexto global instantâneo.
        """
        return {
            "dxy_var": round(self.dxy_var, 3),
            "spx_var": round(self.spx_var, 3),
            "dxy_price": self.dxy_price,
            "spx_price": self.spx_price,
            "last_update": self.last_update.isoformat() if self.last_update else None
        }

# Instância Singleton opcional
_global_context = GlobalContextManager()

def start_global_context():
    _global_context.start()

def stop_global_context():
    _global_context.stop()

def get_global_context():
    return _global_context.get_context()
