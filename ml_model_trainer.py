#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
===================================================================================
PROFITDLL / DATAFEED - PILAR 2: MOTOR DE RE-TREINAMENTO QUANTITATIVO (MLOPS)
===================================================================================
Arquivo: ml_model_trainer.py
Descrição: Motor de Aprendizado Supervisionado com Validação Temporal (Walk-Forward)
           e Calibração Ótima de Threshold Quantitativo.
===================================================================================
"""

import os
import sys
import json
import pickle
import argparse
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
from config import DB_DSN
from price_utils import to_real_points, format_price_b3
from market_calendar import get_market_calendar_features
from dynamic_harmonics import get_daily_harmonic_step, get_closest_harmonic_distance

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


def fetch_labeled_dataset(conn, date_filter: str = None, ticker_filter: str = None) -> pd.DataFrame:
    where_clauses = ["labeled_at IS NOT NULL", "hit_scalp_2_5 IS NOT NULL", "signal_type != 'NEUTRAL'"]
    params = []

    if date_filter:
        where_clauses.append("ts >= %s::timestamp AND ts <= %s::timestamp")
        params.extend([f"{date_filter} 00:00:00", f"{date_filter} 23:59:59"])

    if ticker_filter:
        where_clauses.append("ticker = %s")
        params.append(ticker_filter)

    where_sql = " AND ".join(where_clauses)
    query = f"""
        SELECT id, ts, ticker, signal_type, direction, price_at_signal, context,
               mfe_3m, mae_3m, hit_scalp_2_5, outcome_pts
        FROM signals
        WHERE {where_sql}
        ORDER BY ts ASC
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params)
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
            "signal_type": str(r["signal_type"]),
            "direction": int(r["direction"] or 0),
            "price": price_real,
            "cvd_big": float(ctx.get("cvd_big", 0)),
            "cvd_varejo": float(ctx.get("cvd_varejo", 0)),
            "delta_p": float(ctx.get("delta_p", 0.0)),
            "total_qty": float(ctx.get("total_qty", 0)),
            "dist_to_macro_harmonic": dist_harmonic,
            "month_week_phase": cal_feat.get("month_week_phase", 2),
            "days_to_rollover": cal_feat.get("days_to_rollover", 15),
            "is_payroll_week": cal_feat.get("is_payroll_week", 0),
            "mfe_3m": float(r["mfe_3m"] or 0.0),
            "mae_3m": float(r["mae_3m"] or 0.0),
            "outcome_pts": float(r["outcome_pts"] or 0.0),
            "target": 1 if r["hit_scalp_2_5"] else 0
        })

    return pd.DataFrame(records)


def build_feature_matrix(df: pd.DataFrame):
    canonical_signals = [
        "ABSORCAO_COMPRADORA", "ABSORCAO_VENDEDORA",
        "IMPULSO_COMPRADOR", "IMPULSO_VENDEDOR",
        "DISTRIBUICAO_TOPO", "ACUMULACAO_FUNDO",
        "COMBO_ABSORCAO_IMPULSO_COMPRA", "COMBO_ABSORCAO_IMPULSO_VENDA"
    ]

    for sig in canonical_signals:
        df[f"sig__{sig}"] = (df["signal_type"] == sig).astype(float)

    feature_cols = [
        "direction", "cvd_big", "cvd_varejo", "delta_p", "total_qty", "dist_to_macro_harmonic",
        "month_week_phase", "days_to_rollover", "is_payroll_week"
    ] + [f"sig__{sig}" for sig in canonical_signals]

    X = df[feature_cols].copy().fillna(0.0)
    y = df["target"].values

    return X, y, feature_cols


def find_optimal_threshold(y_true, y_prob):
    """Encontra o threshold de probabilidade que maximiza a precisão mantendo F1 saudável."""
    best_thresh = 0.30
    best_f1 = 0.0
    for th in np.arange(0.18, 0.50, 0.02):
        preds = (y_prob >= th).astype(int)
        f1 = f1_score(y_true, preds, zero_division=0)
        if f1 > best_f1:
            best_f1 = f1
            best_thresh = th
    return best_thresh


