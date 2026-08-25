"""
backtest_engine.py
Motor de Backtesting Forense e Simulação de Execução Out-of-Sample de Alta Performance.
Simula a execução financeira realista com custos B3, slippage e gestão de risco.
"""

import sys
import json
import argparse
import pickle
import psycopg2
from psycopg2.extras import RealDictCursor
import numpy as np
import pandas as pd
from config import DB_DSN
from price_utils import to_real_points, format_price_b3
from market_calendar import get_market_calendar_features
from dynamic_harmonics import get_daily_harmonic_step, get_closest_harmonic_distance

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run_backtest(model_path: str = "models/quant_signals_v1.pkl", min_conviction: float = 30.0, contracts: int = 1, cost_per_trade_brl: float = 1.20, slippage_pts: float = 0.5):
    print("\n" + "="*88)
    print(" 🚀 MOTOR DE BACKTESTING FORENSE — EXECUÇÃO OUT-OF-SAMPLE B3")
    print(f" ⚙️  Contratos: {contracts} WDO | Custo B3: R$ {cost_per_trade_brl:.2f} | Slippage: {slippage_pts:.1f} pt | Min ML: {min_conviction:.1f}%")
    print("="*88)

    # 1. Carregar Modelo ML
    try:
        with open(model_path, "rb") as f:
            payload = pickle.load(f)
        model = payload["model"]
        scaler = payload["scaler"]
        feature_names = payload["feature_names"]
        optimal_th = payload.get("optimal_threshold", 0.25)
        print(f"🤖 Modelo ML carregado ({len(feature_names)} features | Threshold de Treino: {optimal_th*100:.1f}%).")
    except Exception as e:
        print(f"❌ Erro ao carregar modelo ML em {model_path}: {e}")
        return

    # 2. Carregar Sinais Rotulados
    with psycopg2.connect(DB_DSN) as conn:
        query = """
            SELECT id, ts, ticker, signal_type, direction, price_at_signal, context,
                   mfe_3m, mae_3m, hit_scalp_2_5, outcome_pts
            FROM signals
            WHERE labeled_at IS NOT NULL AND hit_scalp_2_5 IS NOT NULL AND signal_type != 'NEUTRAL'
            ORDER BY ts ASC;
        """
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            rows = cur.fetchall()

        cur_ohlc = conn.cursor()
        cur_ohlc.execute("SELECT date, open_p FROM daily_ohlc WHERE ticker = 'WDOFUT'")
        open_map = {r[0]: float(r[1]) for r in cur_ohlc.fetchall()}
        cur_ohlc.close()

    if not rows:
        print("❌ Nenhum dado etiquetado encontrado para backtest.")
        return

    print(f"📊 Avaliando {len(rows):,} sinais históricos com busca otimizada...")

    unique_dates = set(r["ts"].date() for r in rows)
    harmonic_steps = {d: get_daily_harmonic_step(d, auto_sync=False) for d in unique_dates}

    records_for_df = []
    meta_records = []

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

        row_dict = {
            "direction": int(r["direction"] or 0),
            "cvd_big": float(ctx.get("cvd_big", 0)),
            "cvd_varejo": float(ctx.get("cvd_varejo", 0)),
            "delta_p": float(ctx.get("delta_p", 0.0)),
            "total_qty": float(ctx.get("total_qty", 0)),
            "dist_to_macro_harmonic": dist_harmonic,
            "month_week_phase": cal_feat.get("month_week_phase", 2),
            "days_to_rollover": cal_feat.get("days_to_rollover", 15),
            "is_payroll_week": cal_feat.get("is_payroll_week", 0),
        }

        for fname in feature_names:
            if fname.startswith("sig__"):
                sig_name = fname.replace("sig__", "")
                row_dict[fname] = 1.0 if r["signal_type"] == sig_name else 0.0
            elif fname not in row_dict:
                row_dict[fname] = 0.0

        records_for_df.append(row_dict)
        meta_records.append({
            "id": r["id"],
            "ts": r["ts"],
            "ticker": tck,
            "signal_type": r["signal_type"],
            "direction": r["direction"],
            "price": price_real,
            "hit_scalp": bool(r["hit_scalp_2_5"]),
            "outcome_pts": float(r["outcome_pts"] or 0.0)
        })

    # Predição em batch no Scikit-Learn (milissegundos)
    X_mat = pd.DataFrame(records_for_df)[feature_names]
    X_sc = scaler.transform(X_mat) if scaler else X_mat
    probs = model.predict_proba(X_sc)[:, 1] * 100.0

    trades_simulated = []
    for meta, prob in zip(meta_records, probs):
        if prob >= min_conviction:
            hit = meta["hit_scalp"]
            pts_brutos = (2.5 - slippage_pts) if hit else (-2.0 - slippage_pts)
            financeiro_bruto = pts_brutos * 10.0 * contracts
            financeiro_liquido = financeiro_bruto - (cost_per_trade_brl * contracts)

            trades_simulated.append({
                "id": meta["id"],
                "ts": meta["ts"],
                "ticker": meta["ticker"],
                "signal_type": meta["signal_type"],
                "direction": meta["direction"],
                "price": meta["price"],
                "prob_ml": prob,
                "hit": hit,
                "pts": pts_brutos,
                "pnl_brl": financeiro_liquido
            })

    if not trades_simulated:
        print(f"⚠️ Nenhum trade atingiu o filtro de convicção mínima de {min_conviction}%.")
        return

    df_trades = pd.DataFrame(trades_simulated)
    total_ops = len(df_trades)
    wins = df_trades["hit"].sum()
    losses = total_ops - wins
    win_rate = (wins / total_ops) * 100.0

    pnl_total = df_trades["pnl_brl"].sum()
    pts_total = df_trades["pts"].sum()

    df_trades["cum_pnl"] = df_trades["pnl_brl"].cumsum()
    df_trades["peak"] = df_trades["cum_pnl"].cummax()
    df_trades["drawdown"] = df_trades["cum_pnl"] - df_trades["peak"]
    max_dd = df_trades["drawdown"].min()

    gains_total = df_trades[df_trades["pnl_brl"] > 0]["pnl_brl"].sum()
    losses_total = abs(df_trades[df_trades["pnl_brl"] < 0]["pnl_brl"].sum())
    profit_factor = (gains_total / losses_total) if losses_total > 0 else 999.0

    avg_win = df_trades[df_trades["hit"]]["pts"].mean() if wins > 0 else 0.0
    avg_loss = abs(df_trades[~df_trades["hit"]]["pts"].mean()) if losses > 0 else 0.0
    payoff = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    print("\n" + "="*88)
    print(" 🏆 RESULTADO CONSOLIDADO DO BACKTEST FORENSE (OUT-OF-SAMPLE)")
    print("="*88)
    print(f" 📈 Total de Operações Filtradas   : {total_ops:,} (de {len(rows):,} sinais avaliados)")
    print(f" 🎯 Taxa de Acerto (Win Rate)      : {win_rate:.1f}% ({wins:,} V / {losses:,} D)")
    print(f" 💰 Retorno Líquido Total          : R$ {pnl_total:+,.2f} ({pts_total:+.1f} pontos)")
    print(f" ⚖️  Profit Factor (Fator de Lucro) : {profit_factor:.2f}")
    print(f" 📊 Payoff Ratio (Ganho/Perda)     : {payoff:.2f} (Gain Líquido: {avg_win:+.1f} pts | Loss: -{avg_loss:.1f} pts)")
    print(f" 🛡️ Drawdown Máximo                : R$ {max_dd:,.2f} ({max_dd/(10*contracts):.1f} pts)")
    print("="*88 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Motor de Backtesting Forense.")
    parser.add_argument("--conviction", type=float, default=30.0, help="Convicção mínima do ML (0-100%)")
    parser.add_argument("--contracts", type=int, default=1, help="Quantidade de contratos WDO")
    parser.add_argument("--slippage", type=float, default=0.5, help="Slippage estimado em pontos")
    args = parser.parse_args()

    run_backtest(min_conviction=args.conviction, contracts=args.contracts, slippage_pts=args.slippage)
