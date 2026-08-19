import logging
from datetime import datetime

log = logging.getLogger("DomesticContext")

class DomesticContextManager:
    """
    Mantém o contexto macroeconômico doméstico em memória.
    Neste projeto, WIN (Mini Índice) e DI1 (Juros Futuros) são usados como
    bússolas direcionais. 
    A variação (delta) da abertura ao preço atual dita o apetite a risco interno.
    """
    def __init__(self):
        self.win_open = 0.0
        self.win_price = 0.0
        self.di1_open = 0.0
        self.di1_price = 0.0
        self.last_update = None

    def update_price(self, ticker: str, price: float, open_price: float = None):
        """Atualiza o preço em tempo real."""
        # Filtro básico pelo prefixo
        if ticker.startswith("WIN") or ticker.startswith("IND"):
            self.win_price = price
            if open_price and open_price > 0:
                self.win_open = open_price
        elif ticker.startswith("DI1"):
            self.di1_price = price
            if open_price and open_price > 0:
                self.di1_open = open_price
        self.last_update = datetime.now()

    def get_context(self) -> dict:
        """
        Retorna o contexto doméstico: variação em pontos/bps desde a abertura.
        """
        win_delta = (self.win_price - self.win_open) if self.win_open > 0 else 0.0
        di1_delta = (self.di1_price - self.di1_open) if self.di1_open > 0 else 0.0
        
        return {
            "win_delta_pts": win_delta,
            "di1_delta_pts": di1_delta,
            "win_price": self.win_price,
            "di1_price": self.di1_price,
            "last_update": self.last_update.isoformat() if self.last_update else None
        }

# Instância Singleton
_domestic_context = DomesticContextManager()

def update_domestic_asset(ticker: str, price: float, open_price: float = None):
    _domestic_context.update_price(ticker, price, open_price)

def get_domestic_context() -> dict:
    return _domestic_context.get_context()
