"""
config.example.py
Template de configuração — copie para config.py e preencha com seus valores.

    copy config.example.py config.py

NUNCA faça commit do config.py — ele contém credenciais.
"""

# ---------------------------------------------------------------------------
# Banco de dados PostgreSQL
# ---------------------------------------------------------------------------
DB = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "fluxo_ordens",
    "user":     "postgres",
    "password": "SUA_SENHA_AQUI",
}

DB_DSN = (
    f"host={DB['host']} port={DB['port']} dbname={DB['dbname']} "
    f"user={DB['user']} password={DB['password']}"
)

# ---------------------------------------------------------------------------
# ProfitDLL — caminho para a DLL Win64
# Obter em: https://www.nelogica.com.br/produtos/datafeed
# ---------------------------------------------------------------------------
import os

DLL_PATH = os.path.join(
    os.path.dirname(__file__),
    "ProfitDLL", "DLLs", "Win64", "ProfitDLL.dll"
)

# ---------------------------------------------------------------------------
# Ativos monitorados
# Ajuste o vencimento conforme o contrato ativo na B3.
# Exemplo: WDOK25 = Mini Dólar vencimento outubro/2025
#          WDOM25 = Mini Dólar vencimento novembro/2025
# ---------------------------------------------------------------------------
ASSETS = [
    {"ticker": "WDOK25",  "exchange": "F"},   # Mini Dólar — ajustar vencimento
    {"ticker": "DOLK25",  "exchange": "F"},   # Dólar Cheio — ajustar vencimento
    {"ticker": "DOLPRO",  "exchange": "F"},   # DolPro (contrato contínuo)
]

# ---------------------------------------------------------------------------
# Agentes conhecidos (mapeamento manual)
# A DLL retorna IDs numéricos. Após a primeira sessão, identifique os IDs
# observando o console e relacionando com o Time & Sales do ProfitPro.
# ---------------------------------------------------------------------------
KNOWN_AGENTS = {
    # Exemplos (valores fictícios — confirmar com dados reais):
    # 386: "XP Investimentos",
    # 3:   "BTG Pactual",
    # 72:  "UBS",
    # 1:   "Clear Corretora",
    # 45:  "Genial Investimentos",
}

# Agentes classificados como varejo (atuação contrária esperada)
# Preencher após identificar os IDs de corretoras de varejo (Clear, Rico, etc.)
RETAIL_AGENTS: set = set()

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
# Parâmetros de análise (Fase 2+)
# ---------------------------------------------------------------------------
ANALYSIS = {
    "iceberg_min_renewals":     3,      # mínimo de renovações para considerar iceberg
    "retail_signal_threshold":  200,    # saldo líquido de varejo para gerar alerta
    "cvd_divergence_points":    50,     # divergência CVD/preço para alerta
}
