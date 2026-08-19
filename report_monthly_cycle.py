#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Raio-X do Ciclo Mensal do Dólar Futuro na B3 (15/06/2026 a 17/07/2026).
Agrega 105 milhões de ticks em análises diárias e semanais (4 Fases do Mês)
para tirar a prova das amplitudes de caixote vs rolagem e direcionalidade.
"""

import sys
import os
import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime
from market_calendar import get_market_calendar_features

# Blindagem de Encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_DSN = os.getenv("PROFIT_DB_DSN", "dbname=fluxo_ordens user=postgres password=postgres host=localhost")

def run_monthly_xray():
    print("\n" + "="*88)
    print(" 🌟 RAIO-X MACROESTRUTURAL: 105 MILHÕES DE TICKS DO DÓLAR FUTURO POR FASES DO MÊS")
    print("="*88)
    print(" ⏱️  Consultando agregação diária no PostgreSQL (isso leva alguns segundos)...")

    query = """
        SELECT 
            DATE(ts) as pregao_date,
            ticker,
            MIN(price) as min_raw,
            MAX(price) as max_raw,
            COUNT(*) as n_trades,
            SUM(qty) as total_qty,
            AVG(qty) as avg_lote
        FROM trades
        WHERE ticker LIKE 'WDO%' OR ticker LIKE 'DOL%'
        GROUP BY DATE(ts), ticker
        ORDER BY pregao_date ASC
    """

    try:
        with psycopg2.connect(DB_DSN) as conn:
            df = pd.read_sql_query(query, conn)
    except Exception as e:
        print(f"❌ Erro na consulta ao banco: {e}")
        return

    if df.empty:
        print("⚠️ Nenhum registro encontrado para WDO/DOL no período.")
        return

    # Ajustar escala de preço WDO/DOL (dividir por 10 conforme Regra 1 AGENTS.md)
    df["min_p"] = df["min_raw"] / 10.0
    df["max_p"] = df["max_raw"] / 10.0
    df["amplitude_pts"] = df["max_p"] - df["min_p"]

    # Injetar Fases do Mês
    feats_list = []
    for d in df["pregao_date"]:
        dt_obj = datetime.strptime(str(d), "%Y-%m-%d") if isinstance(d, (str, datetime)) else datetime.combine(d, datetime.min.time())
        feats_list.append(get_market_calendar_features(dt_obj))

    feats_df = pd.DataFrame(feats_list)
    df["phase"] = feats_df["month_week_phase"].astype(int)
    df["days_to_rollover"] = feats_df["days_to_rollover"].astype(int)
    df["is_payroll"] = feats_df["is_payroll_week"].astype(int)

    # Exibir Tabela Diária Detalhada
    print("\n" + "-"*88)
    print(f" {'DATA':<12} | {'TICKER':<6} | {'FASE':<6} | {'MÍNIMA':<9} | {'MÁXIMA':<9} | {'AMPLITUDE':<10} | {'VOLUME (LTS)':<13} | {'LOTE MÉD'}")
    print("-"*88)

    for _, r in df.iterrows():
        p_str = f"Fase {r['phase']}"
        if r['is_payroll'] == 1:
            p_str += " (PR)"
        if r['days_to_rollover'] <= 3:
            p_str += " (ROL)"

        amp_color = "\033[1;32m" if r['amplitude_pts'] >= 50.0 else ("\033[1;33m" if r['amplitude_pts'] >= 35.0 else "\033[1;36m")
        print(f" {str(r['pregao_date']):<12} | {r['ticker']:<6} | {p_str:<11} | {r['min_p']:<9.2f} | {r['max_p']:<9.2f} | {amp_color}{r['amplitude_pts']:<8.2f} pt\033[0m | {int(r['total_qty']):<13,d} | {r['avg_lote']:.2f}")

    # Síntese Comparativa por Fase do Mês
    print("\n" + "="*88)
    print(" 🏆 PROVA REAL: COMPARATIVO MÉDIO POR FASE DO MÊS (SAZONALIDADE AUDITADA)")
    print("="*88)
    print(f" {'FASE DO MÊS / PERÍODO':<32} | {'DIAS':<5} | {'AMPLITUDE MÉDIA':<17} | {'VOLUME DIÁRIO MÉDIO':<20} | {'LOTE MÉDIO'}")
    print("-"*88)

    phase_labels = {
        1: "Fase 1: Pós-Rolagem / Pré-Payroll",
        2: "Fase 2: Caixote / Estabilidade",
        3: "Fase 3: Caixote / Estabilidade",
        4: "Fase 4: Pré-Rolagem / Disputa PTAX"
    }

    for p in range(1, 5):
        df_p = df[df["phase"] == p]
        if df_p.empty:
            continue
        avg_amp = df_p["amplitude_pts"].mean()
        avg_vol = df_p["total_qty"].mean()
        avg_lote = df_p["avg_lote"].mean()

        amp_color = "\033[1;32m" if avg_amp >= 45.0 else ("\033[1;33m" if avg_amp >= 35.0 else "\033[1;36m")
        print(f" {phase_labels.get(p, f'Fase {p}'):<32} | {len(df_p):<5} | {amp_color}{avg_amp:<6.2f} pontos\033[0m      | {int(avg_vol):<13,d} lotes  | {avg_lote:.2f}")

    print("="*88 + "\n")

if __name__ == "__main__":
    run_monthly_xray()
