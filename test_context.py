import time
import logging
from global_context import start_global_context, stop_global_context, get_global_context
from domestic_context import update_domestic_asset, get_domestic_context

logging.basicConfig(level=logging.INFO)

def run_test():
    print("Iniciando Global Context...")
    start_global_context()
    
    print("Simulando atualização de WIN e DI1 (Contexto Doméstico)...")
    update_domestic_asset("WINQ26", 130000.0, 129500.0) # subiu 500 pts
    update_domestic_asset("DI1F27", 10.550, 10.500)     # subiu 50 bps
    
    # Aguardar o fetch do TradingView (pode levar uns segundos na primeira vez)
    print("Aguardando fetch do TradingView...")
    for _ in range(5):
        time.sleep(2)
        global_ctx = get_global_context()
        if global_ctx.get("DXY"):
            break
            
    global_ctx = get_global_context()
    dom_ctx = get_domestic_context()
    
    print("\n--- RESULTADOS ---")
    print(f"Contexto Global: {global_ctx}")
    print(f"Contexto Doméstico: {dom_ctx}")
    
    assert dom_ctx["win_delta_pts"] == 500.0, "Delta WIN Incorreto"
    assert dom_ctx["di1_delta_pts"] > 0, "Delta DI1 Incorreto"
    
    print("Testes OK! Desligando...")
    stop_global_context()

if __name__ == "__main__":
    run_test()
