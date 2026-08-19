#!/usr/bin/env python3
"""
backtest_absorption_v2.py — Backtest Quantitativo de Scalping V2 (Filtro Institucional + Divergência WDO vs DOL).
Testa empiricamente nos 800 mil trades do banco a eficácia dos 3 filtros quantitativos:
1. Divergência do Dólar Cheio (DOLQ26 não confirmando a agressão do Mini).
2. Perfilagem de Corretoras (Agressores de Varejo/Stop vs Absorvedores Institucionais).
3. Saída Inteligente (Até 60s com alvo cirúrgico de +2,5 pts / -1,5 pt).
"""

import sys
import os
import psycopg2
from datetime import timedelta

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Adicionar pasta raiz ao path para importar corretoras se necessário
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')))
try:
    from corretoras import get_nome_corretora
except ImportError:
    def get_nome_corretora(agent_id): return str(agent_id)

RETAIL_AGENTS = {3, 23, 39, 1110, 1408, 1931, 4090, 6003, 740} # XP, Modal, Ágora, Inter, Clear, Rico, Nu, C6, Toro
INSTITUTIONAL_AGENTS = {8, 16, 40, 85, 92, 114, 115, 122, 238, 251, 1026, 1618} # UBS, JP, Morgan, BTG, Renascença, Citi, Itaú, BGC, Goldman, BNP, Ideal

def get_connection():
    return psycopg2.connect("host=localhost port=5432 dbname=fluxo_ordens user=postgres password=postgres")

