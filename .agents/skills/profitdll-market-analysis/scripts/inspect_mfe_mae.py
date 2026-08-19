#!/usr/bin/env python3
"""
inspect_mfe_mae.py — Análise Forense de Excursão Máxima (MFE vs MAE) dos 25 Sinais de Absorção.
Mede exatamente quantos pontos o mercado andou a favor e contra nos 10s, 20s, 30s, 60s e 120s seguintes
após a absorção institucional ser detectada.
"""

import sys
import os
import psycopg2
from datetime import timedelta

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

RETAIL_AGENTS = {3, 23, 39, 1110, 1408, 1931, 4090, 6003, 740}
INSTITUTIONAL_AGENTS = {8, 16, 40, 85, 92, 114, 115, 122, 238, 251, 1026, 1618}

def get_connection():
    return psycopg2.connect("host=localhost port=5432 dbname=fluxo_ordens user=postgres password=postgres")

def run_mfe_mae():
    conn = get_connection()
    cur = conn.cursor()
    dias = ['2026-07-14', '2026-07-15', '2026-07-16']
    
    print("==============================================================================================================")
    print(" 🔍 RAIO-X FORENSE DOS SINAIS DE ABSORÇÃO INSTITUCIONAL: EXCURSÃO MÁXIMA A FAVOR (MFE) E CONTRA (MAE)")
    print(" Descobrindo o Alvo Perfeito de Scalping (+1.0, +1.5, +2.0 ou +2.5 pts) nos primeiros segundos após o sinal")
    print("==============================================================================================================\n")

    sinais = []

    for dia in dias:
        cur.execute("""
            SELECT ts, ticker, price, qty, trade_type, buy_agent, sell_agent
            FROM trades
            WHERE ticker IN ('WDOQ26', 'DOLQ26') 
              AND ts >= %s::timestamp + INTERVAL '9 hours' 
              AND ts < %s::timestamp + INTERVAL '18 hours'
            ORDER BY ts ASC, id ASC
        """, (dia, dia))
        
        rows = cur.fetchall()
        if not rows: continue
        
        n = len(rows)
        i = 0
        while i < n:
            r_ts, r_ticker, r_price, r_qty, r_tt, r_buy, r_sell = rows[i]
            if r_ticker != 'WDOQ26':
                i += 1
                continue
                
            t_start = r_ts
            t_end_window = t_start + timedelta(seconds=30)
            j = i
            buy_aggr_wdo = 0
            sell_aggr_wdo = 0
            buy_aggr_dol = 0
            sell_aggr_dol = 0
            min_p = float(r_price) / 10.0
            max_p = float(r_price) / 10.0
            
            agressores_venda_retail = 0
            absorvedores_compra_inst = 0
            agressores_compra_retail = 0
            absorvedores_venda_inst = 0
            
            while j < n and rows[j][0] <= t_end_window:
                row_ts, row_tick, row_p, row_qty, row_tt, row_b, row_s = rows[j]
                if row_tick == 'DOLQ26':
                    if row_tt == 2: buy_aggr_dol += row_qty
                    elif row_tt == 3: sell_aggr_dol += row_qty
                elif row_tick == 'WDOQ26':
                    p = float(row_p) / 10.0
                    if p < min_p: min_p = p
                    if p > max_p: max_p = p
                    if row_tt == 2:
                        buy_aggr_wdo += row_qty
                        if row_b in RETAIL_AGENTS: agressores_compra_retail += row_qty
                        if row_s in INSTITUTIONAL_AGENTS: absorvedores_venda_inst += row_qty
                    elif row_tt == 3:
                        sell_aggr_wdo += row_qty
                        if row_s in RETAIL_AGENTS: agressores_venda_retail += row_qty
                        if row_b in INSTITUTIONAL_AGENTS: absorvedores_compra_inst += row_qty
                j += 1
                
            if j >= n: break
            deslocamento = max_p - min_p
            p_close = float(rows[j-1][2]) / 10.0 if rows[j-1][1] == 'WDOQ26' else min_p
            cvd_dol = buy_aggr_dol - sell_aggr_dol
            
            # Checar Sinal de COMPRA
            if sell_aggr_wdo >= 2500 and deslocamento <= 1.50 and cvd_dol >= -50:
                if (agressores_venda_retail >= sell_aggr_wdo * 0.35) or (absorvedores_compra_inst >= sell_aggr_wdo * 0.40):
                    # Medir MFE e MAE nas janelas de 10s, 20s, 30s, 60s, 120s
                    t_0 = rows[j-1][0]
                    k = j
                    max_fav_10s = 0.0; max_adv_10s = 0.0
                    max_fav_30s = 0.0; max_adv_30s = 0.0
                    max_fav_60s = 0.0; max_adv_60s = 0.0
                    max_fav_120s = 0.0; max_adv_120s = 0.0
                    
                    while k < n and rows[k][0] <= t_0 + timedelta(seconds=120):
                        if rows[k][1] == 'WDOQ26':
                            p_k = float(rows[k][2]) / 10.0
                            diff = p_k - p_close # para compra, diff positiva é a favor
                            dt = (rows[k][0] - t_0).total_seconds()
                            
                            if dt <= 10:
                                if diff > max_fav_10s: max_fav_10s = diff
                                if diff < max_adv_10s: max_adv_10s = diff
                            if dt <= 30:
                                if diff > max_fav_30s: max_fav_30s = diff
                                if diff < max_adv_30s: max_adv_30s = diff
                            if dt <= 60:
                                if diff > max_fav_60s: max_fav_60s = diff
                                if diff < max_adv_60s: max_adv_60s = diff
                            if diff > max_fav_120s: max_fav_120s = diff
                            if diff < max_adv_120s: max_adv_120s = diff
                        k += 1
                        
                    sinais.append(('COMPRA', str(t_0)[:19], p_close, sell_aggr_wdo, max_fav_10s, max_adv_10s, max_fav_30s, max_adv_30s, max_fav_60s, max_adv_60s, max_fav_120s, max_adv_120s))
                    
                    while i < n and rows[i][0] <= t_0 + timedelta(seconds=60): i += 1
                    continue

            # Checar Sinal de VENDA
            if buy_aggr_wdo >= 2500 and deslocamento <= 1.50 and cvd_dol <= +50:
                if (agressores_compra_retail >= buy_aggr_wdo * 0.35) or (absorvedores_venda_inst >= buy_aggr_wdo * 0.40):
                    t_0 = rows[j-1][0]
                    k = j
                    max_fav_10s = 0.0; max_adv_10s = 0.0
                    max_fav_30s = 0.0; max_adv_30s = 0.0
                    max_fav_60s = 0.0; max_adv_60s = 0.0
                    max_fav_120s = 0.0; max_adv_120s = 0.0
                    
                    while k < n and rows[k][0] <= t_0 + timedelta(seconds=120):
                        if rows[k][1] == 'WDOQ26':
                            p_k = float(rows[k][2]) / 10.0
                            diff = p_close - p_k # para venda, diff positiva quando cai
                            dt = (rows[k][0] - t_0).total_seconds()
                            
                            if dt <= 10:
                                if diff > max_fav_10s: max_fav_10s = diff
                                if diff < max_adv_10s: max_adv_10s = diff
                            if dt <= 30:
                                if diff > max_fav_30s: max_fav_30s = diff
                                if diff < max_adv_30s: max_adv_30s = diff
                            if dt <= 60:
                                if diff > max_fav_60s: max_fav_60s = diff
                                if diff < max_adv_60s: max_adv_60s = diff
                            if diff > max_fav_120s: max_fav_120s = diff
                            if diff < max_adv_120s: max_adv_120s = diff
                        k += 1
                        
                    sinais.append(('VENDA', str(t_0)[:19], p_close, buy_aggr_wdo, max_fav_10s, max_adv_10s, max_fav_30s, max_adv_30s, max_fav_60s, max_adv_60s, max_fav_120s, max_adv_120s))
                    while i < n and rows[i][0] <= t_0 + timedelta(seconds=60): i += 1
                    continue
            
            t_next = t_start + timedelta(seconds=10)
            while i < n and rows[i][0] < t_next: i += 1

    print(f" 📊 TABELA DETALHADA DOS {len(sinais)} TRADES CIRÚRGICOS (MFE = Excursão Máxima a Favor | MAE = Contra):")
    print(" ------------------------------------------------------------------------------------------------------------")
    print(f" {'LADO':<6} | {'HORÁRIO':<19} | {'ENTRADA':<7} | {'MFE 10s':<7} | {'MFE 30s':<7} | {'MFE 60s':<7} | {'MFE 120s':<8} | {'MAE 60s':<7}")
    print(" ------------------------------------------------------------------------------------------------------------")
    
    hits_1_0 = 0; hits_1_5 = 0; hits_2_0 = 0; hits_2_5 = 0
    
    for s in sinais:
        lado, ts_str, p_ent, aggr, mf10, ma10, mf30, ma30, mf60, ma60, mf120, ma120 = s
        print(f" {lado:<6} | {ts_str:<19} | {p_ent:<7.1f} | {mf10:>+6.1f}p | {mf30:>+6.1f}p | {mf60:>+6.1f}p | {mf120:>+7.1f}p | {ma60:>+6.1f}p")
        if mf60 >= 1.0: hits_1_0 += 1
        if mf60 >= 1.5: hits_1_5 += 1
        if mf60 >= 2.0: hits_2_0 += 1
        if mf60 >= 2.5: hits_2_5 += 1

    tot = len(sinais)
    print(" ------------------------------------------------------------------------------------------------------------")
    if tot > 0:
        print("\n 🏆 MATRIZ DE SIMULAÇÃO DE ALVOS (NOS PRIMEIROS 60 SEGUNDOS APÓS O ALERTA):")
        print(f"  • Se o alvo for +1,0 ponto (2 ticks): {hits_1_0}/{tot} trades atingiram o alvo -> {(hits_1_0/tot)*100:.1f}% de Taxa de Acerto!")
        print(f"  • Se o alvo for +1,5 ponto (3 ticks): {hits_1_5}/{tot} trades atingiram o alvo -> {(hits_1_5/tot)*100:.1f}% de Taxa de Acerto!")
        print(f"  • Se o alvo for +2,0 pontos (4 ticks): {hits_2_0}/{tot} trades atingiram o alvo -> {(hits_2_0/tot)*100:.1f}% de Taxa de Acerto!")
        print(f"  • Se o alvo for +2,5 pontos (5 ticks): {hits_2_5}/{tot} trades atingiram o alvo -> {(hits_2_5/tot)*100:.1f}% de Taxa de Acerto!")
    print("==============================================================================================================\n")
    conn.close()

if __name__ == "__main__":
    run_mfe_mae()
