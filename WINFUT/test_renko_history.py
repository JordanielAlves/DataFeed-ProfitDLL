"""
test_renko_history.py
Script para validar o renko_engine.py usando dados históricos do WINFUT já presentes no banco de dados.
"""
import sys
import os
import psycopg2
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import DB_DSN, PRICE_SCALE_BY_PREFIX
from WINFUT.renko_engine import RenkoEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("test_renko")

def on_renko_close(box):
    cor = "VERDE" if box.state_color == 1 else "VERMELHO" if box.state_color == -1 else "NEUTRO"
    trava = "[TRAVADO]" if box.aggression_locked else ""
    sma = f"{box.sma:.1f}" if box.sma is not None else "N/A"
    log.info(f"Box {box.index:03d} fechou em {box.close_price:.0f} | {cor} {trava} | SMA: {sma} | Agressão: {box.aggression_balance:.0f}")

def run_test():
    log.info("Iniciando backtest do Renko com dados históricos do banco...")
    renko = RenkoEngine(box_size=50.0, sma_period=10, aggression_filter=5000.0, on_box_close=on_renko_close)
    
    scale = PRICE_SCALE_BY_PREFIX.get("WIN", 5.0)
    
    # Busca os primeiros 50.000 trades do WIN para teste
    try:
        with psycopg2.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                log.info("Executando query no banco (limitado a 100k trades para teste rápido)...")
                cur.execute("""
                    SELECT price, qty, trade_type
                    FROM trades 
                    WHERE ticker = 'WINFUT'
                    ORDER BY ts ASC
                    LIMIT 100000
                """)
                
                rows = cur.fetchall()
                if not rows:
                    log.warning("Nenhum dado encontrado para WIN no banco.")
                    return
                    
                log.info(f"Processando {len(rows)} trades...")
                
                for price_raw, qty, t_type in rows:
                    real_price = float(price_raw) * scale
                    vol = 0.0
                    if t_type == 2:   # Compra agredida
                        vol = qty
                    elif t_type == 3: # Venda agredida
                        vol = -qty
                        
                    renko.process_trade(real_price, vol)
                    
        log.info(f"Fim do processamento. Total de boxes gerados: {len(renko.boxes)}")
    except Exception as e:
        log.error(f"Erro ao acessar banco de dados: {e}")

if __name__ == "__main__":
    run_test()
