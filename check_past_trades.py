import psycopg2
from config import DB_DSN

with psycopg2.connect(DB_DSN) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, COUNT(*), MIN(ts), MAX(ts) FROM trades GROUP BY ticker")
        print("CONTAGEM DE TRADES NO BANCO (POR TICKER):")
        for row in cur.fetchall():
            print(" ", row)
