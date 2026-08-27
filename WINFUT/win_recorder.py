"""
win_recorder.py

Script dedicado para captura de fluxo e construção do Renko para o WINFUT.
Isola a execução para não interferir na captura do Dólar principal.
"""
import os
import sys
import time
import logging

# Adiciona o diretório raiz ao PYTHONPATH para importar os módulos centrais
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from profit_bridge import ProfitBridge, TradeEvent
from data_recorder import DataRecorder
from config import DLL_PATH, PROFIT, ASSETS, PRICE_SCALE_BY_PREFIX

from WINFUT.renko_engine import RenkoEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
log = logging.getLogger("win_recorder")

def main():
    log.info("Inicializando Gravador WINFUT e Motor Renko...")
    
    # 1. Configurar o Motor Renko
    def on_renko_close(box):
        cor_nome = "VERDE" if box.state_color == 1 else "VERMELHO"
        trava = " [TRAVADO]" if box.aggression_locked else ""
        log.info(f">>> [RENKO] Fechamento Box {box.index}: {box.close_price:.0f} | Cor: {cor_nome}{trava} | SMA: {box.sma:.1f} | Agressão (Saldo): {box.aggression_balance:.0f}")

    # No WIN (Índice), 15R equivale a 75 pontos de movimentação direcional do box
    renko = RenkoEngine(box_size=75.0, sma_period=10, aggression_filter=5000.0, on_box_close=on_renko_close)

    # 2. Inicializar DLL e Recorder do DB
    bridge = ProfitBridge(DLL_PATH)
    recorder = DataRecorder()

    # 3. Interceptar trades para alimentar o Renko E gravar no banco
    def on_trade_handler(evt: TradeEvent):
        # Envia pro banco de dados
        recorder.on_trade(evt)
        
        # O preço do WIN já vem da DLL em formato bruto. Precisamos aplicar a escala
        # WIN escala = 5 (vem 26000 -> real 130000)
        prefix = evt.ticker[:3]
        scale = PRICE_SCALE_BY_PREFIX.get(prefix, 1.0)
        real_price = evt.price * scale
        
        # volume agressão
        # Se for trade direto sem agressão (type 1), ignoramos o saldo
        vol = 0.0
        if evt.trade_type == 2:   # Comprador agrediu
            vol = evt.qty
        elif evt.trade_type == 3: # Vendedor agrediu
            vol = -evt.qty
            
        renko.process_trade(real_price, vol)

    bridge.on_trade = on_trade_handler
    
    # 4. Iniciar infraestrutura
    recorder.start()
    
    try:
        bridge.Initialize(PROFIT["key"], PROFIT["user"], PROFIT["password"])
        
        # Assinar apenas os ativos de Índice que estão na config
        win_assets = [a["ticker"] for a in ASSETS if a["ticker"].startswith("WIN") or a["ticker"].startswith("IND")]
        
        for t in win_assets:
            log.info(f"Assinando Trade para: {t}")
            bridge.SubscribeTrade(t)
            
        log.info("Sistema operando. Pressione Ctrl+C para encerrar.")
        
        # Mantém a thread principal viva
        while True:
            time.sleep(1.0)
            
    except KeyboardInterrupt:
        log.info("Encerrando execução pelo usuário...")
    finally:
        recorder.stop()
        bridge.Finalize()
        log.info("Gravador WINFUT finalizado com sucesso.")

if __name__ == "__main__":
    main()
