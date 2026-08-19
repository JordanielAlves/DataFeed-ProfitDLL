import sys
import json
import psycopg2
from datetime import datetime, timedelta
from psycopg2.extras import RealDictCursor

# Corrigir encoding no Windows PowerShell se necessário
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from config import DB_DSN
from ml_live_predictor import MLLivePredictor

def load_signals_for_day(date_str: str) -> list:
    """Busca todos os sinais de um dia específico."""
    query = """
        SELECT 
            ts, 
            ticker, 
            signal_type, 
            direction, 
            price_at_signal, 
            context
        FROM signals
        WHERE DATE(ts) = %s
        ORDER BY ts ASC
    """
    try:
        with psycopg2.connect(DB_DSN) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (date_str,))
                return cur.fetchall()
    except Exception as e:
        print(f"Erro ao buscar sinais: {e}")
        return []

def main():
    print("=========================================================")
    print(" ⏳ ASSISTENTE DE REPLAY SINCRONIZADO (PROFIT PRO) ⏳ ")
    print("=========================================================")
    
    date_str = input("Qual a data do Replay? (formato AAAA-MM-DD, ex: 2026-04-07): ").strip()
    if not date_str:
        date_str = "2026-04-07"
    
    print(f"\nCarregando sinais gerados pela IA para {date_str}...")
    signals = load_signals_for_day(date_str)
    
    if not signals:
        print(f"Nenhum sinal encontrado no banco para o dia {date_str}.")
        return
        
    print(f"✅ Sucesso! Foram carregados {len(signals)} alertas para este dia.")
    
    predictor = MLLivePredictor()
    
    last_printed_time = datetime.strptime(f"{date_str} 09:00:00", "%Y-%m-%d %H:%M:%S")
    
    print("\nInstruções:")
    print(" - Digite o horário exato que está passando no seu ProfitPro (ex: 09:15).")
    print(" - Ou apenas aperte ENTER para avançar 5 minutos no relógio do Python.")
    print(" - Digite 'q' para sair.\n")
    
    while True:
        try:
            user_input = input(f"\n🕒 Horário atual no Replay (último: {last_printed_time.strftime('%H:%M:%S')}): ").strip()
            
            if user_input.lower() == 'q':
                break
                
            if not user_input:
                current_time = last_printed_time + timedelta(minutes=5)
            else:
                if len(user_input) == 5: # HH:MM
                    user_input += ":00"
                current_time = datetime.strptime(f"{date_str} {user_input}", "%Y-%m-%d %H:%M:%S")
            
            if current_time < last_printed_time:
                print("O tempo não pode retroceder. Digite um horário futuro.")
                continue
                
            # Filtrar e imprimir sinais que ocorreram na janela entre o último print e o current_time
            matched = [s for s in signals if last_printed_time < s["ts"].replace(tzinfo=None) <= current_time]
            
            if not matched:
                print(f"Nenhum alerta gerado pela IA entre {last_printed_time.strftime('%H:%M:%S')} e {current_time.strftime('%H:%M:%S')}.")
            else:
                for sig in matched:
                    ts = sig["ts"].replace(tzinfo=None)
                    ctx = sig["context"]
                    cvd_b = ctx.get("cvd_big", 0)
                    cvd_v = ctx.get("cvd_varejo", 0)
                    delta_p = ctx.get("delta_p", 0.0)
                    ml_conviction = ctx.get("ml_conviction", 0)
                    
                    # Recriar a lista de detalhes e formatação visual
                    strength = "Media"
                    if ml_conviction and ml_conviction >= 65.0:
                        strength = "⭐ ALTA (ML)"
                    elif ml_conviction and ml_conviction <= 45.0:
                        strength = "⚠️ BAIXA (ML)"
                    
                    agents_str = ""
                    top_agents = ctx.get("top_agents", [])
                    if top_agents:
                        agents_str = ", ".join([f"{a.get('corretora', a.get('agent_id'))} ({a.get('saldo', 0):+d} ctrs)" for a in top_agents])
                        
                    title = f"[{ts.strftime('%H:%M:%S')}] {sig['ticker']} | {sig['signal_type']}"
                    
                    # Usa a função nativa do ML Predictor para gerar a barra Powerline bonita
                    predictor.print_powerline_alert(
                        title=title,
                        price_str=f"PREÇO: {sig['price_at_signal']:.2f} (Δ {delta_p:+.2f})",
                        extra_str=f"PROB: {ml_conviction}% ({strength})",
                        direction=sig["direction"],
                        agents_str=agents_str,
                        details_list=[
                            f"Varejo CVD: {cvd_v:+} | Institucional CVD: {cvd_b:+}"
                        ]
                    )
            
            last_printed_time = current_time
            
        except ValueError:
            print("Formato inválido! Use HH:MM ou HH:MM:SS.")
        except KeyboardInterrupt:
            break
            
    print("\nAssistente de Replay encerrado. Bons trades!")

if __name__ == "__main__":
    main()
