#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
===================================================================================
PROFITDLL / DATAFEED - PILAR 1: ETIQUETADOR AUTOMÁTICO PÓS-PREGÃO
===================================================================================
Arquivo: daily_postmarket_labeler.py
Descrição: Motor de retroalimentação automática (Automated Ground Truth Labeler).
           Lê os sinais registrados na tabela `signals` do PostgreSQL, simula a passagem
           do tempo segundo a segundo/tick a tick na tabela `trades` nas janelas de
           1m, 3m e 5m seguintes ao disparo, calculando:
             - MFE (Maximum Favorable Excursion) em pontos reais da B3
             - MAE (Maximum Adverse Excursion) em pontos reais da B3
             - hit_scalp_2_5 (Se atingiu o alvo de Gain antes do Stop)
             - outcome_pts (Resultado líquido no fechamento da janela de 3m)
===================================================================================
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

# Blindagem de Encoding para Terminal Windows (evita UnicodeEncodeError em emojis/Powerline)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Configuração Padrão do Banco de Dados
DB_DSN = os.getenv("PROFIT_DB_DSN", "dbname=fluxo_ordens user=postgres password=postgres host=localhost")


def ensure_table_columns(conn):
    """Garante que a tabela `signals` possui todas as colunas de auditoria forense do Pilar 1."""
    ddl_statements = [
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS mfe_1m NUMERIC(10, 2);",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS mae_1m NUMERIC(10, 2);",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS mfe_3m NUMERIC(10, 2);",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS mae_3m NUMERIC(10, 2);",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS mfe_5m NUMERIC(10, 2);",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS mae_5m NUMERIC(10, 2);",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS hit_scalp_2_5 BOOLEAN;",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS labeled_at TIMESTAMPTZ;"
    ]
    with conn.cursor() as cur:
        for ddl in ddl_statements:
            cur.execute(ddl)
    conn.commit()


def get_scale_factor(ticker: str) -> float:
    """Retorna o fator de escala de preço para o ativo (Regra 1 AGENTS.md)."""
    if ticker.startswith("WDO") or ticker.startswith("DOL"):
        return 10.0
    elif ticker.startswith("WIN") or ticker.startswith("IND"):
        return 1.0
    return 1.0


def calculate_window_metrics(trades: list, price_signal: float, direction: int, scale: float, gain_pts: float, stop_pts: float):
    """
    Calcula MFE, MAE e hit_scalp para as janelas de tempo de 1m, 3m e 5m a partir de uma lista
    ordenada de trades (por timestamp ts).
    """
    if not trades:
        return {
            "mfe_1m": 0.0, "mae_1m": 0.0,
            "mfe_3m": 0.0, "mae_3m": 0.0,
            "mfe_5m": 0.0, "mae_5m": 0.0,
            "hit_scalp": False, "outcome_pts": 0.0
        }

    t0 = trades[0]["ts"]
    
    # Limites em escala do banco
    gain_limit = price_signal + (gain_pts * scale) if direction == 1 else price_signal - (gain_pts * scale)
    stop_limit = price_signal - (stop_pts * scale) if direction == 1 else price_signal + (stop_pts * scale)

    mfe_1m, mae_1m = 0.0, 0.0
    mfe_3m, mae_3m = 0.0, 0.0
    mfe_5m, mae_5m = 0.0, 0.0
    
    hit_scalp = False
    scalp_decided = False
    
    last_price_3m = price_signal

    for t in trades:
        p = float(t["price"])
        dt_seconds = (t["ts"] - t0).total_seconds()

        # Cálculo de excursão no momento do trade
        if direction == 1:
            favorable = p - price_signal
            adverse = price_signal - p
        else:
            favorable = price_signal - p
            adverse = p - price_signal

        # Janela de 1 Minuto (<= 60s)
        if dt_seconds <= 60:
            if favorable > mfe_1m: mfe_1m = favorable
            if adverse > mae_1m: mae_1m = adverse

        # Janela de 3 Minutos (<= 180s)
        if dt_seconds <= 180:
            if favorable > mfe_3m: mfe_3m = favorable
            if adverse > mae_3m: mae_3m = adverse
            last_price_3m = p

            # Decisão de Scalping na janela de 3 minutos
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

        # Janela de 5 Minutos (<= 300s)
        if dt_seconds <= 300:
            if favorable > mfe_5m: mfe_5m = favorable
            if adverse > mae_5m: mae_5m = adverse

    # Variação no fechamento exato dos 3 minutos
    outcome_pts = (last_price_3m - price_signal) / scale if direction == 1 else (price_signal - last_price_3m) / scale

    return {
        "mfe_1m": round(mfe_1m / scale, 2),
        "mae_1m": round(mae_1m / scale, 2),
        "mfe_3m": round(mfe_3m / scale, 2),
        "mae_3m": round(mae_3m / scale, 2),
        "mfe_5m": round(mfe_5m / scale, 2),
        "mae_5m": round(mae_5m / scale, 2),
        "hit_scalp": hit_scalp,
        "outcome_pts": round(outcome_pts, 2)
    }


