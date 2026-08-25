#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
===================================================================================
PROFITDLL / DATAFEED - PILAR 1: ETIQUETADOR AUTOMÁTICO DE ALTA PERFORMANCE
===================================================================================
Arquivo: daily_postmarket_labeler.py
Descrição: Etiquetador Forense com carregamento em lote por dia e busca binária (bisect).
           Mede MFE, MAE, hit_scalp_2_5 e outcome_pts com precisão de meio ponto em microssegundos.
===================================================================================
"""

import os
import sys
import json
import bisect
import argparse
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from config import DB_DSN
from price_utils import to_real_points, format_price_b3

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def ensure_table_columns(conn):
    """Garante que a tabela `signals` possui todas as colunas de auditoria forense."""
    ddl_statements = [
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS mfe_1m NUMERIC(10, 2);",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS mae_1m NUMERIC(10, 2);",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS mfe_3m NUMERIC(10, 2);",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS mae_3m NUMERIC(10, 2);",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS mfe_5m NUMERIC(10, 2);",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS mae_5m NUMERIC(10, 2);",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS hit_scalp_2_5 BOOLEAN;",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS outcome_pts NUMERIC(10, 2);",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS outcome_window SMALLINT DEFAULT 3;",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS labeled_at TIMESTAMPTZ;"
    ]
    with conn.cursor() as cur:
        for ddl in ddl_statements:
            cur.execute(ddl)
    conn.commit()


def calculate_window_metrics_fast(trades_ts: list, trades_prices: list, price_signal: float, direction: int, gain_pts: float, stop_pts: float):
    """Calcula MFE, MAE e hit_scalp em arrays pré-convertidos para pontos reais."""
    if not trades_ts:
        return {
            "mfe_1m": 0.0, "mae_1m": 0.0,
            "mfe_3m": 0.0, "mae_3m": 0.0,
            "mfe_5m": 0.0, "mae_5m": 0.0,
            "hit_scalp": False, "outcome_pts": 0.0
        }

    t0 = trades_ts[0]
    gain_limit = price_signal + gain_pts if direction == 1 else price_signal - gain_pts
    stop_limit = price_signal - stop_pts if direction == 1 else price_signal + stop_pts

    mfe_1m, mae_1m = 0.0, 0.0
    mfe_3m, mae_3m = 0.0, 0.0
    mfe_5m, mae_5m = 0.0, 0.0
    hit_scalp = False
    scalp_decided = False
    last_price_3m = price_signal

    for ts, p in zip(trades_ts, trades_prices):
        dt_seconds = (ts - t0).total_seconds()

        if direction == 1:
            fav = p - price_signal
            adv = price_signal - p
        else:
            fav = price_signal - p
            adv = p - price_signal

        if dt_seconds <= 60:
            if fav > mfe_1m: mfe_1m = fav
            if adv > mae_1m: mae_1m = adv

        if dt_seconds <= 180:
            if fav > mfe_3m: mfe_3m = fav
            if adv > mae_3m: mae_3m = adv
            last_price_3m = p

            if not scalp_decided:
                if direction == 1:
                    if p >= gain_limit:
                        hit_scalp = True
                        scalp_decided = True
                    elif p <= stop_limit:
                        hit_scalp = False
                        scalp_decided = True
                else:
                    if p <= gain_limit:
                        hit_scalp = True
                        scalp_decided = True
                    elif p >= stop_limit:
                        hit_scalp = False
                        scalp_decided = True

        if dt_seconds <= 300:
            if fav > mfe_5m: mfe_5m = fav
            if adv > mae_5m: mae_5m = adv

    outcome_pts = (last_price_3m - price_signal) if direction == 1 else (price_signal - last_price_3m)

    return {
        "mfe_1m": round(max(0.0, mfe_1m), 2),
        "mae_1m": round(max(0.0, mae_1m), 2),
        "mfe_3m": round(max(0.0, mfe_3m), 2),
        "mae_3m": round(max(0.0, mae_3m), 2),
        "mfe_5m": round(max(0.0, mfe_5m), 2),
        "mae_5m": round(max(0.0, mae_5m), 2),
        "hit_scalp": hit_scalp,
        "outcome_pts": round(outcome_pts, 2)
    }


def run_labeler_fast(conn, date_filter: str = None, ticker_filter: str = None, gain_pts: float = 2.5, stop_pts: float = 2.0, recalculate: bool = False):
    ensure_table_columns(conn)

    where_clauses = ["signal_type != 'NEUTRAL'", "direction != 0"]
    params = []

    if date_filter:
        where_clauses.append("ts >= %s::timestamp AND ts <= %s::timestamp")
        params.extend([f"{date_filter} 00:00:00", f"{date_filter} 23:59:59"])

    if ticker_filter:
        where_clauses.append("ticker = %s")
        params.append(ticker_filter)

    if not recalculate:
        where_clauses.append("labeled_at IS NULL")

    where_sql = " AND ".join(where_clauses)
    
    # 1. Buscar todos os dias e tickers distintos que precisam de auditoria
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT ts::date, ticker FROM signals WHERE {where_sql} ORDER BY ts::date ASC", params)
        day_tickers = cur.fetchall()

    if not day_tickers:
        print("[OK] Nenhum sinal pendente de etiquetagem.")
        return []

    print(f"\n🚀 [ETIQUETADOR ALTA PERFORMANCE] Auditando {len(day_tickers)} dias/tickers com Gain={gain_pts} pts | Stop={stop_pts} pts...")

    all_results = []
    total_updated = 0

    for day, tck in day_tickers:
        d_str = day.strftime("%Y-%m-%d")
        
        # Carregar sinais do dia
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT id, ticker, ts, signal_type, direction, price_at_signal
                FROM signals
                WHERE ts >= %s AND ts <= %s AND ticker = %s AND {where_sql}
                ORDER BY ts ASC
            """, [f"{d_str} 00:00:00", f"{d_str} 23:59:59", tck] + params)
            day_signals = cur.fetchall()

        if not day_signals:
            continue

        # Carregar todos os trades do dia em memória de uma vez só!
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ts, price
                FROM trades
                WHERE ticker = %s AND ts >= %s AND ts <= %s
                ORDER BY ts ASC
            """, (tck, f"{d_str} 00:00:00", f"{d_str} 23:59:59"))
            raw_trades = cur.fetchall()

        if not raw_trades:
            continue

        # Converter para listas alinhadas (timestamps e precos normalizados em pontos reais)
        trades_ts = [r[0].replace(tzinfo=None) if hasattr(r[0], 'tzinfo') and r[0].tzinfo else r[0] for r in raw_trades]
        trades_prices = [to_real_points(r[1], tck) for r in raw_trades]

        updates = []
        for sig in day_signals:
            sig_id = sig["id"]
            ts_sig = sig["ts"].replace(tzinfo=None) if hasattr(sig["ts"], 'tzinfo') and sig["ts"].tzinfo else sig["ts"]
            direction = int(sig["direction"] or 0)
            price_sig = to_real_points(sig["price_at_signal"], tck)

            if direction == 0 or price_sig == 0:
                continue

            end_ts = ts_sig + timedelta(minutes=5)

            # Busca binária rápida O(log N) da janela de 5 minutos
            idx_start = bisect.bisect_left(trades_ts, ts_sig)
            idx_end = bisect.bisect_right(trades_ts, end_ts)

            slice_ts = trades_ts[idx_start:idx_end]
            slice_prices = trades_prices[idx_start:idx_end]

            m = calculate_window_metrics_fast(slice_ts, slice_prices, price_sig, direction, gain_pts, stop_pts)

            updates.append((
                m["mfe_1m"], m["mae_1m"],
                m["mfe_3m"], m["mae_3m"],
                m["mfe_5m"], m["mae_5m"],
                m["hit_scalp"],
                m["outcome_pts"],
                sig_id
            ))

            all_results.append({
                "ticker": tck,
                "signal_type": sig["signal_type"],
                "direction": direction,
                **m
            })

        if updates:
            with conn.cursor() as cur:
                update_sql = """
                    UPDATE signals AS s SET
                        mfe_1m = v.mfe_1m, mae_1m = v.mae_1m,
                        mfe_3m = v.mfe_3m, mae_3m = v.mae_3m,
                        mfe_5m = v.mfe_5m, mae_5m = v.mae_5m,
                        hit_scalp_2_5 = v.hit_scalp,
                        outcome_pts = v.outcome_pts,
                        outcome_window = 3,
                        labeled_at = NOW()
                    FROM (VALUES %s) AS v(mfe_1m, mae_1m, mfe_3m, mae_3m, mfe_5m, mae_5m, hit_scalp, outcome_pts, id)
                    WHERE s.id = v.id;
                """
                execute_values(cur, update_sql, updates, template="(%s, %s, %s, %s, %s, %s, %s, %s, %s)")
            conn.commit()
            total_updated += len(updates)
            print(f"  ✅ {d_str} ({tck}): {len(updates):,} sinais etiquetados com sucesso.")

    print(f"\n🎉 Total final: {total_updated:,} sinais rotulados com Ground Truth real.")
    return all_results


def print_summary(results: list, gain_pts: float, stop_pts: float):
    if not results:
        return

    print("\n" + "="*95)
    print(" 🏆 RESUMO EXECUTIVO DO GROUND TRUTH — AUDITORIA FORENSE DE SINAIS (REAL)")
    print(f" ⚙️  Parâmetros de Scalping: Gain +{gain_pts:.1f} pts | Stop -{stop_pts:.1f} pts (Janela 3m)")
    print("="*95)

    stats = {}
    for r in results:
        st = r["signal_type"]
        if st not in stats:
            stats[st] = {"count": 0, "wins": 0, "mfe_3m_sum": 0.0, "mae_3m_sum": 0.0, "outcome_sum": 0.0}
        stats[st]["count"] += 1
        if r["hit_scalp"]: stats[st]["wins"] += 1
        stats[st]["mfe_3m_sum"] += r["mfe_3m"]
        stats[st]["mae_3m_sum"] += r["mae_3m"]
        stats[st]["outcome_sum"] += r["outcome_pts"]

    print(f" {'TIPO DO ALERTA (SIGNAL_TYPE)':<32} | {'SINAIS':<7} | {'TAXA WIN':<10} | {'MFE 3M':<8} | {'MAE 3M':<8} | {'RETORNO MED'}")
    print(" " + "-"*93)

    for st, d in sorted(stats.items(), key=lambda x: x[1]["wins"]/x[1]["count"] if x[1]["count"]>0 else 0, reverse=True):
        cnt = d["count"]
        win_rate = (d["wins"] / cnt) * 100 if cnt > 0 else 0.0
        avg_mfe = d["mfe_3m_sum"] / cnt
        avg_mae = d["mae_3m_sum"] / cnt
        avg_out = d["outcome_sum"] / cnt

        win_str = f"{win_rate:5.1f}%"
        out_str = f"{avg_out:+5.2f} pts"

        print(f" {st:<32} | {cnt:<7,} | {win_str:<10} | {avg_mfe:6.2f} pt | {avg_mae:6.2f} pt | {out_str}")

    print("="*95 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Etiquetador de Alta Performance.")
    parser.add_argument("--date", default=None, help="Filtrar por data YYYY-MM-DD")
    parser.add_argument("--ticker", default=None, help="Filtrar por ticker (ex: WDOU26)")
    parser.add_argument("--gain", type=float, default=2.5, help="Pontos de Gain")
    parser.add_argument("--stop", type=float, default=2.0, help="Pontos de Stop")
    parser.add_argument("--recalculate", action="store_true", help="Recalcular todos os sinais históricos")

    args = parser.parse_args()

    try:
        with psycopg2.connect(DB_DSN) as conn:
            results = run_labeler_fast(conn, args.date, args.ticker, args.gain, args.stop, args.recalculate)
            print_summary(results, args.gain, args.stop)
    except Exception as e:
        print(f"\n❌ Erro durante a execução do etiquetador: {e}")
        sys.exit(1)
