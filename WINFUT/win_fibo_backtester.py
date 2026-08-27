"""
win_fibo_backtester.py
Backtest da Estratégia de Pullback (Fibonacci 38.2%) no Renko 10R do WINFUT.
"""

import sys
import os
import psycopg2
import logging
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import DB_DSN
from WINFUT.renko_engine import RenkoEngine
from WINFUT.dynamic_harmonics_win import get_daily_harmonic_step, get_closest_harmonic_distance

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("fibo_backtester")

class BacktestTracker:
    def __init__(self, name):
        self.name = name
        self.position = 0 # 1 para Compra, -1 para Venda
        self.entry_price = 0.0
        self.trades = []
        
    def enter_long(self, price, ts):
        if self.position == 0:
            self.position = 1
            self.entry_price = price
            
    def enter_short(self, price, ts):
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
    log.info("Inicializando Backtest de Pullback Fibo 38.2% (Price Action Puro)...")
    
    scale = 1.0 # Banco de dados já fornece pontos reais para o WINFUT
    tracker = BacktestTracker("Fibo 38.2%")
    current_ts = [None]
    
    TAKE_PROFIT_PTS = 50.0  # 1 Box Renko de ganho
    STOP_LOSS_PTS = 100.0   # 2 Boxes Renko de loss (espaço pro pullback evoluir)
    
    zigzag = {
        "direction": 0, # 1 for UP, -1 for DOWN
        "peak": None,
        "trough": None,
        "pending_buy_limit": None,
        "pending_sell_limit": None,
        "reversal_threshold": 150.0,  # 3 boxes to confirm a leg
        "axis_price": None,
        "harmonic_step": None,
        "ignored_by_filter": 0
    }
    
    def on_box_close(box):
        if current_ts[0] is None: return
        
        # Initialization
        if zigzag["direction"] == 0:
            if zigzag["peak"] is None:
                zigzag["peak"] = box.high_price
                zigzag["trough"] = box.low_price
            
            zigzag["peak"] = max(zigzag["peak"], box.high_price)
            zigzag["trough"] = min(zigzag["trough"], box.low_price)
            
            if box.close_price >= zigzag["trough"] + zigzag["reversal_threshold"]:
                zigzag["direction"] = 1
            elif box.close_price <= zigzag["peak"] - zigzag["reversal_threshold"]:
                zigzag["direction"] = -1
                
        elif zigzag["direction"] == 1:
            # We are in an UP leg
            if box.high_price > zigzag["peak"]:
                # New High! Trail the peak.
                zigzag["peak"] = box.high_price
                # Cancel any pending sell limit because the upward leg broke out!
                zigzag["pending_sell_limit"] = None
                
            # Check for reversal DOWN
            if box.close_price <= zigzag["peak"] - zigzag["reversal_threshold"]:
                # Reversal confirmed! The UP leg is complete.
                completed_trough = zigzag["trough"]
                completed_peak = zigzag["peak"]
                
                # Setup for the new DOWN leg
                zigzag["direction"] = -1
                zigzag["trough"] = box.low_price # Start tracking new trough
                
                # Trace Fibo for the completed UP leg to set a BUY limit on the pullback
                leg_size = completed_peak - completed_trough
                if leg_size >= 150:
                    fibo_38 = completed_peak - (0.382 * leg_size)
                    fibo_0 = completed_peak
                    fibo_61 = completed_peak - (0.618 * leg_size)
                    
                    # Filtro de Harmônicos (Opção A)
                    if zigzag["axis_price"] is not None and zigzag["harmonic_step"] is not None:
                        dist = get_closest_harmonic_distance(fibo_38, zigzag["axis_price"], zigzag["harmonic_step"])
                        if dist > 50.0:  # Muito longe da proteção institucional (apenas permitimos trades 'colados' nos harmônicos)
                            zigzag["pending_buy_limit"] = None
                            zigzag["pending_sell_limit"] = None
                            zigzag["ignored_by_filter"] += 1
                            return

                    zigzag["pending_buy_limit"] = {
                        "entry": fibo_38,
                        "tp": fibo_0,
                        "sl": fibo_61
                    }
                    zigzag["pending_sell_limit"] = None
                    
        elif zigzag["direction"] == -1:
            # We are in a DOWN leg
            if box.low_price < zigzag["trough"]:
                # New Low! Trail the trough.
                zigzag["trough"] = box.low_price
                # Cancel any pending buy limit because the downward leg broke out!
                zigzag["pending_buy_limit"] = None
                
            # Check for reversal UP
            if box.close_price >= zigzag["trough"] + zigzag["reversal_threshold"]:
                # Reversal confirmed! The DOWN leg is complete.
                completed_peak = zigzag["peak"]
                completed_trough = zigzag["trough"]
                
                # Setup for the new UP leg
                zigzag["direction"] = 1
                zigzag["peak"] = box.high_price # Start tracking new peak
                
                # Trace Fibo for the completed DOWN leg to set a SELL limit on the pullback
                leg_size = completed_peak - completed_trough
                if leg_size >= 150:
                    fibo_38 = completed_trough + (0.382 * leg_size)
                    fibo_0 = completed_trough
                    fibo_61 = completed_trough + (0.618 * leg_size)
                    
                    # Filtro de Harmônicos (Opção A)
                    if zigzag["axis_price"] is not None and zigzag["harmonic_step"] is not None:
                        dist = get_closest_harmonic_distance(fibo_38, zigzag["axis_price"], zigzag["harmonic_step"])
                        if dist > 50.0:  # Muito longe da proteção institucional (apenas permitimos trades 'colados' nos harmônicos)
                            zigzag["pending_sell_limit"] = None
                            zigzag["pending_buy_limit"] = None
                            zigzag["ignored_by_filter"] += 1
                            return

                    zigzag["pending_sell_limit"] = {
                        "entry": fibo_38,
                        "tp": fibo_0,
                        "sl": fibo_61
                    }
                    zigzag["pending_buy_limit"] = None

    renko = RenkoEngine(box_size=50.0, sma_period=10, aggression_filter=5000.0, on_box_close=on_box_close)
    
    # Controle da posição atual
    active_trade = {"tp": 0.0, "sl": 0.0}
    
    try:
        with psycopg2.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                log.info(f"Buscando pregão 2026-07-10 (das 10h às 12h) para simulação...")
                cur.execute(f"""
                    SELECT ts, price, qty, trade_type
                    FROM trades 
                    WHERE ticker = 'WINFUT'
                    AND ts >= '2026-07-10 10:00:00-03'
                    AND ts < '2026-07-10 12:00:00-03'
                    ORDER BY ts ASC
                """)
                
                rows = cur.fetchall()
                if not rows: return
                
                log.info(f"Simulando apregoamento tick a tick com TP/SL dinâmico (10h as 12h)... ({len(rows)} ticks carregados)")
                
                last_ts = None
                
                for ts, price_raw, qty, t_type in rows:
                    real_price = float(price_raw) * scale
                    
                    # Se tiver um gap gigante (novo dia), reseta o motor
                    if last_ts is not None and (ts - last_ts).total_seconds() > 3600:
                        renko.boxes.clear()
                        zigzag["direction"] = 0
                        zigzag["peak"] = None
                        zigzag["trough"] = None
                        zigzag["pending_buy_limit"] = None
                        zigzag["pending_sell_limit"] = None
                        # Fecha a posicao se estiver aberto ao fim do dia anterior
                        if tracker.position != 0:
                            tracker.close_position(real_price, last_ts)
                            active_trade["tp"] = 0.0
                            active_trade["sl"] = 0.0
                    
                    last_ts = ts
                    current_ts[0] = ts
                    
                    if zigzag["axis_price"] is None:
                        zigzag["axis_price"] = real_price
                        # We pass auto_sync=False because backtest shouldn't try to sync OHLC inside the tick loop
                        zigzag["harmonic_step"] = get_daily_harmonic_step(ts.date(), cur, auto_sync=False)
                        log.info(f"--- 10:00 ------------------------------")
                        log.info(f"Eixo (Abertura): {real_price:.2f}")
                        log.info(f"Harmonic Step: {zigzag['harmonic_step']:.1f}")
                        log.info(f"----------------------------------------")
                        
                    # 1. Gerenciamento de Risco Posição Aberta
                    if tracker.position == 1:
                        if real_price >= active_trade["tp"]:
                            tracker.close_position(real_price, ts)
                        elif real_price <= active_trade["sl"]:
                            tracker.close_position(real_price, ts)
                    elif tracker.position == -1:
                        if real_price <= active_trade["tp"]:
                            tracker.close_position(real_price, ts)
                        elif real_price >= active_trade["sl"]:
                            tracker.close_position(real_price, ts)
                    
                    # 2. Execução das Ordens Apregoadas (Limit Orders)
                    if tracker.position == 0:
                        buy_order = zigzag["pending_buy_limit"]
                        if buy_order is not None and real_price <= buy_order["entry"]:
                            tracker.enter_long(buy_order["entry"], ts) # Executa no preço do limit
                            active_trade["tp"] = buy_order["tp"]
                            active_trade["sl"] = buy_order["sl"]
                            zigzag["pending_buy_limit"] = None 
                            
                        sell_order = zigzag["pending_sell_limit"]
                        if sell_order is not None and real_price >= sell_order["entry"]:
                            tracker.enter_short(sell_order["entry"], ts)
                            active_trade["tp"] = sell_order["tp"]
                            active_trade["sl"] = sell_order["sl"]
                            zigzag["pending_sell_limit"] = None 
                            
                    # 3. Alimenta o motor Renko
                    vol = qty if t_type == 2 else (-qty if t_type == 3 else 0.0)
                    renko.process_trade(real_price, vol)
                    
    except Exception as e:
        log.error(f"Erro: {e}")
        return

    final_price = renko.boxes[-1].close_price if renko.boxes else 0
    tracker.close_position(final_price, None)
    
    log.info("\n" + "="*50)
    log.info("RESULTADOS DO BACKTEST - FIBONACCI 38.2% (10R)")
    log.info(f"Risco/Retorno Fixo: TP={TAKE_PROFIT_PTS} / SL={STOP_LOSS_PTS}")
    log.info("Filtro: Apenas Pernas >= 150 pontos (3 boxes)")
    log.info("="*50)
    
    s = tracker.get_stats()
    log.info(f"[{tracker.name}]")
    log.info(f"  Fibo's Ignoradas (Filtro Harmônico): {zigzag['ignored_by_filter']}")
    log.info(f"  Trades Feitos: {s['Total_Trades']}")
    log.info(f"  Lucro/Prejuízo Total: {s['Total_Pts']:.0f} Pontos")
    log.info(f"  Taxa de Acerto (Win Rate): {s['Win_Rate']:.1f}%")
    log.info(f"  Fator de Lucro (Profit Factor): {s['Profit_Factor']:.2f}")
    log.info(f"  Máximo Rebaixamento (Max Drawdown): {s['Max_DD']:.0f} Pontos")
    log.info("-" * 50)

if __name__ == "__main__":
    run_backtest(3000000)
