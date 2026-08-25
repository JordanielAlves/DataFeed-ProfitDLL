"""
daily_quality_check.py
Auditoria diária de qualidade dos dados após o fechamento do pregão (18h30).
Valida volume de trades, horários de início/fim, ranges de preço, sincroniza
a tabela `daily_ohlc` e calcula o Harmonic Step (Volatilidade 45d) para o próximo pregão.
"""

import sys
import argparse
from datetime import datetime, date, timedelta
import psycopg2
from config import DB_DSN, ASSETS, PREGAO

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from alerts import send_alert
except ImportError:
    send_alert = lambda msg, level="INFO": print(f"[{level}] {msg}")

try:
    from sync_daily_ohlc import sync_daily_ohlc
except ImportError:
    sync_daily_ohlc = None

try:
    from dynamic_harmonics import get_daily_harmonic_step
except ImportError:
    get_daily_harmonic_step = None


def run_check(target_date):
    print(f"Iniciando quality check para {target_date}")
    
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    
    report = [f"📊 Quality Check: {target_date}"]
    critical_issues = 0
    
    for asset_info in ASSETS:
        ticker = asset_info["ticker"] if isinstance(asset_info, dict) else asset_info
        
        # Pega estatisticas basicas
        cur.execute("""
            SELECT count(*), min(price), max(price), min(ts), max(ts)
            FROM trades
            WHERE ticker = %s AND ts::date = %s
        """, (ticker, target_date))
        
        count, pmin, pmax, tmin, tmax = cur.fetchone()
        
        if not count or count == 0:
            report.append(f"❌ {ticker}: SEM DADOS!")
            critical_issues += 1
            continue
            
        # Tratar escala de preco (assumindo WDO/DOL com escala 10 no banco)
        if 'WDO' in ticker or 'DOL' in ticker:
            pmin = float(pmin) / 10.0 if pmin else 0
            pmax = float(pmax) / 10.0 if pmax else 0
            
        tmin_str = tmin.strftime('%H:%M:%S') if tmin else 'N/A'
        tmax_str = tmax.strftime('%H:%M:%S') if tmax else 'N/A'
            
        report.append(f"✅ {ticker}: {count:,} trades | {pmin:.2f} -> {pmax:.2f} | {tmin_str} ate {tmax_str}")
        
    cur.close()
    conn.close()

    # Sincronizar daily_ohlc e calcular próximo passo harmônico
    if sync_daily_ohlc is not None:
        try:
            n_synced = sync_daily_ohlc()
            if get_daily_harmonic_step is not None:
                next_day = datetime.strptime(str(target_date), "%Y-%m-%d").date() + timedelta(days=1)
                # Se cair no sábado/domingo, projeta para segunda
                while next_day.weekday() >= 5:
                    next_day += timedelta(days=1)
                step = get_daily_harmonic_step(next_day)
                report.append(f"🎯 Proximo Harmonic Step ({next_day}): {step:.1f} pts (Volatilidade 45d)")
        except Exception as e:
            report.append(f"⚠️ Erro ao atualizar harmônicos: {e}")
    
    full_report = "\n".join(report)
    print(full_report)
    
    if critical_issues > 0:
        send_alert(full_report, level="CRITICAL")
        sys.exit(1)
    else:
        send_alert(full_report, level="INFO")
        sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Data no formato YYYY-MM-DD")
    args = parser.parse_args()
    
    dt = args.date if args.date else date.today().isoformat()
    run_check(dt)
