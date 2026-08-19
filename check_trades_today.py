import psycopg2
from config import DB_DSN

with psycopg2.connect(DB_DSN) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, COUNT(*), MIN(ts), MAX(ts) FROM trades WHERE ts >= '2026-07-14' GROUP BY ticker")
        rows = cur.fetchall()
        print("TRADES DE HOJE 2026-07-14:")
        if not rows:
            print("  Nenhum trade gravado hoje na tabela trades!")
        for r in rows:
            print(" ", r)
            
        cur.execute("SELECT * FROM sessions WHERE date = '2026-07-14'")
        print("SESSIONS DE HOJE 2026-07-14:")
        for r in cur.fetchall():
            print(" ", r)
