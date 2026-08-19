import json
import psycopg2
from config import DB_DSN
from dynamic_harmonics import get_daily_harmonic_step, get_closest_harmonic_distance
from psycopg2.extras import RealDictCursor

def run():
    print("Atualizando histórico de sinais com a nova feature dist_to_macro_harmonic...")
    conn = psycopg2.connect(DB_DSN)
    
    # Obter aberturas
    with conn.cursor() as cur:
        cur.execute("SELECT date, open_p FROM daily_ohlc WHERE ticker = 'WDOFUT'")
        rows = cur.fetchall()
        open_prices = {str(r[0]): r[1] for r in rows}
        
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, ts, price_at_signal, context FROM signals WHERE signal_type != 'NEUTRAL'")
        signals = cur.fetchall()
        
    print(f"Lidos {len(signals)} sinais históricos.")
    
    updates = []
    
    for s in signals:
        date_str = s['ts'].strftime('%Y-%m-%d')
        open_p = open_prices.get(date_str)
        if open_p is None:
            continue
            
        step = get_daily_harmonic_step(s['ts'].date())
        dist = get_closest_harmonic_distance(float(s['price_at_signal']), float(open_p), float(step))
        
        ctx = s['context']
        if isinstance(ctx, str):
            ctx = json.loads(ctx)
            
        ctx['dist_to_macro_harmonic'] = dist
        updates.append((json.dumps(ctx), s['id']))
        
    print(f"Preparados {len(updates)} updates.")
    
    with conn.cursor() as cur:
        cur.executemany("UPDATE signals SET context = %s::jsonb WHERE id = %s", updates)
        
    conn.commit()
    conn.close()
    print("Sucesso! Banco de dados atualizado retrospectivamente.")

if __name__ == "__main__":
    run()
