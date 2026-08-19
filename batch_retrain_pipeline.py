import os
import subprocess
from datetime import date, timedelta
import sys

# Blindagem de Encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(n)

def run_batch_pipeline():
    start_date = date(2026, 6, 15)
    end_date = date(2026, 7, 17)
    
    print("="*80)
    print(" 🚀 INICIANDO PIPELINE DE RETREINAMENTO MULTICÍCLICO (105M TICKS)")
    print("="*80)

    for single_date in daterange(start_date, end_date):
        # Pula finais de semana
        if single_date.weekday() >= 5:
            continue
            
        date_str = single_date.strftime("%Y-%m-%d")
        print(f"\n[BATCH] 🔍 Auditando e Extraindo Sinais do Pregão: {date_str}...")
        
        # Chama o Rotulador Forense
        try:
            # Não usamos --recalculate para poupar tempo se já tiver sido feito, 
            # mas vamos processar todos os dias que não foram rotulados.
            subprocess.run(["python.exe", "daily_postmarket_labeler.py", "--date", date_str], check=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ Erro ao rotular a data {date_str}. Pulando...")
            continue

    print("\n" + "="*80)
    print(" 🧠 INICIANDO O TREINAMENTO DO NOVO MODELO (RANDOM FOREST)")
    print("="*80)
    
    try:
        subprocess.run(["python.exe", "ml_model_trainer.py", "--splits", "5"], check=True)
        print("✅ PIPELINE MULTICÍCLICO CONCLUÍDO COM SUCESSO!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro crítico ao treinar o modelo: {e}")

if __name__ == "__main__":
    run_batch_pipeline()
