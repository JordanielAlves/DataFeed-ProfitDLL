#!/usr/bin/env python3
"""
market_inspector.py — Ferramenta automatizada de análise de fluxo e microestrutura para ProfitDLL / PostgreSQL.
Uso pela skill `profitdll-market-analysis` ou diretamente via CLI.
"""

import sys
import os
import argparse
import psycopg2

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Adicionar o diretório raiz do projeto para importar módulos como corretoras e config
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))
try:
    import corretoras
except ImportError:
    # Fallback se executado de outro caminho
    class corretoras:
        @staticmethod
        def get_nome_corretora(agent_id):
            return f"Agent {agent_id}"

def get_connection(db_dsN=None):
    if not db_dsN:
        db_dsN = os.getenv("DB_DSN", "host=localhost port=5432 dbname=fluxo_ordens user=postgres password=postgres")
    return psycopg2.connect(db_dsN)

def analyze_daily_summary(cur, ticker, date_str):
    cur.execute("""
        SELECT MIN(price), MAX(price),
               (SELECT price FROM trades WHERE ticker=%s AND ts >= %s::timestamp AND ts < %s::timestamp + INTERVAL '1 day' ORDER BY ts ASC LIMIT 1),
               (SELECT price FROM trades WHERE ticker=%s AND ts >= %s::timestamp AND ts < %s::timestamp + INTERVAL '1 day' ORDER BY ts DESC LIMIT 1),
               COUNT(*), SUM(qty),
               SUM(CASE WHEN trade_type=2 THEN qty WHEN trade_type=3 THEN -qty ELSE 0 END)
        FROM trades
        WHERE ticker=%s AND ts >= %s::timestamp AND ts < %s::timestamp + INTERVAL '1 day'
    """, (ticker, date_str, date_str, ticker, date_str, date_str, ticker, date_str, date_str))
    row = cur.fetchone()
    if not row or row[4] == 0:
        print(f"=== [SEM TRADES] Ticker: {ticker} no dia {date_str} ===")
        return

    is_usd = ticker.startswith("WDO") or ticker.startswith("DOL")
    scale = 10.0 if is_usd else 1.0
    
    open_p = float(row[2] or 0) / scale
    low_p = float(row[0] or 0) / scale
    high_p = float(row[1] or 0) / scale
    close_p = float(row[3] or 0) / scale
    trades_cnt = row[4]
    vol_tot = int(row[5] or 0)
    delta = int(row[6] or 0)

    amp_pts = high_p - low_p
    amp_ticks = int(round(amp_pts * 2)) if is_usd else int(round(amp_pts / 5))

    print(f"=================================================================================")
    print(f" 📅 RESUMO DO PREGÃO COMPLETO: {ticker} em {date_str}")
    print(f"=================================================================================")
    print(f"  • Abertura   : {open_p:10.2f}")
    print(f"  • Mínima     : {low_p:10.2f}")
    print(f"  • Máxima     : {high_p:10.2f}")
    print(f"  • Fechamento : {close_p:10.2f}")
    print(f"  • Amplitude  : {amp_pts:10.2f} pts ({amp_ticks} ticks)")
    print(f"  • Negócios   : {trades_cnt:10,}")
    print(f"  • Volume (Q) : {vol_tot:10,} contratos")
    print(f"  • Delta (CVD): {delta:+10,} contratos")
    print(f"=================================================================================\n")

