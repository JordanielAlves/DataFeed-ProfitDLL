import psycopg2
from config import DB_DSN

def check_last_trade():
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        
        cur.execute("SELECT MAX(ts) FROM trades")
        last_trade = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM signals")
        total_signals = cur.fetchone()[0]
        
        print(f"Último pregão: {last_trade.date() if last_trade else 'Nenhum'}")
        print(f"Total sinais: {total_signals}")
        
        conn.close()
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    check_last_trade()
