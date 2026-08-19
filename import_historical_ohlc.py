import csv
import psycopg2
from config import DB_DSN
from datetime import datetime

def parse_price(price_str):
    """Remove 'R$', espaços, converte '.' milhar para vazio, e ',' para '.'"""
    if not price_str:
        return 0.0
    p = price_str.replace('R$', '').strip()
    p = p.replace('.', '')
    p = p.replace(',', '.')
    return float(p)

def run():
    print("Conectando ao banco de dados...")
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    
    file_path = "Dados Históricos WDOFUT.csv"
    print(f"Lendo {file_path}...")
    
    records = []
    
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f, delimiter=';')
        next(reader) # skip header
        for row in reader:
            if len(row) < 5:
                continue
            date_str = row[0].strip()
            if not date_str:
                continue
            
            try:
                date_obj = datetime.strptime(date_str, "%d/%m/%Y").date()
                open_p = parse_price(row[1])
                high_p = parse_price(row[2])
                low_p = parse_price(row[3])
                close_p = parse_price(row[4])
                
                records.append((date_obj, 'WDOFUT', open_p, high_p, low_p, close_p))
            except Exception as e:
                print(f"Erro ao converter linha: {row} -> {e}")
                
    print(f"Lidos {len(records)} pregões.")
    
    print("Limpando a tabela daily_ohlc atual para recarregar...")
    cur.execute("TRUNCATE TABLE daily_ohlc;")
    
    print("Inserindo dados no banco...")
    query = """
    INSERT INTO daily_ohlc (date, ticker, open_p, high_p, low_p, close_p)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (date) DO NOTHING;
    """
    cur.executemany(query, records)
    conn.commit()
    
    cur.execute("SELECT COUNT(*) FROM daily_ohlc;")
    count = cur.fetchone()[0]
    print(f"Sucesso! {count} dias históricos gravados em daily_ohlc.")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    run()
