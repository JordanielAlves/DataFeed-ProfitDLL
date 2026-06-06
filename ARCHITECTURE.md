# Arquitetura — Análise de Fluxo

Este documento descreve o design técnico do sistema de análise de fluxo de ordens: responsabilidades dos componentes, fluxo de dados, decisões de design e trade-offs conhecidos.

---

## Índice

- [Contexto do sistema](#contexto-do-sistema)
- [Detalhamento dos componentes](#detalhamento-dos-componentes)
- [Fluxo de dados](#fluxo-de-dados)
- [Modelo de threads](#modelo-de-threads)
- [Detalhes de integração com a ProfitDLL](#detalhes-de-integração-com-a-profitdll)
- [Design do banco de dados](#design-do-banco-de-dados)
- [Decisões de design](#decisões-de-design)
- [Restrições conhecidas](#restrições-conhecidas)

---

## Contexto do sistema

O sistema integra com os mercados futuros da B3 (bolsa brasileira) via ProfitDLL da Nelogica — uma DLL Windows proprietária que fornece dados de mercado em tempo real com **identificação de agente (corretora) por negócio**.

Esses dados por agente são a principal proposta de valor. Na maioria dos mercados, os negócios são anônimos. Nos futuros da B3, cada negócio executado identifica as corretoras compradora e vendedora por um ID numérico. Isso possibilita:

- **Perfilagem institucional**: quais corretoras estão acumulando ou distribuindo
- **Fingerprinting de HFT**: algoritmos deixam padrões característicos (tamanho de lote, nível de preço, comportamento de renovação)
- **Detecção de varejo**: corretoras específicas (Clear, Rico) se correlacionam com fluxo de pessoa física, que historicamente precede movimentos adversos
- **Rastreamento de iceberg**: ordens passivas que renovam no mesmo preço com o mesmo `offer_id` revelam tamanho oculto

O sistema é inteiramente passivo — apenas lê dados de mercado. Nenhuma ordem é enviada na implementação atual.

---

## Detalhamento dos componentes

### `profit_bridge.py` — Wrapper da DLL

**Responsabilidade:** Encapsular toda a interação ctypes com a ProfitDLL. Traduzir callbacks C brutos em eventos Python tipados.

**Classes principais:**
- `ProfitBridge` — gerencia inicialização, assinaturas, estado de conexão
- `TradeEvent` — um negócio executado (preço, qtd, volume, agente comprador, agente vendedor, tipo, timestamp)
- `BookEvent` — uma mutação do book de ofertas (ação, posição, lado, qtd, agente, offer_id, preço)
- `PriceDepthEvent` — notificação da API de price depth (sinaliza que o book mudou; dados lidos separadamente)
- `DailyEvent` — agregado periódico da DLL (abertura/máxima/mínima/fechamento, delta diário, volume)

**Máquina de estados de conexão:**

A DLL dispara um callback de estado com `(state_type, result)`. Quatro tipos de estado independentes devem todos atingir "pronto" antes de o sistema estar operacional:

```
STATE_TYPE_LOGIN      (0): result 0 = OK
STATE_TYPE_ROUTING    (1): result 0 = OK (apenas com DLLInitializeLogin)
STATE_TYPE_MARKET     (2): result 4 = DATA_READY  ← chave para receber ticks
STATE_TYPE_ACTIVATION (3): result 0 = OK          ← validação de licença
```

`ProfitBridge.is_connected` é True somente quando tanto market (tipo 2, resultado 4) quanto activation (tipo 3, resultado 0) estão prontos.

**Dois modos da DLL:**
- `DLLInitializeMarketLogin`: apenas market data (sem roteamento de ordens) — usado por padrão
- `DLLInitializeLogin`: market data + roteamento de ordens — necessário para a Fase 5 de automação

**API dupla de book:**
- **Offer Book** (`SetOfferBookCallbackV2` / `SubscribeOfferBook`): ofertas individuais com IDs de agente e `offer_id`. Necessário para detecção de iceberg.
- **Price Depth** (`SetPriceDepthCallback` / `SubscribePriceDepth`): agregado por nível de preço, DLL mantém o estado. Melhor para imbalance do book. Consultado via `GetPriceGroup` após notificação de `utFlush`.

---

### `flow_engine.py` — Métricas em tempo real

**Responsabilidade:** Manter um `FlowSnapshot` atualizado por ticker, atualizado a cada evento.

**Campos do `FlowSnapshot`:**

| Campo | Descrição |
|---|---|
| `cvd` | Delta de Volume Acumulado — soma corrente de (qtd compra agressiva - qtd venda agressiva) |
| `buy_qty` / `sell_qty` | Total de contratos comprados/vendidos agressivamente na sessão |
| `cross_qty` | Negócios cruzados (sem agressor — dentro da mesma corretora) |
| `footprint` | Dict de `preço → FootprintLevel` (buy_qty, sell_qty, delta por nível de preço) |
| `bids` / `asks` | Estado atual do book (lista de BookLevel, melhor bid/ask primeiro) |
| `daily_*` | Abertura/máxima/mínima/fechamento/volume/delta do agregado periódico da DLL |
| `book_imbalance` | `(bid_qty - ask_qty) / (bid_qty + ask_qty)` no topo do book |

**Estado do book — fonte dupla:**
- `on_book()` aplica mutações do offer book (add/edit/delete/full_book) — rastreia mudanças por oferta
- `update_price_depth()` substitui bids/asks com o estado autoritativo do price depth da DLL — chamado no `utFlush`

O price depth tem prioridade quando disponível. Os eventos do offer book continuam disparando e são gravados no banco para análise de iceberg.

---

### `data_recorder.py` — Persistência

**Responsabilidade:** Persistir todos os eventos no PostgreSQL sem nunca bloquear os callbacks da DLL.

**Arquitetura:** padrão estrito de produtor/consumidor.

```
Callback da DLL (ConnectorThread)
    │
    │  queue.put_nowait()    ← não bloqueante, descarta se fila cheia
    ▼
Queue (maxsize=50.000)
    │
    │  thread escritora drena
    ▼
_buffer_trade / _buffer_book
    │
    │  flush a cada 2s OU lote cheio
    ▼
PostgreSQL (psycopg2 execute_values)
```

**Cache de agentes:** Os saldos diários por agente são acumulados em memória (`_agent_cache`) e enviados via upsert para `agent_daily` a cada 10 segundos. Isso evita uma escrita no banco por negócio para o que é essencialmente um contador corrente.

**Gestão de sessões:** Na inicialização, uma linha em `sessions` é criada (ou atualizada) para cada ticker+hoje. No encerramento, os totais são gravados de volta em `sessions`.

---

### `historical_downloader.py` — Backfill

**Responsabilidade:** Baixar dados históricos tick a tick com IDs de agente via `GetHistoryTrades`.

**Detalhes importantes:**
- Baixa um dia por vez para evitar problemas de memória (WDO pode ter 400k+ negócios/dia)
- Verifica `_dia_ja_gravado()` antes de requisitar — idempotente, seguro para re-executar
- Pula fins de semana e feriados B3 (calendario hardcoded 2025–2026)
- Usa `SetSerieProgressCallback` — aguarda `progresso == 100` (threading.Event) para saber que o download concluiu
- Persiste no mesmo esquema que o gravador em tempo real (tabelas compartilhadas)

**Limitação:** `GetHistoryTrades` é limitado a aproximadamente 10 dias por ativo por requisição pelo servidor Nelogica. O downloader itera dia a dia para períodos mais longos.

---

## Fluxo de dados

### Caminho em tempo real (main.py)

```
ProfitDLL dispara callback
    → profit_bridge.py traduz para evento tipado
        → flow_engine.on_trade/on_book/on_daily() — atualiza FlowSnapshot em memória
        → data_recorder.on_trade/on_book() — enfileira na Queue
            → thread escritora drena → psycopg2 → PostgreSQL
```

### Caminho do Price Depth

```
ProfitDLL dispara TConnectorPriceDepthCallback (utFlush ou utFullBook)
    → PriceDepthEvent enfileirado na Queue no handler do main.py
        → thread escritora chama bridge.get_price_depth()
            → GetPriceGroup() para cada nível (lê estado interno da DLL)
                → flow_engine.update_price_depth() — substitui bids/asks
```

> Atenção: `get_price_depth()` é chamado de uma thread que não é a de callback. Chamar GetPriceGroup dentro do callback bloquearia a ConnectorThread.

### Caminho histórico (historical_downloader.py)

```
Usuário invoca CLI
    → ProfitBridge.initialize() + wait_connected()
        → HistoricalDownloader.baixar_periodo()
            → para cada dia útil:
                → GetHistoryTrades() → SetHistoryTradeCallback dispara N vezes
                    → negócios acumulados em lista na memória
                → callback de progresso dispara → threading.Event setado em 100%
                → _persistir() → inserção em lote via psycopg2
```

---

## Modelo de threads

| Thread | Origem | Responsabilidade |
|---|---|---|
| Thread principal | `main.py` | CLI, orquestração de inicialização/encerramento |
| ConnectorThread | ProfitDLL (interna) | Dispara todos os callbacks da DLL — nunca deve bloquear |
| recorder-writer | `DataRecorder._writer_loop` | Drena a fila, faz flush no banco |

**Regra:** Todos os callbacks da DLL (on_trade, on_book, on_price_depth) devem apenas chamar `queue.put_nowait()`. Sem chamadas ao banco, sem computações pesadas, sem sleep. Violar isso cria latência cumulativa na ConnectorThread.

**Estratégia de locks no FlowEngine:** Cada ticker tem seu próprio `threading.Lock`. O lock global só protege a criação do ticker. Isso permite atualizações concorrentes em tickers diferentes.

---

## Detalhes de integração com a ProfitDLL

### Constantes de TradeType

Valores documentados pela Nelogica:

| Valor | Constante | Significado |
|---|---|---|
| 1 | `TRADE_TYPE_CROSS` | Cross trade — sem agressor (dentro da mesma corretora) |
| 2 | `TRADE_TYPE_BUY` | Comprador agrediu — levantou a ask |
| 3 | `TRADE_TYPE_SELL` | Vendedor agrediu — bateu na bid |
| 4 | `TRADE_TYPE_LEILAO` | Negócio em leilão |
| 5–8 | Vários | Surveillance, ExPit, opções, OTC |
| 32 | `TRADE_TYPE_DESCONHECIDO` | Desconhecido |

> ⚠️ **Nota histórica:** Exemplos antigos da documentação mostram valores errados (BUY=1, SELL=2). Os valores corretos são BUY=2, SELL=3. Usar valores errados inverte toda a análise direcional.

### Armadilhas críticas no ctypes

**`c_longlong` vs `c_long`**: No Windows x64, `c_long` tem 32 bits. Para campos `Quantity` em `TConnectorTrade` e `TConnectorPriceGroup`, sempre usar `c_longlong` (Int64). Usar `c_long` resulta em `Quantity = 0` em todos os níveis e corrompe campos adjacentes da struct silenciosamente.

**Assinatura do callback de Price Depth**: O `TConnectorPriceDepthCallback` passa `side` e `updateType` como `c_ubyte`, não `c_int`. Tipos incorretos causam travamentos silenciosos.

**`TConnectorAssetIdentifier` por valor**: O callback de price depth recebe a struct do ativo por valor, não como ponteiro. Usar `POINTER(TConnectorAssetIdentifier)` causa dados incorretos ou crash.

**Proteção contra GC**: Todos os ponteiros de função callback devem ser mantidos vivos em variáveis de instância. Se o garbage collector do Python os liberar, a DLL chama um ponteiro inválido — o processo trava sem mensagem de erro.

**Python deve ser 64-bit**: A DLL é apenas 64-bit. Python 32-bit tem um bug conhecido no ctypes com tipos mais largos que 32 bits.

### Sequência de atualização do Price Depth

Em alta volatilidade, as atualizações chegam em rajadas:
```
utPrepare (5)   ← início da rajada
  utAdd (0)
  utEdit (1)
  utDelete (2)
  ...
utFlush (6)     ← fim da rajada — processar aqui
```

O sistema só chama `get_price_depth()` no `utFlush` ou `utFullBook`, não a cada atualização individual.

---

## Design do banco de dados

### Tabela `trades`

A tabela central. Uma linha por negócio executado. Colunas principais:

- `trade_number`: ID sequencial da B3 — usado como chave de idempotência (ON CONFLICT DO NOTHING)
- `buy_agent` / `sell_agent`: IDs numéricos de corretora — base de toda análise de agentes
- `trade_type`: 1=cross, 2=agressão compradora, 3=agressão vendedora (mapeia para constantes `TRADE_TYPE_*`)
- `ts`: timestamp com precisão de milissegundo

### Tabela `book_events`

Uma linha por mutação do book de ofertas. A coluna chave é `offer_id`:

Uma ordem iceberg no preço P aparece como:
1. `action=0` (ADD) com `offer_id=X` e `qty=100`
2. Após 100 contratos executarem: `action=2` (DELETE) para `offer_id=X`
3. `action=0` (ADD) com `offer_id=X` e `qty=100` novamente ← **renovação**

O `pattern_analyzer` (Fase 2) consultará essas renovações em `book_events` agrupadas por `offer_id` para popular a tabela `icebergs`.

### Tabela `agent_daily`

Total corrente por agente por dia. Enviado via upsert incrementalmente — linhas existentes têm deltas somados, não substituídos. Isso torna os upserts incrementais do gravador em tempo real e os upserts em lote do downloader histórico intercambiáveis.

### Tabela `signals`

Projetada para o loop de feedback humano-no-loop (Fase 3):
- `signal_type`: taxonomia de padrões detectados (iceberg_detected, retail_contrarian, cvd_divergence, etc.)
- `context` (JSONB): contexto completo no momento do sinal (estado do book, CVD, dados de agente)
- `trader_agrees` / `outcome_pts`: preenchidos manualmente — dados de treinamento para a Fase 4 de ML

---

## Decisões de design

### Decisão 1: ProfitDLL em vez de alternativas

**Alternativas consideradas:** MT5 (sem dados de agente na B3), Tryd (sem API de tick documentada), CME DataMine (bolsa errada), exchanges de crypto (sem dados de agente, microestrutura diferente).

**Decisão:** ProfitDLL é o único caminho para dados tick com nível de agente na B3. O trial gratuito de 30 dias valida a abordagem antes de comprometer com a assinatura.

### Decisão 2: PostgreSQL em vez de banco de série temporal

**Alternativas:** TimescaleDB, InfluxDB, ClickHouse, DuckDB.

**Decisão:** PostgreSQL puro cobre as Fases 1–3 confortavelmente (B3 WDO/DOL gera ~200k negócios/dia). O modelo relacional é natural para joins com agentes e metadados de sessão. Migrar para TimescaleDB se o desempenho de queries degradar em escala (Fase 4+).

### Decisão 3: Fila produtor/consumidor em vez de escrita direta no banco nos callbacks

**Por quê:** A Nelogica recomenda explicitamente esse padrão. Uma chamada ao banco dentro de um callback bloqueia a ConnectorThread, fazendo todos os callbacks subsequentes enfileirarem internamente. Em ticks de alta frequência (WDO pode ter 500+ negócios/minuto), isso cria latência cumulativa e eventualmente descarta eventos.

### Decisão 4: Book duplo — Offer Book + Price Depth

**Por que não usar apenas um:**
- Offer Book isolado: requer reconstrução manual do estado do book; propenso a erros de sincronização; mas fornece offer_id por agente — essencial para icebergs
- Price Depth isolado: DLL mantém estado autoritativo; imbalance mais limpo; mas sem dados de agente por oferta

**Decisão:** Usar ambos. Eventos do offer book vão para o banco para análise de iceberg. O price depth atualiza os `bids`/`asks` ativos no FlowSnapshot (sobrescreve o estado do offer book a cada `utFlush`).

### Decisão 5: Download histórico dia a dia

**Por que não requisitar o período completo de uma vez:** `GetHistoryTrades` pode retornar centenas de milhares de negócios para um único dia. Um intervalo de 60 dias alocaria centenas de MB em uma única acumulação de callback. Dia a dia limita o consumo de memória e fornece checkpointing natural (pular dias já no banco).

---

## Restrições conhecidas

| Restrição | Impacto | Mitigação |
|---|---|---|
| Apenas Windows x64 | Roda no Windows — sem Linux/Mac | Executar em VM Windows se necessário |
| ProfitPro deve estar aberto | DLL usa a sessão autenticada do ProfitPro | Criar script de inicialização / tarefa agendada |
| Limite de ~10 dias no `GetHistoryTrades` | Não é possível requisitar mais de ~10 dias por chamada | Loop dia a dia já implementado |
| `TNewDailyCallback` NÃO é tempo real | Delta diário da DLL é agregado periódico, não tick a tick | CVD calculado a partir dos negócios é o delta autoritativo em tempo real; callback diário usado apenas para dados do candle diário |
| Mapeamento de agent_id para nome de corretora | DLL retorna IDs numéricos; nomes legíveis precisam de mapeamento manual | Popular `KNOWN_AGENTS` no config.py após primeira sessão |
| Sem modo replay/simulação | Não é possível testar com dados históricos sem conexão ao vivo com a DLL | Fase 2 adicionará um motor de replay baseado no PostgreSQL |