def label_signals_for_date(conn, date_str: str, ticker: str = None, gain_pts: float = 2.5, stop_pts: float = 2.0, recalculate: bool = False):
    """Lê os sinais pendentes no dia informado, consulta o fluxo de trades e popula os desfechos no banco."""
    ensure_table_columns(conn)

    start_day = f"{date_str} 00:00:00"
    end_day = f"{date_str} 23:59:59"

    where_clause = "ts >= %s::timestamp AND ts <= %s::timestamp AND signal_type != 'NEUTRAL'"
    params = [start_day, end_day]

    if ticker:
        where_clause += " AND ticker = %s"
        params.append(ticker)
    if not recalculate:
        where_clause += " AND labeled_at IS NULL"

    query_signals = f"""
        SELECT id, ticker, ts, signal_type, direction, price_at_signal
        FROM signals
        WHERE {where_clause}
        ORDER BY ts ASC
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query_signals, params)
        signals = cur.fetchall()

    if not signals:
        print(f"\n[OK] Nenhum sinal pendente de etiquetagem para a data {date_str} (Ticker: {ticker or 'TODOS'}).")
        return []

    print(f"\n🚀 [ETIQUETADOR PÓS-PREGÃO] Processando {len(signals)} sinais na data {date_str}...")

    labeled_count = 0
    results_summary = []

    for sig in signals:
        sig_id = sig["id"]
        tck = sig["ticker"]
        ts_sig = sig["ts"]
        # Remover timezone se houver para consulta limpa no PostgreSQL
        if hasattr(ts_sig, "tzinfo") and ts_sig.tzinfo is not None:
            ts_sig = ts_sig.replace(tzinfo=None)

        direction = int(sig["direction"] or 0)
        price_sig = float(sig["price_at_signal"])
        scale = get_scale_factor(tck)

        if direction == 0:
            continue

        # Consultar os trades nos 5 minutos seguintes ao sinal
        end_window = ts_sig + timedelta(minutes=5)
        query_trades = """
            SELECT ts, price
            FROM trades
            WHERE ticker = %s AND ts >= %s::timestamp AND ts <= %s::timestamp
            ORDER BY ts ASC
        """
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query_trades, (tck, ts_sig, end_window))
            trades = cur.fetchall()

        metrics = calculate_window_metrics(trades, price_sig, direction, scale, gain_pts, stop_pts)

        update_query = """
            UPDATE signals
            SET mfe_1m = %s, mae_1m = %s,
                mfe_3m = %s, mae_3m = %s,
                mfe_5m = %s, mae_5m = %s,
                hit_scalp_2_5 = %s,
                outcome_pts = %s,
                outcome_window = 3,
                labeled_at = NOW()
            WHERE id = %s
        """
        with conn.cursor() as cur:
            cur.execute(update_query, (
                metrics["mfe_1m"], metrics["mae_1m"],
                metrics["mfe_3m"], metrics["mae_3m"],
                metrics["mfe_5m"], metrics["mae_5m"],
                metrics["hit_scalp"],
                metrics["outcome_pts"],
                sig_id
            ))
        
        labeled_count += 1
        results_summary.append({
            "ticker": tck,
            "signal_type": sig["signal_type"],
            "direction": direction,
            **metrics
        })

    conn.commit()
    print(f"✅ Sucesso! {labeled_count} sinais etiquetados e gravados no banco com MFE/MAE.")
    return results_summary


def print_powerline_summary(results: list, date_str: str, gain_pts: float, stop_pts: float):
    """Exibe no terminal um resumo executivo Powerline das estatísticas forenses do dia."""
    if not results:
        return

    print("\n" + "="*85)
    print(f" 🏆 RESUMO EXECUTIVO DO PILAR 1 — AUDITORIA FORENSE DE SINAIS ({date_str})")
    print(f" ⚙️  Parâmetros de Scalping: Gain +{gain_pts:.1f} pts | Stop -{stop_pts:.1f} pts (Janela 3m)")
    print("="*85)

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

    # Imprimir tabela formatada
    print(f" {'TIPO DO ALERTA (SIGNAL_TYPE)':<32} | {'SINAIS':<6} | {'TAXA WIN':<10} | {'MFE 3M MED':<11} | {'MAE 3M MED':<11} | {'RETORNO MED':<11}")
    print(" " + "-"*92)

    for st, d in stats.items():
        cnt = d["count"]
        win_rate = (d["wins"] / cnt) * 100 if cnt > 0 else 0.0
        avg_mfe = d["mfe_3m_sum"] / cnt
        avg_mae = d["mae_3m_sum"] / cnt
        avg_out = d["outcome_sum"] / cnt

        # Destaque de cores para Win Rate
        if win_rate >= 80.0:
            win_str = f"\033[1;32m{win_rate:6.1f}%\033[0m"
        elif win_rate >= 60.0:
            win_str = f"\033[1;33m{win_rate:6.1f}%\033[0m"
        else:
            win_str = f"\033[1;31m{win_rate:6.1f}%\033[0m"

        out_str = f"\033[1;32m{avg_out:+6.2f} pts\033[0m" if avg_out >= 0 else f"\033[1;31m{avg_out:+6.2f} pts\033[0m"

        print(f" {st:<32} | {cnt:<6} | {win_str:<19} | {avg_mfe:11.2f} | {avg_mae:11.2f} | {out_str:<20}")

    print("="*85 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Etiquetador Automático de Sinais Pós-Pregão (Pilar 1 MLOps).")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="Data dos sinais YYYY-MM-DD (Padrão: hoje)")
    parser.add_argument("--ticker", help="Ativo específico para auditar (ex: WDOQ26)")
    parser.add_argument("--gain", type=float, default=2.5, help="Pontos de Gain para scalper (Padrão: 2.5)")
    parser.add_argument("--stop", type=float, default=2.0, help="Pontos de Stop para scalper (Padrão: 2.0)")
    parser.add_argument("--recalculate", action="store_true", help="Recalcular mesmo os sinais que já possuem MFE/MAE salvo")

    args = parser.parse_args()

    try:
        with psycopg2.connect(DB_DSN) as conn:
            results = label_signals_for_date(conn, args.date, args.ticker, args.gain, args.stop, args.recalculate)
            print_powerline_summary(results, args.date, args.gain, args.stop)
    except Exception as e:
        print(f"\n❌ Erro durante a execução do etiquetador: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
