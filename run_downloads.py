import os
import subprocess
import sys

# Blindagem de Encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def run_downloader(ticker, start_date, end_date):
    print(f"\n=======================================================")
    print(f" 📥 INICIANDO DOWNLOAD: {ticker} ({start_date} a {end_date})")
    print(f"=======================================================")
    
    cmd = [
        "python.exe", "historical_downloader.py",
        "--ticker", ticker,
        "--inicio", start_date,
        "--fim", end_date
    ]
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao baixar {ticker}: {e}")

def main():
    print("🚀 INICIANDO ORQUESTRADOR DE DOWNLOAD HISTÓRICO 🚀")
    
    # Março (23/03 a 31/03) - Letra J26
    run_downloader("WDOJ26", "23/03/2026", "31/03/2026")
    run_downloader("DOLJ26", "23/03/2026", "31/03/2026")
    
    # Abril (01/04 a 30/04) - Letra K26
    run_downloader("WDOK26", "01/04/2026", "30/04/2026")
    run_downloader("DOLK26", "01/04/2026", "30/04/2026")
    
    # Maio (01/05 a 29/05) - Letra M26
    run_downloader("WDOM26", "01/05/2026", "29/05/2026")
    run_downloader("DOLM26", "01/05/2026", "29/05/2026")
    
    # Junho (01/06 a 12/06) - Letra N26
    run_downloader("WDON26", "01/06/2026", "12/06/2026")
    run_downloader("DOLN26", "01/06/2026", "12/06/2026")

    print("\n✅ DOWNLOAD HISTÓRICO CONCLUÍDO COM SUCESSO!")

if __name__ == "__main__":
    main()
