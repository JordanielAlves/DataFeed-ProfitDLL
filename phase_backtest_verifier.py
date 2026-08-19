import sys
import psycopg2
import pandas as pd
from market_calendar import get_market_calendar_features

# Blindagem de Encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_DSN = "dbname=fluxo_ordens user=postgres password=postgres host=localhost"

def run_proof():
    print("\n🔍 ===========================================================================")
    print(" 🚀 TIRANDO A PROVA REAL: EFICÁCIA DE ROMPIMENTOS VS. CAIXOTES POR FASES DO MÊS")
    print("=============================================================================")
    
    with psycopg2.connect(DB_DSN) as conn:
        # Busca sinais auditados
        df = pd.read_sql_query("SELECT ts, signal_type, hit_scalp_2_5 FROM signals WHERE labeled_at IS NOT NULL AND signal_type != 'NEUTRAL'", conn)
        
    if df.empty:
        print("❌ Nenhum sinal auditado encontrado.")
        return
        
    feats = df['ts'].apply(get_market_calendar_features).apply(pd.Series)
    df['phase'] = feats['month_week_phase']
    
    df['is_absorcao'] = df['signal_type'].str.contains('ABSORCAO').astype(int)
    df['is_impulso'] = df['signal_type'].str.contains('IMPULSO').astype(int)
    
    for p in range(1, 5):
        df_p = df[df['phase'] == p]
        if df_p.empty:
            continue
            
        print(f"\n 📅 FASE {p} (Semanas {p} do Mês) - {len(df_p)} sinais encontrados:")
        print(f" -------------------------------------------------------------")
        
        abs_df = df_p[df_p['is_absorcao'] == 1]
        imp_df = df_p[df_p['is_impulso'] == 1]
        
        if len(abs_df) > 0:
            wr_abs = abs_df['hit_scalp_2_5'].mean() * 100
            print(f" 🎣 Absorção / Retorno à Média : \033[1;32m{wr_abs:.1f}%\033[0m WinRate ({len(abs_df)} agressões passivas)")
            
        if len(imp_df) > 0:
            wr_imp = imp_df['hit_scalp_2_5'].mean() * 100
            # Pintar de vermelho se < 40%, amarelo se médio, verde se > 60%
            color_imp = "\033[1;31m" if wr_imp < 40 else ("\033[1;33m" if wr_imp < 60 else "\033[1;32m")
            print(f" ⚡ Impulso / Rompimento       : {color_imp}{wr_imp:.1f}%\033[0m WinRate ({len(imp_df)} agressões diretivas)")

    print("\n=============================================================================\n")

if __name__ == "__main__":
    run_proof()
