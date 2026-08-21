import psycopg2
from config import DB_DSN, ASSETS, PREGAO
from datetime import datetime, date
import sys
import argparse

try:
    from alerts import send_alert
except ImportError:
    send_alert = lambda msg, level="INFO": print(f"[{level}] {msg}")

def run_check(target_date):
    print(f"Iniciando quality check para {target_date}")
    
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    
    report = [f"📊 Quality Check: {target_date}"]
    critical_issues = 0
    
    for ticker in ASSETS:
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
            
        report.append(f"✅ {ticker}: {count} trades | {pmin} -> {pmax} | {tmin.strftime('%H:%M:%S')} até {tmax.strftime('%H:%M:%S')}")
        
    cur.close()
    conn.close()
    
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
