import psycopg2
from config import DB_DSN

with psycopg2.connect(DB_DSN) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ticker, date FROM agent_daily ORDER BY date DESC, ticker")
        print("TICKERS E DATAS EM AGENT_DAILY:")
        for row in cur.fetchall():
            print(" ", row)
