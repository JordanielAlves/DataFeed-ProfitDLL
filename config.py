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
# Credenciais da Nelogica (ProfitDLL)
# ---------------------------------------------------------------------------
PROFIT = {
    "key":      os.getenv("PROFIT_KEY",      "1788578460549219652"),
    "user":     os.getenv("PROFIT_USER",     "72784695115"),
    "password": os.getenv("PROFIT_PASSWORD", "Hkeycode#$%1010"),
}

# ---------------------------------------------------------------------------
# Ativos monitorados
# ticker: código do ativo | exchange: "F" = BMF/Futuros
# Ajuste o vencimento conforme o contrato ativo
# ---------------------------------------------------------------------------
ASSETS = [
    # Contratos vigentes:
    {"ticker": "WDOU26",  "exchange": "F"},   # Mini Dólar — Vencimento Setembro/26
 #   {"ticker": "WINV26",  "exchange": "F"},   # Mini Índice — Vencimento Outubro/26
    {"ticker": "DI1F27",  "exchange": "F"},   # Juros Futuros Jan/2027 (Contexto Macro Doméstico)
    {"ticker": "DI1F29",  "exchange": "F"},   # Juros Futuros Jan/2029 (Contexto Macro Doméstico)
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
# Fator de escala de preço por prefixo de ativo
# A ProfitDLL Nelogica retorna o preço do WIN/IND em "ticks" onde
# cada tick = 5 pontos de Ibovespa — NÃO em pontos reais do índice.
# Ex: DLL retorna 35.584 → preço real no mercado = 177.920 pts (× 5).
# WDO/DOL não têm esse problema (fator = 1).
# DOLPRO e outros sintéticos também devem ser validados na primeira sessão.
# ---------------------------------------------------------------------------
PRICE_SCALE_BY_PREFIX: dict = {
    "WIN": 5,    # Mini Índice — DLL retorna preço/5 (ticks de 5 pts de Ibovespa)
    "IND": 5,    # Índice cheio — mesmo comportamento esperado
    "WDO": 1,    # Mini Dólar — sem escala (ex: 50980.00)
    "DOL": 0.2,  # Dólar cheio — DLL retorna 5x o mini (254950.00 → 50980.00)
}

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

# ---------------------------------------------------------------------------
# Alertas via Telegram
# Para configurar:
#   1. Abra o Telegram e converse com @BotFather
#   2. Envie /newbot e siga as instruções → você receberá um TOKEN
#   3. Abra t.me/userinfobot para descobrir seu CHAT_ID
#   4. Preencha token e chat_id abaixo e mude enabled para True
# ---------------------------------------------------------------------------
TELEGRAM = {
    "token":    os.getenv("TELEGRAM_TOKEN",   ""),   # ex: "7123456789:AAFxxxxxx"
    "chat_id":  os.getenv("TELEGRAM_CHAT_ID", ""),   # ex: "123456789"
    "enabled":  False,   # mudar para True após configurar token e chat_id
}

# ---------------------------------------------------------------------------
# Pregão B3 (horários para watchdog e qualidade de dados)
# ---------------------------------------------------------------------------
PREGAO = {
    "hora_inicio":  "08:45",   # watchdog começa a monitorar
    "hora_fim":     "18:15",   # watchdog para de monitorar
    "quality_check":"18:30",   # horário do daily_quality_check.py
}