def train_and_evaluate_walk_forward(X: pd.DataFrame, y: np.ndarray, feature_names: list, n_splits: int = 5):
    tscv = TimeSeriesSplit(n_splits=n_splits)
    scaler = StandardScaler()
    metrics_list = []
    fold = 1

    print("\n" + "="*102)
    print(" ⏱️  WALK-FORWARD VALIDATION COM CALIBRAÇÃO DINÂMICA DE THRESHOLD QUANTITATIVO")
    print("="*102)
    print(f" {'DOBRA':<7} | {'TREINO':<8} | {'TESTE':<8} | {'THRESHOLD':<10} | {'ACURÁCIA':<10} | {'PRECISÃO':<10} | {'RECALL':<10} | {'F1-SCORE':<10} | {'ROC-AUC'}")
    print(" " + "-"*100)

    for train_idx, test_idx in tscv.split(X):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]

        if len(np.unique(y_train)) < 2 or len(np.unique(y_test)) < 2:
            continue

        X_tr_sc = scaler.fit_transform(X_train)
        X_te_sc = scaler.transform(X_test)

        # Treino com Random Forest balanceado
        base_rf = RandomForestClassifier(n_estimators=150, max_depth=6, class_weight="balanced", random_state=42, n_jobs=-1)
        calibrated_model = CalibratedClassifierCV(estimator=base_rf, method="sigmoid", cv=3)
        calibrated_model.fit(X_tr_sc, y_train)

        # Determinar threshold ótimo na base de treino (sem vazamento para teste!)
        y_tr_prob = calibrated_model.predict_proba(X_tr_sc)[:, 1]
        opt_thresh = find_optimal_threshold(y_train, y_tr_prob)

        # Testar na base out-of-sample estrita
        y_te_prob = calibrated_model.predict_proba(X_te_sc)[:, 1]
        y_pred = (y_te_prob >= opt_thresh).astype(int)

        acc = accuracy_score(y_test, y_pred)
        prec = precision_score(y_test, y_pred, zero_division=0)
        rec = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)
        roc = roc_auc_score(y_test, y_te_prob) if len(np.unique(y_test)) > 1 else 0.5

        metrics_list.append({"fold": fold, "thresh": opt_thresh, "acc": acc, "prec": prec, "rec": rec, "f1": f1, "roc": roc})

        print(f" Fold {fold:<2} | {len(X_train):<8} | {len(X_test):<8} | {opt_thresh*100:5.1f}%     | {acc*100:6.1f}%    | {prec*100:6.1f}%    | {rec*100:6.1f}%    | {f1*100:6.1f}%    | {roc:.3f}")
        fold += 1

    print("="*102)

    # Treinar modelo final em 100% dos dados para persistência
    X_full_sc = scaler.fit_transform(X)
    final_base = RandomForestClassifier(n_estimators=200, max_depth=7, class_weight="balanced", random_state=42, n_jobs=-1)
    final_model = CalibratedClassifierCV(estimator=final_base, method="sigmoid", cv=3)
    final_model.fit(X_full_sc, y)

    y_full_prob = final_model.predict_proba(X_full_sc)[:, 1]
    final_thresh = find_optimal_threshold(y, y_full_prob)

    avg_acc = np.mean([m["acc"] for m in metrics_list]) if metrics_list else 0.0
    avg_prec = np.mean([m["prec"] for m in metrics_list]) if metrics_list else 0.0
    avg_rec = np.mean([m["rec"] for m in metrics_list]) if metrics_list else 0.0
    avg_f1 = np.mean([m["f1"] for m in metrics_list]) if metrics_list else 0.0
    avg_roc = np.mean([m["roc"] for m in metrics_list]) if metrics_list else 0.0

    print(f"\n📊 MÉDIAS FINAIS WALK-FORWARD:")
    print(f"   🎯 Acurácia: {avg_acc*100:.1f}% | Precisão: {avg_prec*100:.1f}% | Recall: {avg_rec*100:.1f}%")
    print(f"   🔥 F1-Score: {avg_f1*100:.1f}% | ROC-AUC: {avg_roc:.3f} | Threshold Ótimo: {final_thresh*100:.1f}%\n")

    return final_model, scaler, final_thresh, {"acc": avg_acc, "prec": avg_prec, "rec": avg_rec, "f1": avg_f1, "roc": avg_roc, "thresh": final_thresh}, metrics_list


def save_model_artifact(model, scaler, threshold: float, feature_names: list, df_len: int, metrics: dict):
    os.makedirs(MODELS_DIR, exist_ok=True)
    pkl_path = os.path.join(MODELS_DIR, "quant_signals_v1.pkl")
    json_path = os.path.join(MODELS_DIR, "quant_signals_v1.json")

    payload = {
        "model": model,
        "scaler": scaler,
        "optimal_threshold": threshold,
        "feature_names": feature_names,
        "trained_at": datetime.now().isoformat(),
        "total_samples": df_len,
        "cv_metrics": metrics
    }

    with open(pkl_path, "wb") as f:
        pickle.dump(payload, f)

    meta_json = {
        "model_type": "CalibratedClassifierCV(RandomForestClassifier)",
        "optimal_threshold_pct": round(threshold * 100, 2),
        "feature_names": feature_names,
        "trained_at": datetime.now().isoformat(),
        "total_samples": df_len,
        "avg_accuracy_pct": round(metrics.get("acc", 0.0) * 100, 2),
        "avg_precision_pct": round(metrics.get("prec", 0.0) * 100, 2),
        "avg_recall_pct": round(metrics.get("rec", 0.0) * 100, 2),
        "avg_f1_score_pct": round(metrics.get("f1", 0.0) * 100, 2),
        "avg_roc_auc": round(metrics.get("roc", 0.0), 3),
        "artifact_path": pkl_path
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta_json, f, indent=2, ensure_ascii=False)

    print(f"💾 [MODELO PERSISTIDO COM SUCESSO] {pkl_path}")


def main():
    parser = argparse.ArgumentParser(description="Motor de Re-treinamento Quantitativo ML.")
    parser.add_argument("--date", help="Filtrar por data YYYY-MM-DD")
    parser.add_argument("--ticker", help="Filtrar por ticker (ex: WDOU26)")
    parser.add_argument("--splits", type=int, default=5, help="Número de folds do Walk-Forward")
    args = parser.parse_args()

    print("\n🚀 [MLOPS TREINADOR] Conectando ao PostgreSQL...")
    try:
        with psycopg2.connect(DB_DSN) as conn:
            df = fetch_labeled_dataset(conn, args.date, args.ticker)

        if df.empty:
            print("❌ Nenhum dado rotulado encontrado.")
            sys.exit(0)

        print(f"📊 Dataset: {len(df):,} sinais auditados carregados.")
        X, y, feature_names = build_feature_matrix(df)
        model, scaler, thresh, metrics, _ = train_and_evaluate_walk_forward(X, y, feature_names, n_splits=args.splits)
        save_model_artifact(model, scaler, thresh, feature_names, len(df), metrics)

    except Exception as e:
        print(f"\n❌ Erro durante o treinamento ML: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