def analyze_time_window(cur, ticker, date_str, start_time, end_time):
    if " " in start_time:
        start_ts = start_time if start_time.count(":") == 2 else f"{start_time}:00"
    else:
        start_ts = f"{date_str} {start_time}" if start_time.count(":") == 2 else f"{date_str} {start_time}:00"

    if " " in end_time:
        end_ts = end_time if end_time.count(":") == 2 else f"{end_time}:00"
    else:
        end_ts = f"{date_str} {end_time}" if end_time.count(":") == 2 else f"{date_str} {end_time}:00"

    is_usd = ticker.startswith("WDO") or ticker.startswith("DOL")
    scale = 10.0 if is_usd else 1.0

    # 1. Resumo do trecho
    cur.execute("""
        SELECT MIN(price), MAX(price),
               (SELECT price FROM trades WHERE ticker=%s AND ts >= %s::timestamp AND ts <= %s::timestamp ORDER BY ts ASC LIMIT 1),
               (SELECT price FROM trades WHERE ticker=%s AND ts >= %s::timestamp AND ts <= %s::timestamp ORDER BY ts DESC LIMIT 1),
               COUNT(*), SUM(qty),
               SUM(CASE WHEN trade_type=2 THEN qty WHEN trade_type=3 THEN -qty ELSE 0 END)
        FROM trades
        WHERE ticker=%s AND ts >= %s::timestamp AND ts <= %s::timestamp
    """, (ticker, start_ts, end_ts, ticker, start_ts, end_ts, ticker, start_ts, end_ts))
    row = cur.fetchone()
    if not row or row[4] == 0:
        print(f"=== [SEM TRADES NA JANELA] Ticker: {ticker} ({start_ts} a {end_ts}) ===")
        return

    open_p = float(row[2] or 0) / scale
    low_p = float(row[0] or 0) / scale
    high_p = float(row[1] or 0) / scale
    close_p = float(row[3] or 0) / scale
    amp_pts = high_p - low_p
    amp_ticks = int(round(amp_pts * 2)) if is_usd else int(round(amp_pts / 5))

    print(f"=================================================================================")
    print(f" 🕒 ANÁLISE DE TRECHO: {ticker} | {date_str} ({start_time} às {end_time})")
    print(f"=================================================================================")
    print(f"  • Extremos do Trecho : {low_p:.2f} (Mín) a {high_p:.2f} (Máx) -> Amplitude: {amp_pts:.2f} pts ({amp_ticks} ticks)")
    print(f"  • Abertura -> Fech.  : {open_p:.2f} -> {close_p:.2f} (Variação: {close_p - open_p:+.2f} pts)")
    print(f"  • Volume & Delta     : {row[5]:,} contratos | CVD Líquido: {row[6]:+,} contratos")
    print(f"=================================================================================\n")

    # 2. Top Agressores de Compra e Venda
    cur.execute("""
        WITH compras AS (
            SELECT buy_agent as agent, SUM(qty) as comp
            FROM trades WHERE ts >= %s::timestamp AND ts <= %s::timestamp AND ticker=%s AND trade_type IN (2,3)
            GROUP BY 1
        ),
        vendas AS (
            SELECT sell_agent as agent, SUM(qty) as vend
            FROM trades WHERE ts >= %s::timestamp AND ts <= %s::timestamp AND ticker=%s AND trade_type IN (2,3)
            GROUP BY 1
        )
        SELECT COALESCE(c.agent, v.agent) as agent_id,
               COALESCE(comp, 0) as compra,
               COALESCE(vend, 0) as venda,
               COALESCE(comp, 0) - COALESCE(vend, 0) as net,
               COALESCE(comp, 0) + COALESCE(vend, 0) as total
        FROM compras c FULL OUTER JOIN vendas v ON c.agent = v.agent
        ORDER BY net DESC LIMIT 8
    """, (start_ts, end_ts, ticker, start_ts, end_ts, ticker))
    
    print(" 🚀 TOP 8 PLAYERS COMPRADORES LÍQUIDOS (Quem puxou/agrediu na compra):")
    print(" Cód  | Corretora         | Compra     | Venda      | Saldo Net  | Volume Total")
    print(" " + "-"*75)
    for r in cur.fetchall():
        nome = corretoras.get_nome_corretora(r[0])
        print(f" {r[0]:<4} | {nome:<17} | {int(r[1]):>10,} | {int(r[2]):>10,} | {int(r[3]):>+10,} | {int(r[4]):>10,}")
    print()

    cur.execute("""
        WITH compras AS (
            SELECT buy_agent as agent, SUM(qty) as comp
            FROM trades WHERE ts >= %s::timestamp AND ts <= %s::timestamp AND ticker=%s AND trade_type IN (2,3)
            GROUP BY 1
        ),
        vendas AS (
            SELECT sell_agent as agent, SUM(qty) as vend
            FROM trades WHERE ts >= %s::timestamp AND ts <= %s::timestamp AND ticker=%s AND trade_type IN (2,3)
            GROUP BY 1
        )
        SELECT COALESCE(c.agent, v.agent) as agent_id,
               COALESCE(comp, 0) as compra,
               COALESCE(vend, 0) as venda,
               COALESCE(comp, 0) - COALESCE(vend, 0) as net,
               COALESCE(comp, 0) + COALESCE(vend, 0) as total
        FROM compras c FULL OUTER JOIN vendas v ON c.agent = v.agent
        ORDER BY net ASC LIMIT 8
    """, (start_ts, end_ts, ticker, start_ts, end_ts, ticker))

    print(" 🛡️ TOP 8 PLAYERS VENDEDORES LÍQUIDOS (Absorção / Contra-fluxo / Despejo):")
    print(" Cód  | Corretora         | Compra     | Venda      | Saldo Net  | Volume Total")
    print(" " + "-"*75)
    for r in cur.fetchall():
        nome = corretoras.get_nome_corretora(r[0])
        print(f" {r[0]:<4} | {nome:<17} | {int(r[1]):>10,} | {int(r[2]):>10,} | {int(r[3]):>+10,} | {int(r[4]):>10,}")
    print()

def main():
    parser = argparse.ArgumentParser(description="Análise quantitativa de microestrutura e fluxo de ordens (ProfitDLL).")
    parser.add_argument("--ticker", required=True, help="Código do ativo (ex: WDOQ26, DOLQ26, WINQ26)")
    parser.add_argument("--date", default="2026-07-16", help="Data YYYY-MM-DD (padrão: hoje)")
    parser.add_argument("--start", help="Hora início HH:MM (ex: 09:30)")
    parser.add_argument("--end", help="Hora fim HH:MM (ex: 10:00)")
    parser.add_argument("--daily", action="store_true", help="Exibe resumo diário completo do ativo")
    
    args = parser.parse_args()
    
    conn = get_connection()
    cur = conn.cursor()
    try:
        if args.daily or not (args.start and args.end):
            analyze_daily_summary(cur, args.ticker, args.date)
        if args.start and args.end:
            analyze_time_window(cur, args.ticker, args.date, args.start, args.end)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
