import logging
from dataclasses import dataclass
from typing import List, Optional, Callable

@dataclass
class RenkoBox:
    index: int
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    is_up: bool
    aggression_balance: float = 0.0  # Volume agressao comprador - vendedor
    sma: Optional[float] = None
    state_color: int = 0             # 1 = Verde, -1 = Vermelho
    aggression_locked: bool = False

class RenkoEngine:
    """
    Construtor de Gráfico Renko em Tempo Real e Máquina de Estados (Média + Trava).
    Baseado na lógica NTSL para o WINFUT.
    """
    
    def __init__(self, 
                 box_size: float = 50.0, # 10R no indice = 50 pontos de range real (ou 10 ticks)
                 sma_period: int = 10,
                 aggression_filter: float = 5000.0,
                 on_box_close: Optional[Callable[[RenkoBox], None]] = None):
        
        # Como o WINFUT se move de 5 em 5 pontos, 10R = 50 pontos de range de abertura para fechamento
        self.box_size = box_size 
        self.sma_period = sma_period
        self.aggression_filter = aggression_filter
        self.on_box_close = on_box_close
        
        self.boxes: List[RenkoBox] = []
        
        # Estado do box atual em formação
        self._current_open = 0.0
        self._current_high = 0.0
        self._current_low = 0.0
        self._current_is_up = True
        self._current_aggression = 0.0
        
        # Variáveis globais da máquina de estados do indicador
        self._vEstadoCor = 1
        self._vBloqueioAgressao = False
        
        self.log = logging.getLogger("renko_engine")
        
    def _calculate_sma(self) -> Optional[float]:
        """Calcula a SMA dos fechamentos dos últimos `sma_period` boxes."""
        if len(self.boxes) < self.sma_period:
            return None
        recent_closes = [b.close_price for b in self.boxes[-self.sma_period:]]
        return sum(recent_closes) / self.sma_period
        
    def _apply_indicator_logic(self, box: RenkoBox):
        """
        Aplica a lógica NTSL "Média 100% + Trava de Agressão" no box recém-fechado.
        """
        box.sma = self._calculate_sma()
        if box.sma is None:
            # Inicialização (Primeiro box)
            self._vEstadoCor = 1
            self._vBloqueioAgressao = False
            box.state_color = self._vEstadoCor
            box.aggression_locked = self._vBloqueioAgressao
            return
            
        vMMA = box.sma
        vAgressao = box.aggression_balance
        
        # Sinais da Média (Requer Box 100% rompido a favor)
        # NTSL: vSinalMMA_Compra := (Low > vMMA) and (Close > Open)
        vSinalMMA_Compra = (box.low_price > vMMA) and box.is_up
        # NTSL: vSinalMMA_Venda  := (High < vMMA) and (Close < Open)
        vSinalMMA_Venda  = (box.high_price < vMMA) and (not box.is_up)
        
        # Sinais de Agressão
        # NTSL: vSinalAgr_Compra := (vAgressao >= FiltroAgressao) and (Close > Open)
        vSinalAgr_Compra = (vAgressao >= self.aggression_filter) and box.is_up
        # NTSL: vSinalAgr_Venda  := (vAgressao <= -FiltroAgressao) and (Close < Open)
        vSinalAgr_Venda  = (vAgressao <= -self.aggression_filter) and (not box.is_up)
        
        # Máquina de Estados com Trava
        estado_ant = self._vEstadoCor
        trava_ant = self._vBloqueioAgressao
        
        if estado_ant == 1: # TENDÊNCIA VERDE
            if vSinalMMA_Venda:
                self._vEstadoCor = -1
                self._vBloqueioAgressao = False
            elif vSinalAgr_Venda and (not trava_ant):
                self._vEstadoCor = -1
                self._vBloqueioAgressao = True
            else:
                self._vEstadoCor = 1
                self._vBloqueioAgressao = trava_ant
                
        elif estado_ant == -1: # TENDÊNCIA VERMELHA
            if vSinalMMA_Compra:
                self._vEstadoCor = 1
                self._vBloqueioAgressao = False
            elif vSinalAgr_Compra and (not trava_ant):
                self._vEstadoCor = 1
                self._vBloqueioAgressao = True
            else:
                self._vEstadoCor = -1
                self._vBloqueioAgressao = trava_ant
                
        box.state_color = self._vEstadoCor
        box.aggression_locked = self._vBloqueioAgressao
        
    def _close_box(self, is_up: bool, close_price: float):
        """Fecha o box atual e salva na lista."""
        idx = len(self.boxes)
        box = RenkoBox(
            index=idx,
            open_price=self._current_open,
            close_price=close_price,
            high_price=self._current_high,
            low_price=self._current_low,
            is_up=is_up,
            aggression_balance=self._current_aggression
        )
        
        # Processar o indicador NTSL antes de emitir callback
        self._apply_indicator_logic(box)
        
        self.boxes.append(box)
        
        if self.on_box_close:
            self.on_box_close(box)
            
        # Prepara o próximo box
        self._current_open = close_price
        self._current_high = close_price
        self._current_low = close_price
        self._current_is_up = is_up
        self._current_aggression = 0.0

    def process_trade(self, price: float, vol_agressor: float):
        """
        Recebe um trade (preço + delta de agressão).
        vol_agressor: positivo para agressão de compra, negativo para agressão de venda.
        No Índice (WIN), os preços já devem vir em pontos (após correção do tick/escala).
        """
        # Inicialização do primeiro box
        if len(self.boxes) == 0 and self._current_open == 0.0:
            self._current_open = price
            self._current_high = price
            self._current_low = price
            self._current_aggression += vol_agressor
            return
            
        # Atualiza métricas intra-box
        self._current_high = max(self._current_high, price)
        self._current_low = min(self._current_low, price)
        self._current_aggression += vol_agressor
        
        # Verifica fechamento (Regra Padrão do Renko)
        if len(self.boxes) == 0:
            # Primeiro box requer movimento simples
            if price >= self._current_open + self.box_size:
                self._close_box(is_up=True, close_price=self._current_open + self.box_size)
            elif price <= self._current_open - self.box_size:
                self._close_box(is_up=False, close_price=self._current_open - self.box_size)
        else:
            last_box = self.boxes[-1]
            if last_box.is_up:
                # Topo de tendência alta: precisa subir +box_size para novo box verde
                if price >= last_box.close_price + self.box_size:
                    self._close_box(is_up=True, close_price=last_box.close_price + self.box_size)
                # Reversão para baixo: precisa cair -2*box_size a partir do close atual
                elif price <= last_box.close_price - (2 * self.box_size):
                    # O open do box de reversão começa 1 box abaixo do close anterior
                    self._current_open = last_box.close_price - self.box_size
                    self._close_box(is_up=False, close_price=last_box.close_price - (2 * self.box_size))
            else:
                # Fundo de tendência baixa: precisa cair -box_size para novo box vermelho
                if price <= last_box.close_price - self.box_size:
                    self._close_box(is_up=False, close_price=last_box.close_price - self.box_size)
                # Reversão para alta: precisa subir +2*box_size a partir do close atual
                elif price >= last_box.close_price + (2 * self.box_size):
                    # O open do box de reversão começa 1 box acima do close anterior
                    self._current_open = last_box.close_price + self.box_size
                    self._close_box(is_up=True, close_price=last_box.close_price + (2 * self.box_size))
