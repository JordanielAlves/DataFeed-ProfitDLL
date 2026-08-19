#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
===================================================================================
PROFITDLL / DATAFEED - PILAR 2: MOTOR DE RE-TREINAMENTO DINÂMICO DE ML
===================================================================================
Arquivo: ml_model_trainer.py
Descrição: Motor de Aprendizado Supervisionado (Supervised ML Retraining Engine).
           Consome os sinais auditados e rotulados com desfechos pelo Pilar 1
           (`daily_postmarket_labeler.py`), constrói a matriz de features ($X$) e
           o vetor alvo de sucesso no scalping ($y = hit_scalp_2_5$), executa
           validação cruzada temporal sem vazamento (TimeSeriesSplit) e exporta
           o modelo quantitativo otimizado (`models/quant_signals_v1.pkl`) para
           pontuação de sinais em tempo real pelo preditor da Fase 3.
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
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from market_calendar import get_market_calendar_features
from dynamic_harmonics import get_daily_harmonic_step, get_closest_harmonic_distance

# Blindagem de Encoding para Terminal Windows (evita UnicodeEncodeError em emojis/Powerline)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Configuração Padrão do Banco de Dados
DB_DSN = os.getenv("PROFIT_DB_DSN", "dbname=fluxo_ordens user=postgres password=postgres host=localhost")
MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


def get_scale_factor(ticker: str) -> float:
    """Retorna o fator de escala do ativo no banco (Regra 1 AGENTS.md)."""
    if ticker.startswith("WDO") or ticker.startswith("DOL"):
        return 10.0
    elif ticker.startswith("WIN") or ticker.startswith("IND"):
        return 1.0
    return 1.0


def fetch_labeled_dataset(conn, date_filter: str = None, ticker_filter: str = None) -> pd.DataFrame:
    """
    Busca no PostgreSQL todos os sinais que já possuem auditoria forense do Pilar 1
    (`labeled_at IS NOT NULL AND hit_scalp_2_5 IS NOT NULL`).
    """
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

    records = []
    for r in rows:
        ctx = r["context"] or {}
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except Exception:
                ctx = {}

        tck = r["ticker"]
        scale = get_scale_factor(tck)

        records.append({
            "id": r["id"],
            "ts": r["ts"],
            "ticker": tck,
            "signal_type": str(r["signal_type"]),
            "direction": int(r["direction"] or 0),
            "price_at_signal": float(r["price_at_signal"]) / scale,
            "cvd_big": float(ctx.get("cvd_big", 0)),
            "cvd_varejo": float(ctx.get("cvd_varejo", 0)),
            "delta_p": float(ctx.get("delta_p", 0.0)),
            "total_qty": float(ctx.get("total_qty", 0)),
            "dist_to_macro_harmonic": float(ctx.get("dist_to_macro_harmonic", 10.0)),
            "mfe_3m": float(r["mfe_3m"] or 0.0),
            "mae_3m": float(r["mae_3m"] or 0.0),
            "outcome_pts": float(r["outcome_pts"] or 0.0),
            "target": 1 if r["hit_scalp_2_5"] else 0
        })

    return pd.DataFrame(records)

def inject_harmonic_distances(df: pd.DataFrame, conn):
    """
    Calcula a dist_to_macro_harmonic de forma retrospectiva e rápida sem precisar
    ter no context JSON do PostgreSQL.
    """
    # 1. Puxa os preços de abertura de todos os dias
    query_open = "SELECT date, open_p FROM daily_ohlc WHERE ticker = 'WDOFUT'"
    df_open = pd.read_sql(query_open, conn)
    df_open['date'] = pd.to_datetime(df_open['date']).dt.date
    
    # 2. Cria a coluna date em df para o merge
    df['date'] = df['ts'].dt.date
    
    # 3. Mergia o open_p
    df = df.merge(df_open, on='date', how='left')
    
    # 4. Calcula os steps harmônicos de cada dia (caching para rapidez)
    unique_dates = df['date'].unique()
    harmonic_steps = {}
    for d in unique_dates:
        harmonic_steps[d] = get_daily_harmonic_step(d)
        
    def calc_dist(row):
        if pd.isna(row['open_p']) or pd.isna(row['price_at_signal']):
            return 10.0 # Valor seguro padrao
        step = harmonic_steps[row['date']]
        open_p = float(row['open_p']) / 10.0 if row['open_p'] > 50000 else float(row['open_p'])
        price_p = float(row['price_at_signal'])
        return get_closest_harmonic_distance(price_p, open_p, step)
        
    df['dist_to_macro_harmonic'] = df.apply(calc_dist, axis=1)
    
    # Limpa as colunas temporárias
    df = df.drop(columns=['date', 'open_p'])
    return df