def run_backtest_v2():
    conn = get_connection()
    cur = conn.cursor()
    dias = ['2026-07-14', '2026-07-15', '2026-07-16']
    
    print("==============================================================================================================")
    print(" 🛡️ BACKTEST QUANTITATIVO V2: ABSORÇÃO INSTITUCIONAL + DIVERGÊNCIA WDO vs DOL")
    print(" Filtro 1 (Divergência DOL) : Dólar Cheio não afunda na venda (CVD DOL >= -50) / não rasga na compra (<= +50)")
    print(" Filtro 2 (Agressores/Stops): Agressão majoritária de Varejo ou Giro/Stop vs Defesa de Institucional no book")
    print(" Alvo de Gain: +2,5 pts (+5 ticks) | Stop Loss: -1,5 pts (-3 ticks) | Janela de Saída: até 60 segundos")
    print("==============================================================================================================\n")

    total_sinais = 0
    gains = 0
    losses = 0
    timeouts = 0
    pts_totais = 0.0

    for dia in dias:
        # Puxar todos os trades de WDOQ26 e DOLQ26 do dia entre 09:00 e 18:00
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
        
        print(f" 📅 Analisando {dia} ({len(rows):,} negócios WDO + DOL processados em tempo real)...")
        
        # Manter inventário diário acumulado dos players no dia até o tick i
        agent_daily_net = {} # agent_id -> net_qty
        
        n = len(rows)
        i = 0
        while i < n:
            # Atualizar inventário até o tick atual se for WDO
            r_ts, r_ticker, r_price, r_qty, r_tt, r_buy, r_sell = rows[i]
            if r_ticker == 'WDOQ26':
                agent_daily_net[r_buy] = agent_daily_net.get(r_buy, 0) + r_qty
                agent_daily_net[r_sell] = agent_daily_net.get(r_sell, 0) - r_qty
                
            # Verificar se podemos iniciar uma janela de 30s de análise a cada 10s no WDO
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
            
            agressores_venda_retail_qty = 0
            agressores_venda_inst_qty = 0
            absorvedores_compra_inst_qty = 0
            
            agressores_compra_retail_qty = 0
            agressores_compra_inst_qty = 0
            absorvedores_venda_inst_qty = 0
            
            while j < n and rows[j][0] <= t_end_window:
                row_ts, row_tick, row_p, row_qty, row_tt, row_b, row_s = rows[j]
                
                if row_tick == 'DOLQ26':
                    if row_tt == 2: buy_aggr_dol += row_qty
                    elif row_tt == 3: sell_aggr_dol += row_qty
                elif row_tick == 'WDOQ26':
                    p = float(row_p) / 10.0
                    if p < min_p: min_p = p
                    if p > max_p: max_p = p
                    
                    if row_tt == 2: # Compra agressiva no WDO (bateu no Ask)
                        buy_aggr_wdo += row_qty
                        if row_b in RETAIL_AGENTS: agressores_compra_retail_qty += row_qty
                        elif row_b in INSTITUTIONAL_AGENTS: agressores_compra_inst_qty += row_qty
                        if row_s in INSTITUTIONAL_AGENTS: absorvedores_venda_inst_qty += row_qty
                    elif row_tt == 3: # Venda agressiva no WDO (bateu no Bid)
                        sell_aggr_wdo += row_qty
                        if row_s in RETAIL_AGENTS: agressores_venda_retail_qty += row_qty
                        elif row_s in INSTITUTIONAL_AGENTS: agressores_venda_inst_qty += row_qty
                        if row_b in INSTITUTIONAL_AGENTS: absorvedores_compra_inst_qty += row_qty
                j += 1
                
            if j >= n: break
            
            deslocamento = max_p - min_p
            p_close_window = float(rows[j-1][2]) / 10.0 if rows[j-1][1] == 'WDOQ26' else min_p
            
            cvd_dol = buy_aggr_dol - sell_aggr_dol
            
            # -----------------------------------------------------------------------------------------
            # FILTRO DE COMPRA V2 (Exaustão na Venda no Suporte + Divergência DOL + Institucional)
            # -----------------------------------------------------------------------------------------
            # 1. Agressão Vendedora >= 2.500 no WDO com Deslocamento <= 1.5 pt (Absorção)
            # 2. Divergência do Cheio: CVD do DOLQ26 >= -50 (Dólar cheio NÃO está afundando)
            # 3. Perfilagem: Varejo agredindo forte OU Institucionais absorvendo no suporte
            if sell_aggr_wdo >= 2500 and deslocamento <= 1.50 and cvd_dol >= -50:
                if (agressores_venda_retail_qty >= sell_aggr_wdo * 0.35) or (absorvedores_compra_inst_qty >= sell_aggr_wdo * 0.40):
                    # Disparou Sinal de COMPRA DE ALTA QUALIDADE!
                    t_trade_end = rows[j-1][0] + timedelta(seconds=60) # 60s de respiro para tracionar
                    p_entry = p_close_window
                    p_gain = p_entry + 2.50
                    p_stop = p_entry - 1.50
                    
                    k = j
                    hit_gain = False
                    hit_stop = False
                    p_last = p_entry
                    
                    while k < n and rows[k][0] <= t_trade_end:
                        if rows[k][1] == 'WDOQ26':
                            p_k = float(rows[k][2]) / 10.0
                            p_last = p_k
                            if p_k >= p_gain: hit_gain = True; break
                            if p_k <= p_stop: hit_stop = True; break
                        k += 1
                        
                    total_sinais += 1
                    if hit_gain:
                        gains += 1
                        pts_totais += 2.50
                    elif hit_stop:
                        losses += 1
                        pts_totais -= 1.50
                    else:
                        timeouts += 1
                        pts_totais += (p_last - p_entry)
                        
                    # Avançar para depois da janela de trade
                    while i < n and rows[i][0] <= t_trade_end:
                        if rows[i][1] == 'WDOQ26':
                            agent_daily_net[rows[i][5]] = agent_daily_net.get(rows[i][5], 0) + rows[i][3]
                            agent_daily_net[rows[i][6]] = agent_daily_net.get(rows[i][6], 0) - rows[i][3]
                        i += 1
                    continue

            # -----------------------------------------------------------------------------------------
            # FILTRO DE VENDA V2 (Exaustão na Compra na Resistência + Divergência DOL + Institucional)
            # -----------------------------------------------------------------------------------------
            if buy_aggr_wdo >= 2500 and deslocamento <= 1.50 and cvd_dol <= +50:
                if (agressores_compra_retail_qty >= buy_aggr_wdo * 0.35) or (absorvedores_venda_inst_qty >= buy_aggr_wdo * 0.40):
                    t_trade_end = rows[j-1][0] + timedelta(seconds=60)
                    p_entry = p_close_window
                    p_gain = p_entry - 2.50
                    p_stop = p_entry + 1.50
                    
                    k = j
                    hit_gain = False
                    hit_stop = False
                    p_last = p_entry
                    
                    while k < n and rows[k][0] <= t_trade_end:
                        if rows[k][1] == 'WDOQ26':
                            p_k = float(rows[k][2]) / 10.0
                            p_last = p_k
                            if p_k <= p_gain: hit_gain = True; break
                            if p_k >= p_stop: hit_stop = True; break
                        k += 1
                        
                    total_sinais += 1
                    if hit_gain:
                        gains += 1
                        pts_totais += 2.50
                    elif hit_stop:
                        losses += 1
                        pts_totais -= 1.50
                    else:
                        timeouts += 1
                        pts_totais += (p_entry - p_last)
                        
                    while i < n and rows[i][0] <= t_trade_end:
                        if rows[i][1] == 'WDOQ26':
                            agent_daily_net[rows[i][5]] = agent_daily_net.get(rows[i][5], 0) + rows[i][3]
                            agent_daily_net[rows[i][6]] = agent_daily_net.get(rows[i][6], 0) - rows[i][3]
                        i += 1
                    continue
            
            # Avançar ponteiro em 10 segundos
            t_next = t_start + timedelta(seconds=10)
            while i < n and rows[i][0] < t_next:
                if rows[i][1] == 'WDOQ26':
                    agent_daily_net[rows[i][5]] = agent_daily_net.get(rows[i][5], 0) + rows[i][3]
                    agent_daily_net[rows[i][6]] = agent_daily_net.get(rows[i][6], 0) - rows[i][3]
                i += 1

    print("\n==============================================================================================================")
    print(" 🎯 RESULTADOS DO BACKTEST V2 COM FILTROS INSTITUCIONAIS & DIVERGÊNCIA WDO vs DOL")
    print("==============================================================================================================")
    if total_sinais > 0:
        win_rate = (gains / total_sinais) * 100.0
        print(f"  • Sinais Filtrados de Alta Qualidade : {total_sinais} trades cirúrgicos")
        print(f"  • Gains Alvo (+2,5 pts)              : {gains} trades ({win_rate:.1f}%)")
        print(f"  • Losses Stop (-1,5 pts)             : {losses} trades ({(losses/total_sinais)*100:.1f}%)")
        print(f"  • Saída por Tempo (60s Reversão)     : {timeouts} trades ({(timeouts/total_sinais)*100:.1f}%)")
        print(f"  • Saldo Líquido em Pontos            : {pts_totais:+.2f} PONTOS no Mini Dólar!")
        print(f"  • Lucro por Contrato (1 lt)          : R$ {pts_totais * 10:+.2f}")
    else:
        print("  • Nenhum sinal atendeu rigorosamente aos 3 filtros simultâneos.")
    print("==============================================================================================================\n")
    conn.close()

if __name__ == "__main__":
    run_backtest_v2()
