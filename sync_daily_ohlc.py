"""
sync_daily_ohlc.py
Sincroniza e atualiza diariamente a tabela `daily_ohlc` no PostgreSQL
a partir dos trades registrados na tabela `trades`.
Garante a alimentação contínua para cálculo dinâmico de harmônicos (WDOFUT).
"""

import sys
import logging
from datetime import date, datetime, timedelta
import psycopg2
from config import DB_DSN

log = logging.getLogger("sync_ohlc")


def normalize_price_pts(price_raw: float) -> float:
    """
    Normaliza o preço para pontos reais da B3 (faixa ~4.000 a 7.000 para Dólar).
    Lida com variações de escala históricas (1x, 10x ou 100x no DB).
    """
    if price_raw is None or price_raw == 0:
        return 0.0
    p = float(price_raw)
    if 4000.0 <= p <= 7500.0:
        return round(p, 2)
    elif 40000.0 <= p <= 75000.0:
        return round(p / 10.0, 2)
    elif 400000.0 <= p <= 750000.0:
        return round(p / 100.0, 2)
    elif 400.0 <= p <= 750.0:
        return round(p * 10.0, 2)
    return round(p, 2)


def sync_daily_ohlc(target_date: date = None) -> int:
    """
    Sincroniza as barras diárias de WDOFUT na tabela daily_ohlc.
    Se target_date for informado, sincroniza apenas esse dia.
    Caso contrário, verifica todos os dias pendentes a partir da última data em daily_ohlc.
    """
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    if target_date is not None:
        if isinstance(target_date, str):
            target_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        dates_to_sync = [target_date]
    else:
        cur.execute("SELECT MAX(date) FROM daily_ohlc WHERE ticker = 'WDOFUT'")
        last_date = cur.fetchone()[0]
        if last_date is None:
            last_date = date(2005, 1, 1)
        
        log.info(f"Última data em daily_ohlc: {last_date}")

        cur.execute("""
            SELECT DISTINCT ts::date 
            FROM trades 
            WHERE ticker LIKE 'WDO%%' AND ts::date >= %s
            ORDER BY ts::date ASC;
        """, (last_date,))
        dates_to_sync = [r[0] for r in cur.fetchall()]

    if not dates_to_sync:
        log.info("Nenhuma nova data para sincronizar em daily_ohlc.")
        cur.close()
        conn.close()
        return 0

    log.info(f"Processando {len(dates_to_sync)} dias para sincronização em daily_ohlc...")
    records = []

    for d in dates_to_sync:
        if isinstance(d, str):
            d = datetime.strptime(d, "%Y-%m-%d").date()
        d_start = datetime.combine(d, datetime.min.time())
        d_end = datetime.combine(d, datetime.max.time())

        cur.execute("""
            SELECT MIN(price), MAX(price), COUNT(*)
            FROM trades
            WHERE ticker LIKE 'WDO%%' AND ts >= %s AND ts <= %s;
        """, (d_start, d_end))
        row = cur.fetchone()
        if not row or row[0] is None or row[2] == 0:
            continue

        raw_min, raw_max, trade_count = row
        low_p = normalize_price_pts(raw_min)
        high_p = normalize_price_pts(raw_max)

        cur.execute("""
            SELECT price FROM trades
            WHERE ticker LIKE 'WDO%%' AND ts >= %s AND ts <= %s
            ORDER BY ts ASC LIMIT 1;
        """, (d_start, d_end))
        open_raw = cur.fetchone()[0]
        open_p = normalize_price_pts(open_raw)

        cur.execute("""
            SELECT price FROM trades
            WHERE ticker LIKE 'WDO%%' AND ts >= %s AND ts <= %s
            ORDER BY ts DESC LIMIT 1;
        """, (d_start, d_end))
        close_raw = cur.fetchone()[0]
        close_p = normalize_price_pts(close_raw)

        if high_p < low_p:
            high_p, low_p = low_p, high_p

        records.append((d, 'WDOFUT', open_p, high_p, low_p, close_p))
        log.info(f"  {d} -> Open: {open_p:.2f} | High: {high_p:.2f} | Low: {low_p:.2f} | Close: {close_p:.2f} | Amp: {(high_p - low_p):.2f} pts ({trade_count:,} trades)")

    if records:
        insert_query = """
            INSERT INTO daily_ohlc (date, ticker, open_p, high_p, low_p, close_p)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (date) DO UPDATE 
            SET open_p = EXCLUDED.open_p,
                high_p = EXCLUDED.high_p,
                low_p = EXCLUDED.low_p,
                close_p = EXCLUDED.close_p;
        """
        cur.executemany(insert_query, records)
        conn.commit()
        log.info(f"✅ Sucesso: {len(records)} registros atualizados em daily_ohlc.")

    cur.close()
    conn.close()
    return len(records)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        sync_daily_ohlc(target)
    else:
        sync_daily_ohlc()
