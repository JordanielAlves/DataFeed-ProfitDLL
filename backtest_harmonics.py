import pandas as pd
import psycopg2
from config import DB_DSN
from dynamic_harmonics import get_daily_harmonic_step, get_closest_harmonic_distance
from tqdm import tqdm

def run_backtest(gain_target=2.5, stop_loss=4.5):
    print("Conectando ao banco de dados...")
    conn = psycopg2.connect(DB_DSN)
    
    query = """
    SELECT s.id, s.ts, DATE(s.ts) as date, s.ticker, s.signal_type, s.direction, s.price_at_signal, s.hit_scalp_2_5
    FROM signals s
    WHERE s.signal_type != 'NEUTRAL'
    ORDER BY s.ts ASC
    """
    df = pd.read_sql(query, conn)
    
    # Obter aberturas (direto da tabela daily_ohlc que é super leve!)
    query_open = """
    SELECT date, open_p
    FROM daily_ohlc
    WHERE ticker = 'WDOFUT'
    """
    df_open = pd.read_sql(query_open, conn)
    
    # Garantir que a data seja tipo Date no Pandas para bater com a query de signals
    df_open['date'] = pd.to_datetime(df_open['date']).dt.date
    df['date'] = pd.to_datetime(df['date']).dt.date
    
    # Mesclar com os sinais
    df = df.merge(df_open, on='date', how='left')
    
    print(f"Total de sinais para analisar: {len(df)}")
    
    # Calcular harmonic step por dia
    unique_dates = df['date'].unique()
    harmonic_steps = {}
    for d in unique_dates:
        harmonic_steps[d] = get_daily_harmonic_step(d)
        
    # Calcular dist_to_macro_harmonic para cada sinal
    def calc_dist(row):
        if pd.isna(row['open_p']) or pd.isna(row['price_at_signal']):
            return None
        step = harmonic_steps[row['date']]
        
        # Ajuste de escala para WDO
        open_p = float(row['open_p']) / 10.0 if row['open_p'] > 50000 else float(row['open_p'])
        price_p = float(row['price_at_signal'])
        
        return get_closest_harmonic_distance(price_p, open_p, step)
        
    print("Calculando distâncias harmônicas (Volatilidade 45d)...")
    df['dist_macro'] = df.apply(calc_dist, axis=1)
    
    # Filtrar nulos
    df = df.dropna(subset=['dist_macro'])
    
    # Classificar: "Na Zona" se dist <= 1.5 pts, senão "Fora"
    df['zona_harmonica'] = df['dist_macro'].apply(lambda x: 'NA_ZONA' if x <= 1.5 else 'FORA')
    
    # Avaliar taxa de acerto
    # Como os hit_scalp_2_5 já foram calculados pelo labeler diário, vamos usar essa flag!
    # Mas se hit_scalp_2_5 for nulo, ignoramos.
    df = df.dropna(subset=['hit_scalp_2_5'])
    
    if len(df) == 0:
        print("Nenhum sinal rotulado encontrado. Por favor rode daily_postmarket_labeler.py primeiro.")
        return
        
    # Agrupar e calcular estatísticas
    print("\n=======================================================")
    print("BACKTEST: EFEITO DOS HARMÔNICOS DE VOLATILIDADE (45D)")
    print("=======================================================\n")
    
    stats = df.groupby(['signal_type', 'zona_harmonica'])['hit_scalp_2_5'].agg(['count', 'mean'])
    stats['mean'] = (stats['mean'] * 100).round(1)
    
    print("Taxa de Acerto (Win Rate) por Tipo de Sinal e Localização:\n")
    print(stats)
    
    print("\nResumo por Localização (Independente do Sinal):")
    resumo = df.groupby('zona_harmonica')['hit_scalp_2_5'].agg(['count', 'mean'])
    resumo['mean'] = (resumo['mean'] * 100).round(1)
    print(resumo)
    
    # Salvar resultados
    with open('harmonic_backtest_report.txt', 'w', encoding='utf-8') as f:
        f.write("BACKTEST: EFEITO DOS HARMÔNICOS DE VOLATILIDADE (45D)\n\n")
        f.write(stats.to_string())
        f.write("\n\nResumo por Localização:\n")
        f.write(resumo.to_string())
        
    print("\nRelatório salvo em harmonic_backtest_report.txt")
    
if __name__ == "__main__":
    run_backtest()
