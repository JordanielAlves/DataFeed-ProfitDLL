"""
win_reversion_backtester.py
Backtest da Estratégia de Reversão à Média (Scalping + ML) no WINFUT.
"""

import sys
import os
import psycopg2
import logging
import pandas as pd
import pickle
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import DB_DSN, PRICE_SCALE_BY_PREFIX
from WINFUT.renko_engine import RenkoEngine
from WINFUT.win_feature_extractor import WinFeatureExtractor

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("reversion_backtester")

class BacktestTracker:
    def __init__(self, name):
        self.name = name
        self.position = 0 # 1 para Compra, -1 para Venda
        self.entry_price = 0.0
        self.trades = []
        
    def enter_long(self, price, ts):
        if self.position == -1:
            self.close_position(price, ts)
        if self.position == 0:
            self.position = 1
            self.entry_price = price
            
    def enter_short(self, price, ts):
        if self.position == 1:
            self.close_position(price, ts)
        if self.position == 0:
            self.position = -1
            self.entry_price = price
            
    def close_position(self, price, ts):
        if self.position != 0:
            pts = (price - self.entry_price) * self.position
            self.trades.append(pts)
            self.position = 0

    def get_stats(self):
        if not self.trades:
            return {"Total_Pts": 0, "Win_Rate": 0, "Total_Trades": 0, "Max_DD": 0, "Profit_Factor": 0}
            
        pts = np.array(self.trades)
        total_pts = pts.sum()
        win_rate = (pts > 0).sum() / len(pts) * 100
        
        cum_pts = pts.cumsum()
        max_peaks = np.maximum.accumulate(cum_pts)
        drawdowns = max_peaks - cum_pts
        max_dd = drawdowns.max() if len(drawdowns) > 0 else 0
        
        gross_profit = pts[pts > 0].sum()
        gross_loss = abs(pts[pts < 0].sum())
        pf = gross_profit / gross_loss if gross_loss != 0 else float('inf')
        
        return {
            "Total_Pts": total_pts,
            "Win_Rate": win_rate,
            "Total_Trades": len(pts),
            "Max_DD": max_dd,
            "Profit_Factor": pf
        }

def run_backtest(limit=300000):
    log.info("Inicializando Backtest de Scalping Reversão...")
    
    model_path = os.path.join(os.path.dirname(__file__), 'win_model.pkl')
    if not os.path.exists(model_path):
        log.error("Modelo não encontrado. Treine o modelo primeiro.")
        return
        
    with open(model_path, 'rb') as f:
        model = pickle.load(f)
        
    scale = 1.0 # O banco de dados já armazena em pontos reais (Escala 1x para WINFUT)
    extractor = WinFeatureExtractor()
    
    tracker = BacktestTracker("Scalper HFT (10h as 12h)")
    current_ts = [None]
    
    feature_cols = [
        'state_color', 'is_locked', 'dist_to_sma', 
        'trades_per_sec', 'buy_imbalance', 'avg_trade_size', 'large_trades_count'
    ]
    
    TAKE_PROFIT_PTS = 30.0
    STOP_LOSS_PTS = 50.0
    
    def on_box_close(box):
        if current_ts[0] is None: return
            
        features = extractor.extract_on_box_close(box, current_ts[0])
        if not features: return
        
        df_feat = pd.DataFrame([features])[feature_cols]
        ml_prediction = model.predict(df_feat)[0] # 0 = Reversão iminente
        
        close_p = box.close_price
        
        # Lógica de Entrada (Somente se não estiver posicionado)
        if tracker.position == 0:
            if box.state_color == 1 and ml_prediction == 0:
                tracker.enter_short(close_p, current_ts[0])
                
            elif box.state_color == -1 and ml_prediction == 0:
                tracker.enter_long(close_p, current_ts[0])

    renko = RenkoEngine(box_size=50.0, sma_period=10, aggression_filter=5000.0, on_box_close=on_box_close)
    
    try:
        with psycopg2.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                log.info(f"Buscando últimos {limit} trades do banco para simulação...")
                cur.execute(f"""
                    SELECT ts, price, qty, trade_type
                    FROM trades 
                    WHERE ticker = 'WINFUT'
                    ORDER BY ts ASC
                    LIMIT {limit}
                """)
                
                rows = cur.fetchall()
                if not rows: return
                
                log.info("Simulando execução tick a tick...")
                for ts, price_raw, qty, t_type in rows:
                    real_price = float(price_raw) * scale
                    current_ts[0] = ts
                    
                    # Gerenciamento de Risco Tick-a-Tick (O segredo do Scalping)
                    if tracker.position != 0:
                        open_pts = (real_price - tracker.entry_price) * tracker.position
                        if open_pts >= TAKE_PROFIT_PTS:
                            tracker.close_position(real_price, ts)
                        elif open_pts <= -STOP_LOSS_PTS:
                            tracker.close_position(real_price, ts)
                            
                    extractor.add_trade(ts, real_price, qty, t_type)
                    
                    vol = qty if t_type == 2 else (-qty if t_type == 3 else 0.0)
                    renko.process_trade(real_price, vol)
                    
    except Exception as e:
        log.error(f"Erro: {e}")
        return

    final_price = renko.boxes[-1].close_price if renko.boxes else 0
    tracker.close_position(final_price, None)
    
    log.info("\n" + "="*50)
    log.info("RESULTADOS DO BACKTEST - SCALPING HFT (10R)")
    log.info(f"Filtro: TP={TAKE_PROFIT_PTS} / SL={STOP_LOSS_PTS} | Horário: 10h-12h")
    log.info("="*50)
    
    s = tracker.get_stats()
    log.info(f"[{tracker.name}]")
    log.info(f"  Trades Feitos: {s['Total_Trades']}")
    log.info(f"  Lucro/Prejuízo Total: {s['Total_Pts']:.0f} Pontos")
    log.info(f"  Taxa de Acerto (Win Rate): {s['Win_Rate']:.1f}%")
    log.info(f"  Fator de Lucro (Profit Factor): {s['Profit_Factor']:.2f}")
    log.info(f"  Máximo Rebaixamento (Max Drawdown): {s['Max_DD']:.0f} Pontos")
    log.info("-" * 50)

if __name__ == "__main__":
    run_backtest(300000)
