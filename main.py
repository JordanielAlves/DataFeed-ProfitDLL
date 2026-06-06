"""
main.py
Ponto de entrada da leitura de fluxo de ordens — WDO, DOL, DOLPRO.

Uso:
    python main.py

    Ou com argumentos:
    python main.py --dll "C:/caminho/ProfitDLL.dll" --key SUACHAVE
"""

import argparse
import os
import sys
import time
import threading
from getpass import getpass
from datetime import datetime

from profit_bridge  import (
    ProfitBridge, PriceDepthEvent,
    PD_UPDATE_FLUSH, PD_UPDATE_FULL_BOOK,
    BOOK_SIDE_BUY, BOOK_SIDE_SELL,
)
from flow_engine    import FlowEngine, FlowSnapshot
from data_recorder  import DataRecorder

# ---------------------------------------------------------------------------
# Ativos monitorados
# ---------------------------------------------------------------------------
ASSETS = [
    ("WDOK25",  "F"),   # Mini Dólar — vencimento corrente (ajustar conforme necessário)
    ("DOLK25",  "F"),   # Dólar Cheio
    ("DOLPRO",  "F"),   # DolPro (ativo de fluxo contínuo)
]

# Caminho padrão da DLL (Win64)
DEFAULT_DLL = os.path.join(
    os.path.dirname(__file__),
    "ProfitDLL", "DLLs", "Win64", "ProfitDLL.dll"
)

# ---------------------------------------------------------------------------
# Impressão no console (substitui a interface até ela ser definida)
# ---------------------------------------------------------------------------
_print_lock = threading.Lock()

def print_trade_update(snap: FlowSnapshot):
    """Imprime uma linha resumo a cada trade recebido."""
    with _print_lock:
        imb = snap.book_imbalance
        imb_bar = _imbalance_bar(imb)
        print(
            f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}  "
            f"{snap.ticker:<10} "
            f"Last {snap.last_price:>10.2f}  "
            f"{snap.last_side:<5}  "
            f"Qty {snap.last_qty:>4}  "
            f"CVD {snap.cvd:>+7}  "
            f"DailyΔ {snap.daily_delta:>+7}  "
            f"Imb {imb_bar}"
        )

def _imbalance_bar(imb) -> str:
    """Barra visual de imbalance: ←←←←·→→→→"""
    if imb is None:
        return "  n/a  "
    filled = int(abs(imb) * 5)
    filled = min(filled, 5)
    if imb > 0:
        return "·" * (5 - filled) + "→" * filled + f"  ({imb:+.2f})"
    else:
        return "←" * filled + "·" * (5 - filled) + f"  ({imb:+.2f})"

def print_header():
    print()
    print("=" * 90)
    print(f"  {'HORA':<15} {'ATIVO':<10} {'PREÇO':>10}  {'LADO':<5}  "
          f"{'QTD':>4}  {'CVD':>7}  {'Δ DIA':>7}  IMBALANCE")
    print("=" * 90)

def print_status(snap: FlowSnapshot):
    """Imprime estado completo de um ativo (para diagnóstico)."""
    print(f"\n--- STATUS: {snap.ticker} ---")
    print(f"  Última cotação : {snap.last_price:.2f}  ({snap.last_side})")
    print(f"  CVD (sessão)   : {snap.cvd:+d}  "
          f"(compra: {snap.buy_qty}  venda: {snap.sell_qty}  cross: {snap.cross_qty})")
    print(f"  Delta diário   : {snap.daily_delta:+d}  "
          f"(DLL: comprador {snap.daily_delta + snap.contracts_open // 2} / "
          f"vendedor {snap.contracts_open // 2})")
    print(f"  Candle dia     : O={snap.daily_open:.2f}  H={snap.daily_high:.2f}  "
          f"L={snap.daily_low:.2f}  C={snap.daily_close:.2f}")
    print(f"  Vol financeiro : R$ {snap.daily_vol:,.0f}")
    print(f"  Contratos open : {snap.contracts_open}")
    imb = snap.book_imbalance
    print(f"  Imbalance book : {imb:+.3f}" if imb else "  Imbalance book: n/a (sem book)")
    if snap.bids:
        print(f"  Melhor bid     : {snap.bids[0].price:.2f}  ({snap.bids[0].qty} contr.)")
    if snap.asks:
        print(f"  Melhor ask     : {snap.asks[0].price:.2f}  ({snap.asks[0].qty} contr.)")
    print(f"  Spread         : {snap.spread:.2f}" if snap.spread else "  Spread: n/a")
    print(f"  Total trades   : {snap.total_trades}")
    top = snap.top_footprint_levels(8)
    if top:
        print("  Footprint (top 8 níveis por preço):")
        for lvl in top:
            bar_b = "█" * min(int(lvl.buy_qty  / max(lvl.total_qty, 1) * 20), 20)
            bar_s = "█" * min(int(lvl.sell_qty / max(lvl.total_qty, 1) * 20), 20)
            print(f"    {lvl.price:>10.2f}  "
                  f"C {bar_b:<20} {lvl.buy_qty:>5}  "
                  f"V {bar_s:<20} {lvl.sell_qty:>5}  "
                  f"Δ {lvl.delta:>+6}")

