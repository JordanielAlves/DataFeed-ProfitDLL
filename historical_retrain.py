import os
import subprocess
import sys
from datetime import date, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def main():
    print("=================================================================")
    print(" 🧠 RETREINAMENTO GLOBAL (MARÇO a JUNHO) ")
    print("=================================================================")
    
    # 1. Rotulação de todos os dias passados
    print("\n[Passo 1/2] Rotulando Sinais Históricos (Ground Truth MFE/MAE)...")
    
    start_date = date(2026, 3, 23)
    end_date = date(2026, 6, 12)
    current = start_date
    
    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")
        try:
            # Pula a verificação check=True para evitar interromper o script inteiro caso um dia falhe ou esteja vazio
            subprocess.run(["python.exe", "daily_postmarket_labeler.py", "--date", date_str])
        except Exception as e:
            print(f"❌ Erro na rotulação do dia {date_str}: {e}")
        current += timedelta(days=1)
        
    print("✅ Rotulação de todos os dias concluída!")

    # 2. Retreinamento do Modelo ML
    print("\n[Passo 2/2] Retreinando Random Forest com 5 splits...")
    try:
        subprocess.run(["python.exe", "ml_model_trainer.py", "--splits", "5"], check=True)
        print("✅ Retreinamento concluído com sucesso!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro no treinamento: {e}")
        return

    print("\n🚀 PROCESSO DE ATUALIZAÇÃO HISTÓRICA CONCLUÍDO! O modelo quant_signals_v1.pkl foi atualizado.")

if __name__ == "__main__":
    main()
