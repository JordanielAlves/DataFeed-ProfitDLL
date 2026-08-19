import psycopg2
from config import DB_DSN
import numpy as np

def main():
    print("Conectando ao banco de dados para puxar MFE e MAE de todos os sinais...")
    
    query = """
        SELECT signal_type, mfe_3m, mae_3m
        FROM signals
        WHERE mfe_3m IS NOT NULL AND mae_3m IS NOT NULL
          AND signal_type != 'NEUTRAL'
    """
    
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute(query)
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        print(f"Erro no banco: {e}")
        return

    if not rows:
        print("Nenhum sinal com MFE/MAE encontrado.")
        return
        
    print(f"Total de sinais analisados: {len(rows)}")
    
    gains = np.arange(2.0, 8.5, 0.5)
    stops = np.arange(2.0, 6.5, 0.5)
    
    results = []
    
    for g in gains:
        for s in stops:
            wins = 0
            losses = 0
            ties = 0 # Ambiguous cases where both MFE >= g and MAE >= s
            timeouts = 0 # Cases where neither hit within 3 minutes
            
            for row in rows:
                mfe = float(row[1])
                mae = float(row[2])
                
                if mfe >= g and mae >= s:
                    # Conservador: Assume que pegou o stop primeiro
                    losses += 1
                    ties += 1
                elif mfe >= g:
                    wins += 1
                elif mae >= s:
                    losses += 1
                else:
                    # Não atingiu nem gain nem stop em 3 min, encerrou pelo tempo
                    # Conta como o resultado médio entre os não atingidos, ou zero?
                    # Vamos ignorar timeouts ou zerá-los. Para simplificar, consideramos neutro (0 pts)
                    timeouts += 1
                    
            # Saldo conservador
            saldo_pts = (wins * g) - (losses * s)
            total_closed = wins + losses
            win_rate = (wins / total_closed) * 100 if total_closed > 0 else 0
            
            results.append({
                "gain": g,
                "stop": s,
                "wins": wins,
                "losses": losses,
                "ties_considered_loss": ties,
                "timeouts": timeouts,
                "win_rate": win_rate,
                "saldo_pts": saldo_pts
            })
            
    # Ordenar por Saldo em Pontos
    results = sorted(results, key=lambda x: x["saldo_pts"], reverse=True)
    
    print("\nTop 15 Melhores Combinações de Risco/Retorno (Cenário Conservador):")
    print(f"{'Gain':<6} | {'Stop':<6} | {'Wins':<6} | {'Losses':<6} | {'Timeouts':<9} | {'Win Rate':<10} | {'Saldo (Pts)':<12}")
    print("-" * 75)
    
    for r in results[:15]:
        print(f"{r['gain']:<6.1f} | {r['stop']:<6.1f} | {r['wins']:<6} | {r['losses']:<6} | {r['timeouts']:<9} | {r['win_rate']:>6.2f}%    | {r['saldo_pts']:>+10.1f}")
        
    print("\nPiores 5 Combinações:")
    for r in results[-5:]:
        print(f"{r['gain']:<6.1f} | {r['stop']:<6.1f} | {r['wins']:<6} | {r['losses']:<6} | {r['timeouts']:<9} | {r['win_rate']:>6.2f}%    | {r['saldo_pts']:>+10.1f}")

if __name__ == "__main__":
    main()
