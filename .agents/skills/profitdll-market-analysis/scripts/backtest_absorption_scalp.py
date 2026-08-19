#!/usr/bin/env python3
"""
backtest_absorption_scalp.py — Backtest Quantitativo de Scalping focado em Exaustão e Absorção Passiva.
Mede a taxa de acerto de trades de +2,5 pts (5 ticks) após agressões pesadas (>2.500 / >3.000 contratos) com deslocamento zero ou reduzido.
"""

import sys
import os
import psycopg2
from datetime import timedelta

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def get_connection():
    return psycopg2.connect("host=localhost port=5432 dbname=fluxo_ordens user=postgres password=postgres")

def run_backtest():
    conn = get_connection()
    cur = conn.cursor()
    
    # Vamos rodar dia a dia nos últimos 3 dias (14, 15 e 16 de Julho)
    dias = ['2026-07-14', '2026-07-15', '2026-07-16']
    
    print("==============================================================================================================")
    print(" ⚡ BACKTEST QUANTITATIVO DE SCALPING: ABSORÇÃO PASSIVA & EXAUSTÃO DE AGRESSÃO (WDOQ26)")
    print(" Parâmetros: Janela de Detecção de 30s | Agressão > 2.500 contratos | Deslocamento <= 1.5 pts (Absorção)")
    print(" Alvo de Gain: +2,5 pontos (+5 ticks) | Stop Loss: -1,5 pontos (-3 ticks) | Tempo Máx no Trade: 30 segundos")
    print("==============================================================================================================\n")

    total_trades_c = 0
    gains_c = 0
    losses_c = 0
    timeouts_c = 0
    pts_totais_c = 0.0

    total_trades_v = 0
    gains_v = 0
    losses_v = 0
    timeouts_v = 0
    pts_totais_v = 0.0

    for dia in dias:
        # Puxar todos os trades do WDOQ26 do dia ordenados por ts e id
        cur.execute("""
            SELECT ts, price, qty, trade_type, buy_agent, sell_agent
            FROM trades
            WHERE ticker = 'WDOQ26' AND ts >= %s::timestamp + INTERVAL '9 hours' 
              AND ts < %s::timestamp + INTERVAL '18 hours'
            ORDER BY ts ASC, id ASC
        """, (dia, dia))
        
        rows = cur.fetchall()
        if not rows:
            continue
            
        print(f" 📅 Analisando pregão {dia} ({len(rows):,} negócios processados tick a tick)...")
        
        # Estrutura para janela móvel em segundos
        # Para performance no Python, vamos agrupar em blocos/snapshots de tempo (ou iterar com ponteiro duplo de 30s)
        n = len(rows)
        i = 0
        while i < n:
            # Definir início da janela T0
            t_start = rows[i][0]
            t_end_window = t_start + timedelta(seconds=30)
            
            # Avançar j até t_end_window
            j = i
            buy_aggr = 0
            sell_aggr = 0
            min_p = float(rows[i][1]) / 10.0
            max_p = float(rows[i][1]) / 10.0
            
            while j < n and rows[j][0] <= t_end_window:
                p = float(rows[j][1]) / 10.0
                qty = rows[j][2]
                tt = rows[j][3]
                
                if p < min_p: min_p = p
                if p > max_p: max_p = p
                if tt == 2: buy_aggr += qty
                elif tt == 3: sell_aggr += qty
                j += 1
                
            if j >= n:
                break
                
            # Preço ao final da janela de 30s
            p_close_window = float(rows[j-1][1]) / 10.0
            deslocamento = max_p - min_p
            
            # -----------------------------------------------------------------------------------------
            # SINAL 1: ABSORÇÃO NA VENDA -> SCALPING DE COMPRA (+2,5 pts)
            # Agressão vendedora brutal (>= 2.500 ctrs no 30s) mas preço caiu <= 1,5 pts do topo ao fundo da janela
            # e o delta foi fortemente negativo (sell_aggr - buy_aggr >= 1.500)
            # -----------------------------------------------------------------------------------------
            if sell_aggr >= 2500 and (sell_aggr - buy_aggr) >= 1500 and (max_p - min_p) <= 1.50:
                # Disparou sinal de COMPRA! Vamos checar os próximos 30 segundos após j
                t_trade_end = rows[j-1][0] + timedelta(seconds=30)
                p_entry = p_close_window
                p_gain = p_entry + 2.50
                p_stop = p_entry - 1.50
                
                k = j
                hit_gain = False
                hit_stop = False
                p_last = p_entry
                
                while k < n and rows[k][0] <= t_trade_end:
                    p_k = float(rows[k][1]) / 10.0
                    p_last = p_k
                    if p_k >= p_gain:
                        hit_gain = True
                        break
                    if p_k <= p_stop:
                        hit_stop = True
                        break
                    k += 1
                    
                total_trades_c += 1
                if hit_gain:
                    gains_c += 1
                    pts_totais_c += 2.50
                elif hit_stop:
                    losses_c += 1
                    pts_totais_c -= 1.50
                else:
                    timeouts_c += 1
                    pts_totais_c += (p_last - p_entry)
                
                # Avançar o ponteiro i para frente do trade para não contar sinais sobrepostos logo em seguida
                i = max(j, k)
                continue

            # -----------------------------------------------------------------------------------------
            # SINAL 2: ABSORÇÃO NA COMPRA -> SCALPING DE VENDA (-2,5 pts)
            # Agressão compradora brutal (>= 2.500 ctrs no 30s) mas preço subiu <= 1,5 pts na janela
            # e o delta foi fortemente positivo (buy_aggr - sell_aggr >= 1.500)
            # -----------------------------------------------------------------------------------------
            if buy_aggr >= 2500 and (buy_aggr - sell_aggr) >= 1500 and (max_p - min_p) <= 1.50:
                t_trade_end = rows[j-1][0] + timedelta(seconds=30)
                p_entry = p_close_window
                p_gain = p_entry - 2.50
                p_stop = p_entry + 1.50
                
                k = j
                hit_gain = False
                hit_stop = False
                p_last = p_entry
                
                while k < n and rows[k][0] <= t_trade_end:
                    p_k = float(rows[k][1]) / 10.0
                    p_last = p_k
                    if p_k <= p_gain:
                        hit_gain = True
                        break
                    if p_k >= p_stop:
                        hit_stop = True
                        break
                    k += 1
                    
                total_trades_v += 1
                if hit_gain:
                    gains_v += 1
                    pts_totais_v += 2.50
                elif hit_stop:
                    losses_v += 1
                    pts_totais_v -= 1.50
                else:
                    timeouts_v += 1
                    pts_totais_v += (p_entry - p_last)
                
                i = max(j, k)
                continue
                
            # Avançar ponteiro i de 10 em 10 segundos
            t_next = t_start + timedelta(seconds=10)
            while i < n and rows[i][0] < t_next:
                i += 1

    print("\n==============================================================================================================")
    print(" 📊 RESULTADOS DO BACKTEST DE SCALPING (3 DIAS ACUMULADOS — WDOQ26)")
    print("==============================================================================================================")
    
    print("\n 🟢 SCALPING NA COMPRA (Após Exaustão/Absorção na Venda no Suporte):")
    if total_trades_c > 0:
        win_rate_c = (gains_c / total_trades_c) * 100.0
        print(f"  • Sinais Disparados : {total_trades_c} oportunidades nos 3 dias")
        print(f"  • Gains (+2,5 pts)  : {gains_c} trades ({win_rate_c:.1f}%)")
        print(f"  • Losses (-1,5 pts) : {losses_c} trades ({(losses_c/total_trades_c)*100:.1f}%)")
        print(f"  • Saídas por Tempo  : {timeouts_c} trades ({(timeouts_c/total_trades_c)*100:.1f}%)")
        print(f"  • Resultado Pontos  : {pts_totais_c:+.2f} pontos líquidos no Mini Dólar!")
        print(f"  • Financeiro (1 lt) : R$ {pts_totais_c * 10:+.2f} por contrato de WDO")
    else:
        print("  • Nenhum sinal disparado com os parâmetros atuais de agressão >= 2500 e desloc <= 1.5 pt.")

    print("\n 🔴 SCALPING NA VENDA (Após Exaustão/Absorção na Compra na Resistência):")
    if total_trades_v > 0:
        win_rate_v = (gains_v / total_trades_v) * 100.0
        print(f"  • Sinais Disparados : {total_trades_v} oportunidades nos 3 dias")
        print(f"  • Gains (-2,5 pts)  : {gains_v} trades ({win_rate_v:.1f}%)")
        print(f"  • Losses (+1,5 pts) : {losses_v} trades ({(losses_v/total_trades_v)*100:.1f}%)")
        print(f"  • Saídas por Tempo  : {timeouts_v} trades ({(timeouts_v/total_trades_v)*100:.1f}%)")
        print(f"  • Resultado Pontos  : {pts_totais_v:+.2f} pontos líquidos no Mini Dólar!")
        print(f"  • Financeiro (1 lt) : R$ {pts_totais_v * 10:+.2f} por contrato de WDO")
    else:
        print("  • Nenhum sinal disparado com esses parâmetros.")

    tot_sinais = total_trades_c + total_trades_v
    tot_pts = pts_totais_c + pts_totais_v
    print("\n " + "-"*108)
    print(f" 🏆 RESUMO GERAL DO MODELO DE ABSORÇÃO: {tot_sinais} TRADES | SALDO TOTAL: {tot_pts:+.2f} PONTOS (R$ {tot_pts*10:+.2f} / lt)")
    print("==============================================================================================================\n")

    conn.close()

if __name__ == "__main__":
    run_backtest()
