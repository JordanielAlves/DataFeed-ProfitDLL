"""
config.py
Configurações centrais do sistema.
NÃO commitar este arquivo em repositórios públicos.
"""

# ---------------------------------------------------------------------------
# Banco de dados PostgreSQL
# ---------------------------------------------------------------------------
DB = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "fluxo_ordens",
    "user":     "postgres",
    "password": "12021992",
}

# String de conexão (usada por psycopg2)
DB_DSN = (
    f"host={DB['host']} port={DB['port']} dbname={DB['dbname']} "
    f"user={DB['user']} password={DB['password']}"
)

# ---------------------------------------------------------------------------
# ProfitDLL
# ---------------------------------------------------------------------------
import os

DLL_PATH = os.path.join(
    os.path.dirname(__file__),
    "ProfitDLL", "DLLs", "Win64", "ProfitDLL.dll"
)

# ---------------------------------------------------------------------------
# Ativos monitorados
# ticker: código do ativo | exchange: "F" = BMF/Futuros
# Ajuste o vencimento conforme o contrato ativo
# ---------------------------------------------------------------------------
ASSETS = [
    {"ticker": "WDOK25",  "exchange": "F"},   # Mini Dólar
    {"ticker": "DOLK25",  "exchange": "F"},   # Dólar Cheio
    {"ticker": "DOLPRO",  "exchange": "F"},   # DolPro agregado
]

# ---------------------------------------------------------------------------
# Agentes conhecidos (mapeamento manual — expandir conforme observação)
# IDs numéricos fornecidos pela DLL, nomes para referência humana
# ---------------------------------------------------------------------------
KNOWN_AGENTS = {
    # Preencher após primeira sessão — a DLL retorna IDs numéricos
    # Exemplo (valores fictícios — confirmar com GetAgentName):
    # 386:  "XP",
    # 3:    "BTG",
    # 72:   "UBS",
    # 90:   "CM Capital",
    # 1:    "Clear",
    # 45:   "Genial",
    # 120:  "Terra",
    # 8:    "Safra",
    # 299:  "Tullett",
}

# Agentes classificados como varejo (sinal contrário)
RETAIL_AGENTS: set = set()   # preencher após identificar os IDs

# ---------------------------------------------------------------------------
# Parâmetros de gravação
# ---------------------------------------------------------------------------
RECORDER = {
    "trade_batch_size":     100,    # inserir a cada N trades acumulados
    "book_batch_size":      500,    # inserir a cada N eventos de book
    "flush_interval_sec":   2.0,    # forçar flush a cada X segundos
    "max_queue_size":       50_000, # tamanho máximo da fila em memória
}

# ---------------------------------------------------------------------------
# Parâmetros de análise
# ---------------------------------------------------------------------------
ANALYSIS = {
    "iceberg_min_renewals":     3,      # mínimo de renovações para considerar iceberg
    "retail_signal_threshold":  200,    # saldo líquido de varejo para gerar alerta
    "cvd_divergence_points":    50,     # divergência CVD/preço para alerta
}
