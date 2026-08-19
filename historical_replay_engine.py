import sys
import argparse
from datetime import date, datetime, timedelta
import psycopg2
from config import DB_DSN
from ml_live_predictor import MLLivePredictor

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def run_replay(start_date: date, end_date: date, interval_seconds: int = 10, window_minutes: int = 5):
    print("\n" + "="*80)
    print(" ⏳ MÁQUINA DO TEMPO: HISTORICAL REPLAY ENGINE")
    print("="*80)
    
    predictor = MLLivePredictor()
    
    # Descobrir quais tickers temos no banco para as datas alvo
    with psycopg2.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT DATE(ts), ticker 
                FROM trades 
                WHERE ts >= %s AND ts < %s + interval '1 day'
                  AND (ticker LIKE 'WDO%%' OR ticker LIKE 'DOL%%')
                ORDER BY DATE(ts) ASC
            """, (start_date, end_date))
            available_days = {}
            for d, t in cur.fetchall():
                if d not in available_days:
                    available_days[d] = []
                available_days[d].append(t)
                
    if not available_days:
        print("❌ Nenhum dado encontrado no período para replay.")
        return

    total_days = len(available_days)
    print(f"✅ Encontrados {total_days} dias de pregão para simulação.")

    # Loop de Replay
    for i, (day, tickers) in enumerate(available_days.items(), 1):
        print(f"\n[REPLAY {i}/{total_days}] Simulando pregão do dia {day.strftime('%d/%m/%Y')}...")
        
        # Simula das 09:00:00 até 18:00:00
        current_ts = datetime.combine(day, datetime.min.time()).replace(hour=9, minute=0, second=0)
        end_ts = datetime.combine(day, datetime.min.time()).replace(hour=18, minute=0, second=0)
        
        while current_ts <= end_ts:
            for ticker in tickers:
                if ticker.startswith("WDO") and len(ticker) == 6: # Focar no WDO da letra (ex WDOJ26)
                    # Silenciar print nativo redirecionando stdout ou apenas aceitando
                    try:
                        trade_data, top_agents, session_id = predictor.analisar_janela_atual(ticker, window_minutes, current_ts)
                        # Só processa se houver trades na janela para economizar tempo
                        if trade_data and trade_data.get("n_trades") and trade_data["n_trades"] > 0:
                            predictor.avaliar_e_disparar_sinais(ticker, trade_data, top_agents, session_id, current_ts)
                    except Exception as e:
                        pass
                        
            current_ts += timedelta(seconds=interval_seconds)

    print("\n✅ REPLAY HISTÓRICO CONCLUÍDO! Sinais gerados no banco de dados.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", type=str, required=True, help="Data inicial YYYY-MM-DD")
    parser.add_argument("--fim", type=str, required=True, help="Data final YYYY-MM-DD")
    args = parser.parse_args()
    
    s = datetime.strptime(args.inicio, "%Y-%m-%d").date()
    e = datetime.strptime(args.fim, "%Y-%m-%d").date()
    run_replay(s, e)