def build_feature_matrix(df: pd.DataFrame):
    """
    Constrói a matriz de features (X) e os alvos (y) aplicando One-Hot Encoding em
    `signal_type` e extraindo as variáveis contínuas microestruturais.
    """
    # Lista canônica de tipos de sinais para manter dimensionalidade estática no modelo
    canonical_signals = [
        "ABSORCAO_COMPRADORA", "ABSORCAO_VENDEDORA",
        "IMPULSO_COMPRADOR", "IMPULSO_VENDEDOR",
        "DISTRIBUICAO_TOPO", "ACUMULACAO_FUNDO",
        "COMBO_ABSORCAO_IMPULSO_COMPRA", "COMBO_ABSORCAO_IMPULSO_VENDA"
    ]

    # One-Hot Encoding canônico
    for sig in canonical_signals:
        df[f"sig__{sig}"] = (df["signal_type"] == sig).astype(float)

    # Injetando Pilar 2.6 - Sazonalidade (month_week_phase, days_to_rollover, is_payroll_week)
    calendar_feats = df["ts"].apply(get_market_calendar_features).apply(pd.Series)
    df["month_week_phase"] = calendar_feats["month_week_phase"]
    df["days_to_rollover"] = calendar_feats["days_to_rollover"]
    df["is_payroll_week"] = calendar_feats["is_payroll_week"]

    feature_cols = [
        "direction", "cvd_big", "cvd_varejo", "delta_p", "total_qty", "dist_to_macro_harmonic",
        "month_week_phase", "days_to_rollover", "is_payroll_week"
    ] + [f"sig__{sig}" for sig in canonical_signals]

    X = df[feature_cols].copy()
    y = df["target"].values

    # Preencher valores nulos com 0 por segurança
    X.fillna(0.0, inplace=True)

    return X, y, feature_cols