# ---------------------------------------------------------------------------
# CLI interativa simples
# ---------------------------------------------------------------------------
def run_cli(engine: FlowEngine, recorder=None):
    """Loop de comandos para o usuário interagir enquanto os dados chegam."""
    HELP = """
Comandos disponíveis:
  status <TICKER>   — exibe estado completo do ativo
  list              — lista ativos ativos
  footprint <N>     — footprint dos N melhores níveis (padrão: 10)
  help              — este menu
  exit / quit       — encerrar
"""
    print(HELP)
    while True:
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not cmd:
            continue

        parts = cmd.split()
        verb  = parts[0].lower()

        if verb in ("exit", "quit"):
            break

        elif verb == "help":
            print(HELP)

        elif verb == "list":
            snaps = engine.all_snapshots()
            if not snaps:
                print("  (nenhum dado recebido ainda)")
            for t, s in snaps.items():
                print(f"  {t:<12}  Last={s.last_price:.2f}  CVD={s.cvd:+d}  Trades={s.total_trades}")

        elif verb == "status" and len(parts) >= 2:
            ticker = parts[1].upper()
            snap   = engine.snapshot(ticker)
            if snap:
                print_status(snap)
            else:
                print(f"  Ativo '{ticker}' não encontrado. Use 'list' para ver os disponíveis.")

        elif verb == "db":
            if recorder:
                print(f"  {recorder.status()}")
            else:
                print("  Recorder não disponível.")

        elif verb == "footprint":
            n = int(parts[1]) if len(parts) >= 2 else 10
            for ticker in engine.tickers():
                snap = engine.snapshot(ticker)
                if snap:
                    print(f"\n  Footprint — {ticker} (últimos {n} níveis):")
                    for lvl in snap.top_footprint_levels(n):
                        print(f"    {lvl.price:>10.2f}  "
                              f"C={lvl.buy_qty:>5}  V={lvl.sell_qty:>5}  "
                              f"Δ={lvl.delta:>+6}  "
                              f"Dom={'COMP' if lvl.delta > 0 else 'VEND' if lvl.delta < 0 else 'NEUT'}")

        else:
            print(f"  Comando desconhecido: '{cmd}'. Digite 'help'.")

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Leitor de Fluxo de Ordens — ProfitDLL")
    parser.add_argument("--dll", default=DEFAULT_DLL, help="Caminho para ProfitDLL.dll")
    parser.add_argument("--key",  default=None, help="Chave de acesso Nelogica")
    parser.add_argument("--user", default=None, help="Usuário (email ou CPF)")
    parser.add_argument("--market-only", action="store_true",
                        help="Conectar apenas como market data (sem roteamento)")
    args = parser.parse_args()

    # Verificar DLL
    if not os.path.isfile(args.dll):
        print(f"[ERRO] DLL não encontrada: {args.dll}")
        print("  Informe o caminho com --dll")
        sys.exit(1)

    # Credenciais
    key      = args.key  or input("Chave de acesso: ").strip()
    user     = args.user or input("Usuário (email/CPF): ").strip()
    password = getpass("Senha: ")

    # Inicializar componentes
    bridge   = ProfitBridge(args.dll)
    engine   = FlowEngine()
    recorder = DataRecorder()

    # Iniciar gravador ANTES de conectar à DLL
    recorder.start()

    # Conectar engine e recorder ao bridge (ambos recebem os mesmos eventos)
    def _on_trade(evt):
        engine.on_trade(evt)
        recorder.on_trade(evt)

    def _on_book(evt):
        engine.on_book(evt)
        recorder.on_book(evt)

    def _on_daily(evt):
        engine.on_daily(evt)
        recorder.on_daily(evt)

    # Price Depth: atualiza book_imbalance do engine com dados agregados da DLL
    # Processamos apenas no utFlush (fim de rajada) para evitar redesenho excessivo
    def _on_price_depth(evt: PriceDepthEvent):
        if evt.is_flush or evt.is_full_book:
            # Lê o livro atual da DLL e atualiza o engine
            # (chamado em thread separada via enfileiramento, não na ConnectorThread)
            depth = bridge.get_price_depth(evt.ticker, n_levels=10)
            engine.update_price_depth(evt.ticker, depth)

    bridge.on_trade  = _on_trade
    bridge.on_book   = _on_book
    bridge.on_daily  = _on_daily
    bridge.on_price_depth = _on_price_depth
    bridge.on_connected = lambda ok: print(
        f"\n[{'CONECTADO' if ok else 'DESCONECTADO'}] {datetime.now().strftime('%H:%M:%S')}"
    )

    # Imprimir cada trade no console
    engine.on_trade_update = print_trade_update

    print("\nInicializando DLL...")
    result = bridge.initialize(key, user, password, market_only=args.market_only)
    if result != 0:
        print(f"[ERRO] DLLInitialize retornou: {result}")
        sys.exit(1)

    # Registrar callback de price depth após initialize
    bridge.setup_price_depth()

    print("Aguardando conexão com o servidor...")
    if not bridge.wait_connected(timeout=30):
        print("[AVISO] Timeout aguardando conexão. Verifique se o ProfitPro está aberto e logado.")

    # Inscrever nos ativos (trades + offer book + price depth)
    print(f"\nInscrevendo nos ativos: {[a[0] for a in ASSETS]}")
    for ticker, exchange in ASSETS:
        bridge.subscribe(ticker, exchange)
        bridge.subscribe_price_depth(ticker, exchange)

    print_header()

    # CLI interativa em thread separada (não bloqueia os callbacks)
    cli_thread = threading.Thread(target=run_cli, args=(engine, recorder), daemon=True)
    cli_thread.start()
    cli_thread.join()

    # Encerrar
    print("\nFinalizando DLL...")
    bridge.finalize()
    recorder.stop()
    print("Encerrado.")


if __name__ == "__main__":
    main()
