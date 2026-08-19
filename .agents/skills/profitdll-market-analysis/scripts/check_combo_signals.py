#!/usr/bin/env python3
"""
check_combo_signals.py — Backtest do Combo de Ouro do Day Trade (Absorção -> Impulso de Tração).
Verifica a taxa de acerto de +2,5 pts (+5 ticks) e +3,5 pts (+7 ticks) quando esperamos
a ABSORÇÃO PASSIVA ser confirmada por uma AGRESSÃO DE IMPULSO na direção contrária dentro de até 120s.
Simétrico para Compra (Absorção Compradora -> Impulso Comprador) e Venda (Absorção Vendedora -> Impulso Vendedor).
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

def run_combo_test():
    conn = get_connection()
    cur = conn.cursor()
    dias = ['2026-07-14', '2026-07-15', '2026-07-16']
    
    print("==============================================================================================================")
    print(" ⚡🛡️ BACKTEST DO COMBO DE OURO: ABSORÇÃO PASSIVA + CONFIRMAÇÃO POR IMPULSO DE TRAÇÃO")
    print(" 1º Sinal: Absorção (Deslocamento <= 1.5 pt sob agressão contrária >= 2.000 ctrs)")
    print(" 2º Sinal (Até 120s depois): Impulso de Tração (Agressão forte na direção do trade >= 1.200 ctrs em 15s)")
    print(" Alvos de Scalping: +2,5 pts (+5 ticks) e +3,5 pts (+7 ticks) | Stop Loss: -1,5 pt | Tempo trade: 60s")
    print(" Simétrico 100% para Compra e Venda")
    print("==============================================================================================================\n")

    total_combo_compra = 0
    gains_c_25 = 0; gains_c_35 = 0; losses_c = 0; time_c = 0
    pts_c = 0.0

    total_combo_venda = 0
    gains_v_25 = 0; gains_v_35 = 0; losses_v = 0; time_v = 0
    pts_v = 0.0

    for dia in dias:
        cur.execute("""
            SELECT ts, price, qty, trade_type, buy_agent, sell_agent
            FROM trades
            WHERE ticker = 'WDOQ26' AND ts >= %s::timestamp + INTERVAL '9 hours' 
              AND ts < %s::timestamp + INTERVAL '18 hours'
            ORDER BY ts ASC, id ASC
        """, (dia, dia))
        rows = cur.fetchall()
        if not rows: continue
        
        n = len(rows)
        i = 0
        while i < n:
            t_start = rows[i][0]
            t_end_abs = t_start + timedelta(seconds=30)
            
            j = i
            buy_aggr = 0; sell_aggr = 0
            min_p = float(rows[i][1]) / 10.0; max_p = min_p
            
            while j < n and rows[j][0] <= t_end_abs:
                p = float(rows[j][1]) / 10.0
                qty = rows[j][2]; tt = rows[j][3]
                if p < min_p: min_p = p
                if p > max_p: max_p = p
                if tt == 2: buy_aggr += qty
                elif tt == 3: sell_aggr += qty
                j += 1
                
            if j >= n: break
            desloc = max_p - min_p
            p_abs_close = float(rows[j-1][1]) / 10.0
            
            # -----------------------------------------------------------------------------------------
            # COMBO DE COMPRA: 1º Absorção de Venda -> 2º Esperar Impulso Comprador
            # -----------------------------------------------------------------------------------------
            if sell_aggr >= 2000 and desloc <= 1.50:
                # Procurar nos próximos 120 segundos pelo SINAL DE IMPULSO COMPRADOR (>= 1.200 lotes em 15s)
                t_search_end = rows[j-1][0] + timedelta(seconds=120)
                m = j
                while m < n and rows[m][0] <= t_search_end:
                    # Checar janela de 15s a partir do tick m
                    t_impulse_end = rows[m][0] + timedelta(seconds=15)
                    q = m
                    impulse_buy_qty = 0
                    while q < n and rows[q][0] <= t_impulse_end:
                        if rows[q][3] == 2: impulse_buy_qty += rows[q][2]
                        q += 1
                        
                    if impulse_buy_qty >= 1200:
                        # ENCONTRAMOS O IMPULSO COMPRADOR! ENTRADA NA COMPRA AGORA!
                        t_entry = rows[q-1][0]
                        p_entry = float(rows[q-1][1]) / 10.0
                        
                        # Testar o trade nos 60s seguintes
                        k = q
                        hit_gain25 = False; hit_gain35 = False; hit_stop = False
                        p_last = p_entry
                        
                        while k < n and rows[k][0] <= t_entry + timedelta(seconds=60):
                            p_k = float(rows[k][1]) / 10.0
                            p_last = p_k
                            if p_k >= p_entry + 3.50: hit_gain35 = True; hit_gain25 = True; break
                            if p_k >= p_entry + 2.50: hit_gain25 = True
                            if p_k <= p_entry - 1.50: hit_stop = True; break
                            k += 1
                            
                        total_combo_compra += 1
                        if hit_gain35 or hit_gain25:
                            gains_c_25 += 1
                            if hit_gain35: gains_c_35 += 1; pts_c += 3.50
                            else: pts_c += 2.50
                        elif hit_stop:
                            losses_c += 1; pts_c -= 1.50
                        else:
                            time_c += 1; pts_c += (p_last - p_entry)
                            
                        i = k
                        break
                    m += 1

            # -----------------------------------------------------------------------------------------
            # COMBO DE VENDA: 1º Absorção de Compra -> 2º Esperar Impulso Vendedor
            # -----------------------------------------------------------------------------------------
            if buy_aggr >= 2000 and desloc <= 1.50:
                t_search_end = rows[j-1][0] + timedelta(seconds=120)
                m = j
                while m < n and rows[m][0] <= t_search_end:
                    t_impulse_end = rows[m][0] + timedelta(seconds=15)
                    q = m
                    impulse_sell_qty = 0
                    while q < n and rows[q][0] <= t_impulse_end:
                        if rows[q][3] == 3: impulse_sell_qty += rows[q][2]
                        q += 1
                        
                    if impulse_sell_qty >= 1200:
                        t_entry = rows[q-1][0]
                        p_entry = float(rows[q-1][1]) / 10.0
                        
                        k = q
                        hit_gain25 = False; hit_gain35 = False; hit_stop = False
                        p_last = p_entry
                        
                        while k < n and rows[k][0] <= t_entry + timedelta(seconds=60):
                            p_k = float(rows[k][1]) / 10.0
                            p_last = p_k
                            if p_k <= p_entry - 3.50: hit_gain35 = True; hit_gain25 = True; break
                            if p_k <= p_entry - 2.50: hit_gain25 = True
                            if p_k >= p_entry + 1.50: hit_stop = True; break
                            k += 1
                            
                        total_combo_venda += 1
                        if hit_gain35 or hit_gain25:
                            gains_v_25 += 1
                            if hit_gain35: gains_v_35 += 1; pts_v += 3.50
                            else: pts_v += 2.50
                        elif hit_stop:
                            losses_v += 1; pts_v -= 1.50
                        else:
                            time_v += 1; pts_v += (p_entry - p_last)
                            
                        i = k
                        break
                    m += 1
                    
            i += 1

    print("\n==============================================================================================================")
    print(" 🏆 RESULTADO FINAL DO COMBO (ABSORÇÃO PASSIVA + IMPULSO DE TRAÇÃO NOS 3 DIAS)")
    print("==============================================================================================================")
    if total_combo_compra > 0:
        print(f" 🟢 COMBO DE COMPRA : {total_combo_compra} trades confirmados pelo Impulso")
        print(f"    • Gains (+2.5 a +3.5 pts): {gains_c_25} trades ({(gains_c_25/total_combo_compra)*100:.1f}%)")
        print(f"    • Stops (-1.5 pt)        : {losses_c} trades ({(losses_c/total_combo_compra)*100:.1f}%)")
        print(f"    • Saldo Líquido Compra   : {pts_c:+.2f} pontos no Mini Dólar!")
        
    if total_combo_venda > 0:
        print(f"\n 🔴 COMBO DE VENDA  : {total_combo_venda} trades confirmados pelo Impulso")
        print(f"    • Gains (+2.5 a +3.5 pts): {gains_v_25} trades ({(gains_v_25/total_combo_venda)*100:.1f}%)")
        print(f"    • Stops (-1.5 pt)        : {losses_v} trades ({(losses_v/total_combo_venda)*100:.1f}%)")
        print(f"    • Saldo Líquido Venda    : {pts_v:+.2f} pontos no Mini Dólar!")
        
    tot = total_combo_compra + total_combo_venda
    tot_pts = pts_c + pts_v
    print("\n " + "-"*108)
    print(f" 🎯 TOTAL GERAL DO COMBO : {tot} TRADES CONFIRMADOSS | SALDO LÍQUIDO: {tot_pts:+.2f} PONTOS (R$ {tot_pts*10:+.2f} / lt)")
    print("==============================================================================================================\n")
    conn.close()

if __name__ == "__main__":
    run_combo_test()