def train_and_evaluate_model(X: pd.DataFrame, y: np.ndarray, feature_names: list, n_splits: int = 5):
    """
    Treina o classificador Random Forest com TimeSeriesSplit para evitar look-ahead bias,
    calculando as métricas de acurácia, precisão, recall e F1 por fold.
    """
    if len(X) < 15:
        print("\n⚠️  [AVISO] Amostra insuficiente (< 15 sinais) para TimeSeriesSplit de 5 dobras.")
        print("   O modelo será treinado em todo o dataset disponível sem validação cruzada.")
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        model = RandomForestClassifier(n_estimators=150, max_depth=6, class_weight="balanced_subsample", random_state=42)
        model.fit(X_scaled, y)
        return model, scaler, {"acc": accuracy_score(y, model.predict(X_scaled)), "f1": f1_score(y, model.predict(X_scaled), zero_division=0)}, None

    # Validação Cruzada Temporal (Sem vazamento de futuro)
    tscv = TimeSeriesSplit(n_splits=min(n_splits, len(X) // 5))
    scaler = StandardScaler()

    metrics_list = []
    fold = 1

    print("\n" + "="*88)
    print(" ⏱️  AVALIAÇÃO EM VALIDAÇÃO CRUZADA TEMPORAL (TIME-SERIES SPLIT OUT-OF-SAMPLE)")
    print("="*88)
    print(f" {'DOBRA (FOLD)':<14} | {'TREINO (AMOSTRAS)':<18} | {'TESTE (AMOSTRAS)':<17} | {'ACURÁCIA':<10} | {'F1-SCORE':<10}")
    print(" " + "-"*86)

    for train_idx, test_idx in tscv.split(X):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]

        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # Treino por dobra (com reponderação dinâmica bootstrap por árvore)
        fold_model = RandomForestClassifier(n_estimators=150, max_depth=6, class_weight="balanced_subsample", random_state=42)
        fold_model.fit(X_train_scaled, y_train)

        y_pred = fold_model.predict(X_test_scaled)
        acc = accuracy_score(y_test, y_pred)
        f1 = f1_score(y_test, y_pred, zero_division=0)
        prec = precision_score(y_test, y_pred, zero_division=0)
        rec = recall_score(y_test, y_pred, zero_division=0)

        metrics_list.append({"fold": fold, "acc": acc, "f1": f1, "prec": prec, "rec": rec})

        acc_str = f"\033[1;32m{acc*100:5.1f}%\033[0m" if acc >= 0.60 else f"\033[1;33m{acc*100:5.1f}%\033[0m"
        f1_str = f"\033[1;36m{f1*100:5.1f}%\033[0m"

        print(f" Fold {fold:<9} | {len(X_train):<18} | {len(X_test):<17} | {acc_str:<19} | {f1_str:<19}")
        fold += 1

    print("="*88)

    # Treinamento do Modelo Definitivo sobre 100% dos dados para persistência e operação ao vivo
    X_full_scaled = scaler.fit_transform(X)
    final_model = RandomForestClassifier(n_estimators=200, max_depth=7, class_weight="balanced_subsample", random_state=42)
    final_model.fit(X_full_scaled, y)

    avg_acc = np.mean([m["acc"] for m in metrics_list])
    avg_f1 = np.mean([m["f1"] for m in metrics_list])

    return final_model, scaler, {"acc": avg_acc, "f1": avg_f1}, metrics_list


def print_feature_importances(model, feature_names: list):
    """Exibe no terminal um ranking em TrueColor Powerline das variáveis mais decisivas."""
    if not hasattr(model, "feature_importances_"):
        return

    importances = model.feature_importances_
    ranking = sorted(zip(feature_names, importances), key=lambda x: x[1], reverse=True)

    print("\n" + "="*88)
    print(" 🌟 RANKING DE IMPORTÂNCIA DAS FEATURES QUANTITATIVAS (FEATURE IMPORTANCE)")
    print("="*88)
    print(f" {'POS':<5} | {'VARIÁVEL / FEATURE MICROESTRUTURAL':<38} | {'RELEVÂNCIA (%)':<16} | {'BARRA DE PESO':<20}")
    print(" " + "-"*86)

    for idx, (feat, imp) in enumerate(ranking, 1):
        pct = imp * 100
        bar_len = int(imp * 40)
        bar_str = "█" * bar_len

        # Destaque de cor
        if idx <= 3:
            color = "\033[1;32m"
        elif idx <= 6:
            color = "\033[1;33m"
        else:
            color = "\033[1;37m"

        feat_clean = feat.replace("sig__", "Tipo: ")
        print(f" {idx:<5} | {color}{feat_clean:<38}\033[0m | {color}{pct:6.2f}%\033[0m          | {color}{bar_str:<20}\033[0m")

    print("="*88 + "\n")


def save_model_artifact(model, scaler, feature_names: list, df_len: int, metrics: dict):
    """Persiste o modelo quantitativo em `models/quant_signals_v1.pkl` e resumo `.json`."""
    os.makedirs(MODELS_DIR, exist_ok=True)

    pkl_path = os.path.join(MODELS_DIR, "quant_signals_v1.pkl")
    json_path = os.path.join(MODELS_DIR, "quant_signals_v1.json")

    payload = {
        "model": model,
        "scaler": scaler,
        "feature_names": feature_names,
        "trained_at": datetime.now().isoformat(),
        "total_samples": df_len,
        "cv_metrics": metrics
    }

    with open(pkl_path, "wb") as f:
        pickle.dump(payload, f)

    meta_json = {
        "model_type": str(type(model).__name__),
        "feature_names": feature_names,
        "trained_at": datetime.now().isoformat(),
        "total_samples": df_len,
        "avg_accuracy_pct": round(metrics.get("acc", 0.0) * 100, 2),
        "avg_f1_score_pct": round(metrics.get("f1", 0.0) * 100, 2),
        "artifact_path": pkl_path
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta_json, f, indent=2, ensure_ascii=False)

    print(f"💾 [PILAR 2 PERSISTÊNCIA] Modelo quantitativo exportado com sucesso!")
    print(f"   📁 Pickle (Pipeline): {pkl_path}")
    print(f"   📄 Metadados (JSON):  {json_path}\n")


def main():
    parser = argparse.ArgumentParser(description="Motor de Re-treinamento Dinâmico de ML (Pilar 2 MLOps).")
    parser.add_argument("--date", help="Filtrar treino por data específica dos sinais YYYY-MM-DD")
    parser.add_argument("--ticker", help="Filtrar treino por ativo específico (ex: WDOQ26)")
    parser.add_argument("--splits", type=int, default=5, help="Número de dobras da Validação Cruzada Temporal (Padrão: 5)")

    args = parser.parse_args()

    print("\n🚀 [MOTOR DE RE-TREINAMENTO DINÂMICO ML] Conectando ao PostgreSQL para ingestão dos sinais rotulados...")

    try:
        with psycopg2.connect(DB_DSN) as conn:
            df = fetch_labeled_dataset(conn, args.date, args.ticker)

        if df.empty:
            print("❌ Nenhum sinal auditado/rotulado encontrado na tabela `signals` para os critérios informados.")
            print("   💡 Dica: Execute primeiro o `daily_postmarket_labeler.py` para gerar o Ground Truth (MFE/MAE/hit_scalp).")
            sys.exit(0)
            
        # Injeta a feature calculada dinamicamente
        print("🔄 Calculando Macro Harmônicos retroativamente para os sinais históricos...")
        df = inject_harmonic_distances(df, conn)

        print(f"📊 [DATASET CARREGADO] {len(df)} sinais quantitativos com Ground Truth prontos para treino.")

        X, y, feature_names = build_feature_matrix(df)
        model, scaler, metrics, _ = train_and_evaluate_model(X, y, feature_names, n_splits=args.splits)

        print_feature_importances(model, feature_names)
        save_model_artifact(model, scaler, feature_names, len(df), metrics)

    except Exception as e:
        print(f"\n❌ Erro crítico durante a execução do Motor de Treinamento ML: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
