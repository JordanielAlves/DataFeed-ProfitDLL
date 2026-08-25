"""
feature_audit.py
Auditoria Estatística e Causal das Variáveis Quantitativas (Zero Lookahead Bias).
Mede correlação (Spearman), Ganho de Informação Mútua (Mutual Information) e Poder Preditivo
sobre o Ground Truth real de ganho no scalper (+2.5 pts / -2.0 pts).
"""

import os
import sys
import json
import logging
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import numpy as np
import pandas as pd
from sklearn.feature_selection import mutual_info_classif
from sklearn.ensemble import ExtraTreesClassifier
from config import DB_DSN
from price_utils import to_real_points, format_price_b3
from market_calendar import get_market_calendar_features
from dynamic_harmonics import get_daily_harmonic_step, get_closest_harmonic_distance

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def load_dataset(conn) -> pd.DataFrame:
    query = """
        SELECT id, ts, ticker, signal_type, direction, price_at_signal, context,
               mfe_3m, mae_3m, hit_scalp_2_5, outcome_pts
        FROM signals
        WHERE labeled_at IS NOT NULL 
          AND hit_scalp_2_5 IS NOT NULL
          AND signal_type != 'NEUTRAL'
        ORDER BY ts ASC;
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query)
        rows = cur.fetchall()

    if not rows:
        return pd.DataFrame()

    cur_ohlc = conn.cursor()
    cur_ohlc.execute("SELECT date, open_p FROM daily_ohlc WHERE ticker = 'WDOFUT'")
    open_map = {r[0]: float(r[1]) for r in cur_ohlc.fetchall()}
    cur_ohlc.close()

    unique_dates = set(r["ts"].date() for r in rows)
    harmonic_steps = {d: get_daily_harmonic_step(d, auto_sync=False) for d in unique_dates}

    records = []
    for r in rows:
        ctx = r["context"] or {}
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except Exception:
                ctx = {}

        tck = r["ticker"]
        price_real = to_real_points(r["price_at_signal"], tck)
        sig_date = r["ts"].date()
        open_p = open_map.get(sig_date, price_real)

        step = harmonic_steps.get(sig_date, 16.5)
        dist_harmonic = get_closest_harmonic_distance(price_real, open_p, step)

        cal_feat = get_market_calendar_features(r["ts"])

        records.append({
            "id": r["id"],
            "ts": r["ts"],
            "ticker": tck,
            "signal_type": r["signal_type"],
            "direction": int(r["direction"] or 0),
            "price": price_real,
            "cvd_big": float(ctx.get("cvd_big", 0)),
            "cvd_varejo": float(ctx.get("cvd_varejo", 0)),
            "delta_p": float(ctx.get("delta_p", 0.0)),
            "total_qty": float(ctx.get("total_qty", 0)),
            "dist_to_macro_harmonic": dist_harmonic,
            "hour": r["ts"].hour,
            "minute": r["ts"].minute,
            "minutes_since_open": max(0, int((r["ts"] - r["ts"].replace(hour=9, minute=0, second=0)).total_seconds() / 60)),
            "days_to_rollover": cal_feat.get("days_to_rollover", 15),
            "is_payroll_week": cal_feat.get("is_payroll_week", 0),
            "outcome_pts": float(r["outcome_pts"] or 0.0),
            "mfe_3m": float(r["mfe_3m"] or 0.0),
            "mae_3m": float(r["mae_3m"] or 0.0),
            "target": 1 if r["hit_scalp_2_5"] else 0
        })

    return pd.DataFrame(records)


def run_feature_audit():
    print("\n" + "="*88)
    print(" 🔬 AUDITORIA ESTATÍSTICA E CAUSAL DE FEATURES (ZERO LOOKAHEAD BIAS)")
    print("="*88)

    with psycopg2.connect(DB_DSN) as conn:
        df = load_dataset(conn)

    if df.empty:
        print("❌ Nenhum dado etiquetado encontrado.")
        return

    print(f"📊 Dataset carregado com {len(df):,} sinais auditados.")
    win_rate_geral = (df['target'].mean()) * 100
    print(f"🎯 Win Rate Global do Dataset: {win_rate_geral:.1f}% ({df['target'].sum():,} vitórias de {len(df):,} sinais)")

    sig_dummies = pd.get_dummies(df['signal_type'], prefix="sig")
    
    numeric_features = [
        "direction", "cvd_big", "cvd_varejo", "delta_p", "total_qty",
        "dist_to_macro_harmonic", "hour", "minutes_since_open",
        "days_to_rollover", "is_payroll_week"
    ]
    
    X = pd.concat([df[numeric_features], sig_dummies], axis=1).fillna(0.0)
    y = df['target'].values

    # 1. Informação Mútua
    mi_scores = mutual_info_classif(X, y, random_state=42)
    mi_series = pd.Series(mi_scores, index=X.columns).sort_values(ascending=False)

    # 2. ExtraTrees Feature Importance
    clf = ExtraTreesClassifier(n_estimators=100, max_depth=6, random_state=42, class_weight='balanced', n_jobs=-1)
    clf.fit(X, y)
    rf_series = pd.Series(clf.feature_importances_, index=X.columns).sort_values(ascending=False)

    # 3. Exibir Tabela Consolidada
    print("\n" + "="*88)
    print(" 🌟 RANKING DAS VARIÁVEIS MAIS PREDITIVAS (INFO GAIN & IMPORTÂNCIA)")
    print("="*88)
    print(f" {'POS':<4} | {'VARIÁVEL / FEATURE':<36} | {'PESO RF (%)':<14} | {'MUTUAL INFO':<14}")
    print(" " + "-"*86)

    for idx, feat in enumerate(rf_series.index, 1):
        rf_p = rf_series[feat] * 100
        mi_val = mi_series.get(feat, 0.0)
        feat_clean = feat.replace("sig_", "Tipo: ")
        print(f" {idx:<4} | {feat_clean:<36} | {rf_p:6.2f}%        | {mi_val:8.4f}")

    print("="*88 + "\n")


if __name__ == "__main__":
    run_feature_audit()
