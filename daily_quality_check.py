"""
daily_quality_check.py
Pipeline Diário de Encerramento e Auditoria Pós-Pregão (18h30).
Executa de forma 100% automatizada:
  1. Auditoria de integridade dos trades e cotações B3 (formato 5.165,00)
  2. Sincronização automática da barra OHLC diária no PostgreSQL (WDOFUT)
  3. Auditoria forense dos sinais disparados no dia (MFE/MAE/Taxa de Acerto)
  4. Posição acumulada no contrato dos maiores players institucionais (corretoras.py)
  5. Cálculo do Harmonic Step calibrado para o pregão seguinte
  6. Disparo do Briefing Executivo consolidado para o Telegram do operador
"""

import sys
import time
import argparse
from datetime import datetime, date, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from config import DB_DSN, ASSETS
from price_utils import to_real_points, format_price_b3
from corretoras import get_corretora_label

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from alerts import send_alert, start_alert_worker, stop_alert_worker
except ImportError:
    send_alert = lambda msg, level="INFO": print(f"[{level}] {msg}")
    start_alert_worker = lambda: None
    stop_alert_worker = lambda: None

try:
    from sync_daily_ohlc import sync_daily_ohlc
except ImportError:
    sync_daily_ohlc = None

try:
    from dynamic_harmonics import get_daily_harmonic_step
except ImportError:
    get_daily_harmonic_step = None

try:
    from daily_postmarket_labeler import run_labeler_fast
except ImportError:
    run_labeler_fast = None


def run_pipeline(target_date: str):
    print(f"\n🚀 [PIPELINE PÓS-PREGÃO] Iniciando rotina de encerramento para {target_date}...")
    start_alert_worker()

    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    report_lines = [
        f"📊 <b>BRIEFING DE FECHAMENTO — {target_date}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "📈 <b>QUALIDADE DA COLETA:</b>"
    ]
    critical_issues = 0

    # 1. Auditoria dos Ativos Coletados
    for asset_info in ASSETS:
        ticker = asset_info["ticker"] if isinstance(asset_info, dict) else asset_info

        cur.execute("""
            SELECT count(*) AS total_trades, 
                   min(price) AS min_price, 
                   max(price) AS max_price, 
                   min(ts) AS min_ts, 
                   max(ts) AS max_ts
            FROM trades
            WHERE ticker = %s AND ts::date = %s
        """, (ticker, target_date))

        row = cur.fetchone()
        count = row["total_trades"]
        pmin = row["min_price"]
        pmax = row["max_price"]
        tmin = row["min_ts"]
        tmax = row["max_ts"]

        if not count or count == 0:
            report_lines.append(f"❌ <code>{ticker}</code>: SEM DADOS NO PREGÃO!")
            critical_issues += 1
            continue

        pmin_str = format_price_b3(pmin, ticker)
        pmax_str = format_price_b3(pmax, ticker)
        tmin_str = tmin.strftime('%H:%M:%S') if tmin else 'N/A'
        tmax_str = tmax.strftime('%H:%M:%S') if tmax else 'N/A'

        report_lines.append(f"✅ <code>{ticker}</code>: {count:,} trades | {pmin_str} ➔ {pmax_str} ({tmin_str} às {tmax_str})")

    # 2. Sincronização de OHLC Diário
    report_lines.append("\n🕯️ <b>BARRAS DIÁRIAS (OHLC):</b>")
    if sync_daily_ohlc is not None:
        try:
            n_synced = sync_daily_ohlc(target_date)
            report_lines.append(f"✅ Tabela <code>daily_ohlc</code> sincronizada com sucesso ({n_synced} barras).")
        except Exception as e:
            report_lines.append(f"⚠️ Falha ao sincronizar OHLC: {e}")

    # 3. Etiquetagem Forense dos Sinais do Dia
    report_lines.append("\n🎯 <b>DESEMPENHO DOS SINAIS DO PREGÃO:</b>")
    if run_labeler_fast is not None:
        try:
            results = run_labeler_fast(conn, date_filter=target_date, recalculate=True)
            if results:
                total_sigs = len(results)
                wins = sum(1 for r in results if r["hit_scalp"])
                win_rate = (wins / total_sigs) * 100.0
                report_lines.append(f"🎯 Total: {total_sigs} alertas | Taxa Win: <b>{win_rate:.1f}%</b> ({wins} V / {total_sigs-wins} D)")
            else:
                report_lines.append("ℹ️ Nenhum alerta disparado neste pregão.")
        except Exception as e:
            report_lines.append(f"⚠️ Erro ao auditar sinais: {e}")

    # 4. Posição Acumulada dos Maiores Players no Contrato WDO
    cur.execute("""
        SELECT ticker 
        FROM trades 
        WHERE (ticker LIKE 'WDO%%' OR ticker LIKE 'DOL%%') AND ts::date = %s 
        LIMIT 1
    """, (target_date,))
    wdo_row = cur.fetchone()
    wdo_ticker = wdo_row["ticker"] if wdo_row else "WDOU26"

    cur.execute("""
        SELECT agent_id, SUM(buy_qty - sell_qty) as saldo
        FROM agent_daily
        WHERE ticker = %s
        GROUP BY agent_id
        HAVING SUM(buy_qty - sell_qty) != 0
        ORDER BY saldo DESC;
    """, (wdo_ticker,))
    agent_pos = cur.fetchall()

    if agent_pos:
        report_lines.append(f"\n🏦 <b>POSIÇÃO ACUMULADA NO CONTRATO ({wdo_ticker}):</b>")
        top_buyers = [p for p in agent_pos if p["saldo"] > 0][:3]
        top_sellers = [p for p in reversed(agent_pos) if p["saldo"] < 0][:3]

        if top_buyers:
            compradores_str = ", ".join([f"{get_corretora_label(b['agent_id'])} (+{b['saldo']:,})" for b in top_buyers])
            report_lines.append(f"🟢 <b>Maiores Comprados:</b> {compradores_str}")
        if top_sellers:
            vendedores_str = ", ".join([f"{get_corretora_label(s['agent_id'])} ({s['saldo']:,})" for s in top_sellers])
            report_lines.append(f"🔴 <b>Maiores Vendidos:</b>  {vendedores_str}")

    # 5. Próximo Passo Harmônico
    if get_daily_harmonic_step is not None:
        try:
            next_day = datetime.strptime(str(target_date), "%Y-%m-%d").date() + timedelta(days=1)
            while next_day.weekday() >= 5:  # Pular fim de semana
                next_day += timedelta(days=1)
            step = get_daily_harmonic_step(next_day, auto_sync=False)
            report_lines.append(f"\n📐 <b>PRÓXIMO HARMÔNICO ({next_day.strftime('%d/%m/%Y')}):</b> <b>{step:.1f} pts</b> (Volatilidade 45d)")
        except Exception as e:
            report_lines.append(f"\n⚠️ Falha no cálculo harmônico: {e}")

    report_lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    cur.close()
    conn.close()

    full_report = "\n".join(report_lines)
    print("\n" + full_report + "\n")

    # 6. Disparo via Telegram
    level = "CRITICAL" if critical_issues > 0 else "INFO"
    send_alert(full_report, level=level)

    # Aguardar 3 segundos para garantir envio da fila assíncrona do Telegram
    time.sleep(3)
    stop_alert_worker()

    if critical_issues > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline de Encerramento Pós-Pregão.")
    parser.add_argument("--date", help="Data no formato YYYY-MM-DD (Padrão: hoje)")
    args = parser.parse_args()

    dt = args.date if args.date else date.today().isoformat()
    run_pipeline(dt)
