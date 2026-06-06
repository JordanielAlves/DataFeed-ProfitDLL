# 📊 Análise de Fluxo — Leitura de Fluxo de Ordens para Futuros B3

> Sistema de coleta e análise de fluxo de ordens em tempo real para os mercados futuros da B3 (WDO, DOL, DOLPRO), construído sobre a ProfitDLL da Nelogica. Projetado para leitura institucional de fluxo: fingerprinting de HFT, detecção de iceberg, perfilagem de agentes e insights de trading assistidos por IA.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![PostgreSQL 14+](https://img.shields.io/badge/postgresql-14%2B-blue.svg)](https://www.postgresql.org/)
[![Plataforma: Windows x64](https://img.shields.io/badge/plataforma-Windows%20x64-lightgrey.svg)]()
[![Licença: MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-green.svg)](LICENSE)

---

## Índice

- [O que é este projeto](#o-que-é-este-projeto)
- [Por que foi construído](#por-que-foi-construído)
- [Visão geral da arquitetura](#visão-geral-da-arquitetura)
- [Requisitos](#requisitos)
- [Início rápido](#início-rápido)
- [Configuração](#configuração)
- [Como usar](#como-usar)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Esquema do banco de dados](#esquema-do-banco-de-dados)
- [Roadmap](#roadmap)
- [Contribuindo](#contribuindo)
- [Aviso legal](#aviso-legal)

---

## O que é este projeto

Um motor de coleta e análise de dados que roda em segundo plano e:

1. **Conecta ao market data da B3 em tempo real** via [ProfitDLL](https://www.nelogica.com.br/produtos/datafeed) (Nelogica)
2. **Persiste cada tick** — negócios com IDs de agente (corretora compradora/vendedora), mutações do book com `offer_id`, saldo diário por agente
3. **Calcula métricas de fluxo em tempo real**: CVD (Delta de Volume Acumulado), footprint por nível de preço, imbalance do book, spread
4. **Prepara o terreno para insights de IA**: reconhecimento de padrões de comportamento institucional, fingerprinting de HFT, detecção de iceberg, sinais contrários ao varejo

O sistema roda inteiramente em segundo plano. O trader continua usando o ProfitPro como interface principal; este motor coleta e aprende silenciosamente.

---

## Por que foi construído

Os mercados futuros da B3 (WDO/DOL/DOLPRO) têm uma característica estrutural única: **cada negócio executado expõe a corretora compradora e a vendedora (agente)**. Isso é raro globalmente. Permite:

- Identificar quais corretoras estão acumulando ou distribuindo no dia
- Detectar algoritmos de HFT pelas suas assinaturas características (renovação rápida, lotes fixos, níveis de preço específicos)
- Reconhecer clusters de varejo (lotes pequenos, corretoras como Clear/Rico) que historicamente precedem movimentos adversos
- Rastrear ordens iceberg através de padrões de renovação de `offer_id` em múltiplas execuções

Este projeto automatiza a coleta e estruturação desses dados para que o reconhecimento de padrões — inicialmente manual, eventualmente por IA — possa ser aplicado sistematicamente.

---

## Visão geral da arquitetura

```
┌──────────────────────────────────────────────────────────────────────┐
│                        ProfitDLL (Win64)                             │
│          Market data da Nelogica + identificação de agente           │
└─────────────────────────┬────────────────────────────────────────────┘
                          │ callbacks (ConnectorThread)
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       profit_bridge.py                               │
│  wrapper ctypes · eventos tipados · price depth · estado de conexão  │
└─────────────────┬──────────────────────────────────┬────────────────┘
                  │ TradeEvent / BookEvent             │ PriceDepthEvent
                  ▼                                    ▼
┌─────────────────────────────┐      ┌────────────────────────────────┐
│       flow_engine.py        │      │         price depth            │
│  CVD · footprint            │◄─────│  estado mantido pela DLL       │
│  book imbalance · spread    │      │  consultado no utFlush         │
└─────────────────────────────┘      └────────────────────────────────┘
                  │
                  │ Queue (produtor/consumidor — nunca bloqueia callbacks)
                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      data_recorder.py                                │
│    inserções em lote · upsert agent_daily · gestão de sessões        │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ psycopg2 (batched)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                  PostgreSQL — fluxo_ordens                           │
│  sessions · trades · book_events · agent_daily · icebergs · signals  │
└──────────────────────────────────────────────────────────────────────┘
```

**Princípio central de design:** callbacks da DLL apenas enfileiram. Todo I/O — gravações no banco, computações pesadas — acontece em threads separadas. Isso segue a recomendação oficial da Nelogica e garante zero ticks perdidos.

Veja [ARCHITECTURE.md](ARCHITECTURE.md) para o detalhamento técnico completo.

---

## Requisitos

| Dependência | Versão | Observações |
|---|---|---|
| Windows | 10/11 x64 | ProfitDLL é exclusiva para Windows |
| Python | 3.10+ (64-bit) | **Obrigatoriamente 64-bit** — Python 32-bit tem um bug no ctypes com tipos > 32 bits |
| PostgreSQL | 14+ | Local ou remoto |
| ProfitDLL | Última versão | [Nelogica DataFeed](https://www.nelogica.com.br/produtos/datafeed) — trial gratuito de 30 dias disponível |
| ProfitPro | Última versão | Deve estar aberto e logado para a DLL conectar |

**Pacotes Python:**
```
psycopg2-binary
```

Instalação:
```bash
pip install psycopg2-binary
```

---

## Início rápido

### 1. Clone o repositório

```bash
git clone https://github.com/seu-usuario/analise-de-fluxo.git
cd analise-de-fluxo
```

### 2. Coloque a ProfitDLL

Baixe o pacote ProfitDLL na Nelogica e coloque em:
```
ProfitDLL/
  DLLs/
    Win64/
      ProfitDLL.dll
```

Ou configure um caminho personalizado com o argumento `--dll`.

### 3. Configure

Copie o exemplo de configuração e preencha com suas credenciais:
```bash
copy config.example.py config.py
```

Edite `config.py`:
```python
DB = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "fluxo_ordens",
    "user":     "postgres",
    "password": "SUA_SENHA",
}

ASSETS = [
    {"ticker": "WDOK25", "exchange": "F"},   # ajustar para o contrato ativo
    {"ticker": "DOLK25", "exchange": "F"},
    {"ticker": "DOLPRO", "exchange": "F"},
]
```

> ⚠️ **Nunca faça commit do `config.py`** — ele contém credenciais. Já está no `.gitignore`.

### 4. Configure o banco de dados

```bash
python setup_db.py
```

Isso cria o banco `fluxo_ordens` e todas as tabelas automaticamente.

### 5. Abra o ProfitPro

Abra o Nelogica ProfitPro e faça login. A DLL utiliza a sessão autenticada do ProfitPro.

### 6. Execute o coletor

```bash
python main.py
```

Você será solicitado a informar sua chave de acesso Nelogica, usuário e senha.

### 7. (Opcional) Baixe dados históricos

```bash
# Últimos 30 dias
python historical_downloader.py --dias 30

# Período específico
python historical_downloader.py --inicio 01/03/2025 --fim 30/05/2025

# Ativo específico
python historical_downloader.py --dias 60 --ticker WDOK25
```

Os dados históricos incluem IDs de agente — mesma riqueza que o tempo real.

---

## Configuração

Toda configuração fica em `config.py`:

| Chave | Descrição |
|---|---|
| `DB` | Parâmetros de conexão PostgreSQL |
| `DLL_PATH` | Caminho para `ProfitDLL.dll` (Win64) |
| `ASSETS` | Lista de tickers a monitorar (`ticker` + `exchange`) |
| `KNOWN_AGENTS` | Mapeamento manual de IDs numéricos de agente para nomes de corretora |
| `RETAIL_AGENTS` | Conjunto de IDs de agentes classificados como varejo (sinal contrário) |
| `RECORDER` | Tamanho dos lotes, intervalo de flush, limite da fila |
| `ANALYSIS` | Limites de iceberg, parâmetros de divergência de CVD |

**Atualizando códigos de contrato:** Os contratos futuros da B3 vencem mensalmente/trimestralmente. Atualize `ASSETS` e `HORARIOS` no `historical_downloader.py` conforme os contratos expiram. Exemplo: `WDOK25` → `WDOM25`.

---

## Como usar

### Coleta em tempo real (`main.py`)

```
python main.py [--dll CAMINHO] [--key CHAVE] [--user USUARIO] [--market-only]
```

**Comandos disponíveis durante a execução:**

| Comando | Descrição |
|---|---|
| `status WDOK25` | Snapshot completo: CVD, footprint, book, candle diário |
| `list` | Todos os ativos ativos com último preço e CVD |
| `footprint 10` | Top 10 níveis de footprint por preço |
| `db` | Estatísticas do gravador de banco de dados |
| `help` | Referência de comandos |
| `exit` | Encerramento gracioso com flush final no banco |

**Saída no console (uma linha por negócio):**
```
14:32:07.543  WDOK25     5.248,50  BUY    5  CVD  +1.234  DailyΔ  +8.901  →→→→·  (+0,72)
```

### Download histórico (`historical_downloader.py`)

Baixa dados tick a tick com IDs de agente via `GetHistoryTrades`. Dias já presentes no banco são ignorados automaticamente (idempotente).

```bash
python historical_downloader.py --dias 30
python historical_downloader.py --inicio 01/01/2025 --fim 31/05/2025 --ticker DOLPRO
```

### Configuração do banco (`setup_db.py`)

```bash
python setup_db.py   # executar uma vez — cria banco + todas as tabelas
```

---

## Estrutura do projeto

```
analise-de-fluxo/
│
├── profit_bridge.py        # Wrapper ctypes da ProfitDLL
│   │                       # eventos tipados, API de price depth, estado de conexão
│   └── Exporta: TradeEvent, BookEvent, PriceDepthEvent, DailyEvent
│                ProfitBridge (initialize, subscribe, get_price_depth, ...)
│                Constantes de TradeType e estado de conexão
│
├── flow_engine.py          # Motor de métricas em tempo real
│   │                       # CVD, footprint, imbalance do book, spread
│   └── Exporta: FlowEngine, FlowSnapshot, FootprintLevel, BookLevel
│
├── data_recorder.py        # Persistência no PostgreSQL (fila produtor/consumidor)
│   └── Exporta: DataRecorder (start, stop, on_trade, on_book, on_daily)
│
├── historical_downloader.py # Backfill histórico via GetHistoryTrades
│   └── Exporta: HistoricalDownloader
│
├── config.py               # ⚠️ NÃO commitar — credenciais e ajustes
├── config.example.py       # Template — commitar este no lugar do config.py
│
├── schema.sql              # Esquema PostgreSQL completo
├── setup_db.py             # Inicialização única do banco de dados
│
├── main.py                 # Ponto de entrada — conecta tudo
│
├── ProfitDLL/              # ⚠️ NÃO commitar — DLL proprietária da Nelogica
│   └── DLLs/Win64/ProfitDLL.dll
│
├── ARCHITECTURE.md         # Detalhamento técnico profundo
├── ROADMAP.md              # Funcionalidades planejadas e fases futuras
└── CONTRIBUTING.md         # Como contribuir
```

---

## Esquema do banco de dados

Seis tabelas + duas views:

| Tabela | Finalidade |
|---|---|
| `sessions` | Uma linha por ticker por dia — bookkeeping para análise em lote |
| `trades` | Cada negócio executado: preço, qtd, volume, agente comprador, agente vendedor, tipo |
| `book_events` | Cada mutação do book de ofertas com `offer_id` para rastreamento de iceberg |
| `agent_daily` | Saldo acumulado por agente por dia (qtd compra, qtd venda, volume) |
| `icebergs` | Ordens iceberg detectadas (populada pelo analisador — Fase 2) |
| `signals` | Sinais gerados pelo sistema com colunas de validação pelo trader |

Views: `v_agent_balance_today`, `v_active_icebergs`

Esquema completo: [schema.sql](schema.sql) — veja [ARCHITECTURE.md](ARCHITECTURE.md) para a justificativa do design.

---

## Roadmap

Veja [ROADMAP.md](ROADMAP.md) para o detalhamento completo. Em resumo:

- **Fase 1 (atual):** Coleta de dados em tempo real, persistência no PostgreSQL, backfill histórico
- **Fase 2:** Análise de padrões offline — fingerprinting de HFT, detecção de iceberg, perfilagem de agentes
- **Fase 3:** Motor de sinais em tempo real — alertas baseados em regras, diário do trader, loop de feedback
- **Fase 4:** Camada de IA/ML — aprendizado de padrões, pontuação de sinais, previsão de comportamento
- **Fase 5:** Automação — sinais validados → roteamento automatizado de ordens via DLL

---

## Contribuindo

Veja [CONTRIBUTING.md](CONTRIBUTING.md).

Issues e PRs são bem-vindos, especialmente sobre:
- Mapeamento de IDs de agente (nomes de corretoras para os IDs numéricos)
- Algoritmos de detecção de padrões
- Instrumentos adicionais da B3
- Melhorias de performance

---

## Aviso legal

Este projeto é para fins **educacionais e de pesquisa**. Não constitui recomendação de investimento. Operar futuros envolve risco substancial de perda. Padrões passados não garantem resultados futuros.

A ProfitDLL é software proprietário da Nelogica. Este projeto fornece apenas um wrapper Python — a DLL em si não está incluída e deve ser obtida separadamente na [Nelogica](https://www.nelogica.com.br/produtos/datafeed).

---

## Licença

Licença MIT — veja [LICENSE](LICENSE).
