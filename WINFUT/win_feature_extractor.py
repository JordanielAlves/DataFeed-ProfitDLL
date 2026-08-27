"""
win_feature_extractor.py
Extrai as características (features) da microestrutura do WINFUT no exato momento
em que um box do Renko é fechado. Focado em identificar varreduras (sweeps) de HFT.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from collections import deque
from WINFUT.renko_engine import RenkoBox

class WinFeatureExtractor:
    def __init__(self):
        # Armazena os últimos trades para analisar a microestrutura (ex: últimos 1000 trades)
        self.recent_trades = deque(maxlen=2000)
        self.features_list = []
        
    def add_trade(self, ts: datetime, price: float, qty: int, trade_type: int):
        """
        Adiciona um trade ao buffer recente.
        trade_type: 1=cross, 2=buy_aggress, 3=sell_aggress
        """
        self.recent_trades.append({
            'ts': ts,
            'price': price,
            'qty': qty,
            'trade_type': trade_type
        })
        
    def extract_on_box_close(self, box: RenkoBox, current_ts: datetime):
        """
        Calcula as features baseadas no buffer de trades quando o box fecha.
        Retorna um dict com as features e salva no log interno.
        """
        if not self.recent_trades:
            return None
            
        time_threshold = current_ts.timestamp() - 5.0
        
        trades_5s = []
        # Percorre de trás pra frente (mais recentes primeiro)
        for t in reversed(self.recent_trades):
            if t['ts'].timestamp() >= time_threshold:
                trades_5s.append(t)
            else:
                break
                
        if not trades_5s:
            # Fallback para os 10 últimos se não houver na janela
            trades_5s = list(self.recent_trades)[-10:]
            
        duration = current_ts.timestamp() - trades_5s[-1]['ts'].timestamp() if trades_5s else 0.001
        duration = max(duration, 0.001)
        trades_per_sec = len(trades_5s) / duration
        
        buy_vol = sum(t['qty'] for t in trades_5s if t['trade_type'] == 2)
        sell_vol = sum(t['qty'] for t in trades_5s if t['trade_type'] == 3)
        total_aggress = buy_vol + sell_vol
        buy_imbalance = (buy_vol / total_aggress) if total_aggress > 0 else 0.5
        
        avg_trade_size = sum(t['qty'] for t in trades_5s) / len(trades_5s) if trades_5s else 0.0
        large_trades_count = sum(1 for t in trades_5s if t['qty'] >= 100)
        
        # 5. Features Macro (Do próprio Renko)
        state_color = box.state_color
        is_locked = 1 if box.aggression_locked else 0
        dist_to_sma = (box.close_price - box.sma) if box.sma else 0.0
        
        features = {
            'box_index': box.index,
            'ts': current_ts,
            'state_color': state_color,
            'is_locked': is_locked,
            'dist_to_sma': dist_to_sma,
            'trades_per_sec': trades_per_sec,
            'buy_imbalance': buy_imbalance,
            'avg_trade_size': avg_trade_size,
            'large_trades_count': large_trades_count,
            'box_close_price': box.close_price
        }
        
        self.features_list.append(features)
        return features

    def get_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self.features_list)
