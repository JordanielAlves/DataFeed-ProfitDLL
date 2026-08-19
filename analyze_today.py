import psycopg2
from config import DB_DSN
from datetime import date

def analyze_today():
    today = date.today().isoformat()
    # today = '2026-08-18'
    
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        
        # 1. Min/Max/Open/Close for WDOU26
        query_ohlc = """
            SELECT 
                (SELECT price FROM trades WHERE ticker = 'WDOU26' AND ts >= %s AND ts < %s::date + interval '1 day' ORDER BY ts ASC LIMIT 1) as open_p,
                MAX(price),
                MIN(price),
                (SELECT price FROM trades WHERE ticker = 'WDOU26' AND ts >= %s AND ts < %s::date + interval '1 day' ORDER BY ts DESC LIMIT 1) as close_p
            FROM trades 
            WHERE ticker = 'WDOU26' AND ts >= %s AND ts < %s::date + interval '1 day'
        """
        cur.execute(query_ohlc, (today, today, today, today, today, today))
        row = cur.fetchone()
        
        if not row or row[1] is None:
            print("Nenhum trade encontrado para o WDOU26 hoje.")
            return

        open_p = float(row[0]) / 10.0 if row[0] else 0
        max_p = float(row[1]) / 10.0
        min_p = float(row[2]) / 10.0
        close_p = float(row[3]) / 10.0 if row[3] else 0
        
        print(f"--- RESUMO WDOU26 ({today}) ---")
        print(f"Abertura: {open_p}")
        print(f"Máxima:   {max_p}")
        print(f"Mínima:   {min_p}")
        print(f"Fechamento: {close_p}")
        print(f"Amplitude (pts): {max_p - min_p}")
        
        # 2. Sinais gerados hoje
        query_signals = """
            SELECT 
                COUNT(*),
                SUM(CASE WHEN hit_scalp_2_5 THEN 1 ELSE 0 END) as gains,
                SUM(CASE WHEN hit_scalp_2_5 = FALSE THEN 1 ELSE 0 END) as losses
            FROM signals
            WHERE ticker = 'WDOU26' AND ts >= %s AND ts < %s::date + interval '1 day'
        """
        cur.execute(query_signals, (today, today))
        sig_row = cur.fetchone()
        total_sig = sig_row[0]
        gains = sig_row[1] or 0
        losses = sig_row[2] or 0
        
        print(f"\n--- SINAIS DA IA HOJE ---")
        print(f"Total de Sinais: {total_sig}")
        if total_sig > 0:
            print(f"Gains (2.5 pts): {gains} ({(gains/total_sig)*100:.1f}%)")
            print(f"Losses (4.5 pts): {losses} ({(losses/total_sig)*100:.1f}%)")
            
            # Ver estatísticas de contexto
            cur.execute("""
                SELECT 
                    AVG((context->>'dist_to_macro_harmonic')::numeric),
                    AVG((context->>'delta_p')::numeric)
                FROM signals
                WHERE ticker = 'WDOU26' AND ts >= %s AND ts < %s::date + interval '1 day'
            """, (today, today))
            ctx_row = cur.fetchone()
            print(f"Distância média dos harmônicos nos sinais: {ctx_row[0]:.2f} pts")
        
        conn.close()
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    analyze_today()
