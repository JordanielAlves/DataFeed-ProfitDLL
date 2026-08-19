# Roadmap — Análise de Fluxo

Este documento descreve a evolução planejada do sistema ao longo de cinco fases, desde a coleta de dados brutos até o trading automatizado assistido por IA.

Cada fase constrói sobre a anterior. A Fase 1 é a fundação — sem dados de qualidade, nada mais funciona.

---

## Fase 1 — Coleta de Dados ✅ (Atual)

**Objetivo:** Coletar e persistir dados tick de alta fidelidade com identificação de agente. Construir o dataset do qual toda análise futura depende.

**Pré-requisito:** Acesso à ProfitDLL (trial gratuito de 30 dias disponível).

### Concluído

- [x] `profit_bridge.py` — wrapper ctypes completo da ProfitDLL
  - Eventos tipados TradeEvent, BookEvent, PriceDepthEvent, DailyEvent
  - Constantes TradeType corretas (CROSS=1, BUY=2, SELL=3)
  - Constantes nomeadas de estado de conexão (4 tipos de estado)
  - API dupla de book: Offer Book (ofertas por agente) + Price Depth (agregado mantido pela DLL)
  - Máquina de estados de conexão robusta
- [x] `flow_engine.py` — motor de métricas em tempo real
  - CVD (Delta de Volume Acumulado) por sessão
  - Footprint por nível de preço
  - Imbalance do book via API de Price Depth (padrão utFlush)
  - Dados do candle diário (abertura/máxima/mínima/fechamento)
- [x] `data_recorder.py` — persistência no PostgreSQL
  - Fila produtor/consumidor (callbacks nunca bloqueiam)
  - Inserções em lote (tamanho de lote + intervalo de flush configuráveis)
  - Cache de saldo diário por agente com upsert periódico
  - Gestão de sessões (abrir/fechar com totais)
- [x] `schema.sql` + `setup_db.py` — configuração automatizada do banco
  - Tabelas: sessions, trades, book_events, agent_daily, icebergs, signals
  - Índices para queries de análise (ticker+ts, agente, preço, offer_id)
  - Views: v_agent_balance_today, v_active_icebergs
- [x] `historical_downloader.py` — backfill histórico com agentes
  - Download dia a dia (eficiente em memória)
  - Idempotente (pula dias já no banco)
  - Calendário de feriados B3 2025–2026
- [x] `main.py` — ponto de entrada com CLI interativa
  - Comandos status, list, footprint, db, help
  - Visualização do fluxo de negócios no console

### Em andamento / Próximos passos

- [x] Popular `KNOWN_AGENTS` / `RETAIL_AGENTS` via módulo centralizado (`corretoras.py`)
- [x] Validar valores de TradeType contra dados observados (2 = Compra, 3 = Venda)
- [x] Adicionar gravação de logs persistentes em arquivo (`logs/profitdll_live.log` com interceptação global de exceções e `TeeLogger`)
- [x] Normalização de escala de preço por ativo (`PRICE_SCALE_BY_PREFIX` em `config.py` + `profit_bridge.py`), corrigindo a precificação do Mini Índice / Índice Cheio (`WIN`/`IND` × 5 vs ticks da DLL)

---

## Fase 2 — Análise de Padrões Offline & Clusterização ML ✅ (Núcleo Concluído)

**Objetivo:** Analisar o dataset acumulado para identificar padrões comportamentais estatisticamente significativos: perfis de agentes (K-Means), segregação CVD (Institucional vs Varejo) e estrutura de mercado.

**Status Atual:** **ENTREGUE / EM CALIBRAÇÃO CONTÍNUA**
Superamos a perfilagem básica implementando Inteligência Quantitativa Não-Supervisionada e segregação analítica:
- [x] **`corretoras.py`**: Mapeamento unificado dos códigos B3 para nomes reduzidos (ex: `85 -> BTG`, `1618 -> UBS`).
- [x] **`analytics_engine.py`**: Cálculo de CVD segregado por tamanho de lote (`cvd_varejo` $\le 2$ vs `cvd_big` $\ge 20$) e extração de features estatísticas.
- [x] **`ml_behavior_analyzer.py`**: Algoritmo **K-Means Clustering** categorizando diariamente os players em 3 perfis quantitativos (`⚡ HFT/MM`, `🏛️ Big Player Direcional`, `🦐 Varejo/Passivo`).

### Próximo passo de calibração histórica (após 20-30 dias de pregão acumulados)
- Afinar limiares estatísticos de Icebergs e acurácia de reversões contrárias ao Varejo.

#### Perfilagem de Agentes (Implementado via K-Means e Engine)

```python
# Para cada agente, calcular por dia:
# - Posição líquida (buy_qty - sell_qty)
# - Taxa de agressão (negócios agressivos / total de negócios)
# - Preço médio ponderado por volume (VWAP dos seus preenchimentos)
# - Janelas de atividade (em que horários do dia são mais ativos)
# - Distribuição de tamanho de lote (histograma dos tamanhos de ordem)
# - Correlação com a direção do preço (estão certos?)
```

**Saída:** tabela `agent_profiles` com scores de estabilidade e tags de classificação (HFT, institucional, varejo, formador de mercado).

#### Fingerprinting de HFT

Algoritmos de HFT deixam assinaturas identificáveis:
- **Uniformidade de lote**: sempre operam o mesmo tamanho de lote (5, 10, 50 contratos)
- **Afinidade por nível de preço**: concentram atividade em números redondos ou offsets específicos
- **Renovação rápida**: cancelam e re-inserem ordens em milissegundos
- **Padrões de horário**: atividade concentrada em minutos específicos (ex: janelas de leilão)
- **Correlação com preço**: compram antes do preço subir, vendem antes de cair — com precisão de sub-segundo

```sql
-- Exemplo: encontrar agentes com lotes uniformes (possível HFT)
SELECT buy_agent,
       STDDEV(qty) / AVG(qty) AS coef_variacao_lote,
       COUNT(*) AS negócios
FROM trades
WHERE trade_type = 2  -- agressão compradora
  AND ts::date >= CURRENT_DATE - 30
GROUP BY buy_agent
HAVING COUNT(*) > 500
ORDER BY coef_variacao_lote ASC;
```

#### Detecção de Iceberg

```sql
-- Encontrar renovações de offer_id (mesmo offer_id aparece várias vezes no mesmo preço)
SELECT offer_id, ticker, price, side, COUNT(*) AS renovacoes, SUM(qty) AS qty_total
FROM book_events
WHERE action = 0  -- ADD
  AND offer_id IS NOT NULL
GROUP BY offer_id, ticker, price, side
HAVING COUNT(*) >= 3  -- config: iceberg_min_renewals
ORDER BY renovacoes DESC;
```

Icebergs detectados são gravados na tabela `icebergs`. Sessões em tempo real subsequentes podem alertar quando um nível de preço de iceberg conhecido é atingido.

#### Calibração de Sinal de Varejo

Calcular a acurácia histórica de sinais contrários ao varejo:
- Quando os `RETAIL_AGENTS` têm grande imbalance líquido em uma direção, o mercado se move contra eles?
- Calcular taxa de acerto, tamanho médio do movimento, tempo até o desfecho em todas as instâncias históricas

Essa calibração determina os valores de limiar em `ANALYSIS` no config.

---

## Fase 3 — Motor de Sinais em Tempo Real 🟡 (Iniciada & Em Operação via `ml_live_predictor.py`)

**Objetivo:** Aplicar os padrões aprendidos em tempo real durante a sessão de trading. Gerar alertas visualmente instantâneos e persistir registros auditáveis na tabela `signals`.

**Status Atual:** **EM PRODUÇÃO / EXPANSÃO DE SINAIS**
Adiantamos a criação do motor preditivo em tempo real com o módulo **`ml_live_predictor.py`**:
- [x] **Loop de Monitoramento Real-Time (`loop_monitoramento`)**: Polling contínuo em janelas móveis (ex: 5 min a cada 10s) sem sobrecarregar a memória do coletor C++.
- [x] **Gravação Auditável no Banco com `max_ts`**: Sinais são registrados diretamente no PostgreSQL (`signals`) utilizando o horário exato do último negócio da B3 (`max_ts`), eliminando o bug de carimbos irreais (`NOW()`).
- [x] **Regras Preditivas Microestruturais Ativas**:
  - `ABSORCAO_VENDEDORA` / `ABSORCAO_COMPRADORA` (Big Players agredindo pesado sem deslocar o preço).
  - `DISTRIBUICAO_TOPO` / `ACUMULACAO_FUNDO` (Divergências extremas de agressão entre Varejo e Big Players).
  - `IMPULSO_COMPRADOR` / `IMPULSO_VENDEDOR` (Rompimento agressivo com alto deslocamento `delta_p`).

### Próximos passos na Fase 3
- [ ] Conectar os disparos do `ml_live_predictor.py` com envio de notificações push/Telegram.
- [ ] Implementar a overlay interativa ("Diário do Trader") para rotular acertos/erros no terminal.

### `signal_engine.py` / `ml_live_predictor.py` (Arquitetura Ativa)

Roda em paralelo ou em rotinas programadas. Assina e consulta dados processados. Avalia regras a cada tick/janela.

#### Tipos de Sinal (Implementados & Planejados)

| Sinal | Gatilho | Direção |
|---|---|---|
| `retail_contrarian` | Saldo líquido de varejo ultrapassa limiar na direção D | Oposta a D |
| `iceberg_detectado` | offer_id no preço P renova ≥ N vezes | Direção passiva em P |
| `iceberg_absorvido` | Iceberg em P é totalmente consumido | Rompimento através de P |
| `divergencia_cvd` | Preço em nova máxima/mínima mas CVD não confirma | Contra o movimento do preço |
| `virada_agente` | Grande agente institucional reverte posição líquida durante o pregão | Com a reversão |
| `sweep_detectado` | Múltiplos níveis de preço consumidos em < 500ms | Com a direção do sweep |
| `parede_surgiu` | Grande quantidade repentina em nível único | Repique esperado |
| `parede_removida` | Grande ordem passiva retirada sem execução | Possível armadilha |

#### Schema de Sinais (já em schema.sql)

```sql
INSERT INTO signals (session_id, ticker, ts, signal_type, direction,
                     price_at_signal, context)
VALUES (..., 'iceberg_absorvido', 1, 5248.50,
        '{"offer_id": 12345, "renovacoes": 7, "total_absorvido": 3500,
          "buy_agent": 386, "cvd_no_sinal": +1234}'::jsonb);
```

#### Diário do Trader

Uma overlay leve de CLI/web (ou exportação de notas do ProfitPro) que mostra:
- Sinais ativos em tempo real
- Prompt "Você concordou? S/N" após cada sinal
- Medição automática do desfecho (para onde o preço foi 30s/60s/5min após o sinal)
- Painel de acurácia por tipo de sinal

Esse loop de feedback é os dados de treinamento para a Fase 4.

---

## Fase 4 — Camada de IA / Machine Learning

**Objetivo:** Passar de sinais baseados em regras para reconhecimento de padrões aprendidos. Usar desfechos históricos de sinais para treinar modelos que pontuam novos sinais.

**Pré-requisito:** 3–6 meses de dados de sinais rotulados (trader_agrees + outcome_pts na tabela `signals`).

### Abordagens (a avaliar)

#### Aprendizado Supervisionado — Pontuação de Sinais

Treinar um classificador em sinais onde `trader_agrees` e `outcome_pts` são conhecidos:

```python
# Features por sinal:
# - CVD no momento do sinal
# - Imbalance do book (5 níveis de profundidade)
# - Contagem de icebergs ativos + tamanho total
# - Saldo líquido dos top 3 agentes
# - Horário do dia
# - Volatilidade (equivalente ao ATR dos ticks recentes)
# - Spread
# - Distância de números redondos
#
# Alvo: outcome_pts (regressão) ou sinal(outcome) (classificação)
```

Modelos a experimentar (em ordem de complexidade):
1. **Regressão logística / modelo linear** — baseline interpretável
2. **Gradient boosting (XGBoost/LightGBM)** — lida bem com interações não lineares
3. **LSTM em sequências de tick** — captura contexto temporal (ex: acumulação ao longo de 10 minutos)

#### Não supervisionado — Detecção de Regime

Agrupar sessões de mercado por similaridade comportamental:
- "Dia de tendência com HFT" vs "Dia movido por notícia" vs "Dia choppy de baixo volume"
- Limiares de sinal diferentes para regimes diferentes

#### Detecção de Anomalia

Sinalizar sessões ou janelas de tempo onde o comportamento de agentes desvia significativamente dos baselines históricos — possível "fluxo informado" ou posicionamento pré-anúncio.

#### Contexto de Mercado & Correlação Cross-Asset (`Macro Context Engine`)

Integrar variáveis exógenas e de contexto macroeconômico global em tempo real para permitir que o sistema diferencie operações rápidas de scalping (5 a 8 pontos) de operações direcionais longas / alongamento de posição (`Trend Following` com alvos de 30, 50+ pontos no WDO):
- **Correlação DXY & Treasuries (US 10Y/2Y)**: Avaliar a tendência global do Índice Dólar (`DXY`) e dos juros americanos. Se o fluxo microestrutural der sinal de compra e o `DXY` / `US 10Y` estiverem em forte alta, classificar a operação como `HIGH CONVICTION / TREND LONG`.
- **Curva de Juros DI Futuro (`DIF26`, `DIF27`, `DIF29`)**: Monitorar a inclinação e variação da curva de juros nacional. Aberturas de taxa DI impulsionam compras institucionais de hedge no Dólar e pressionam o Índice (`WIN`).
- **Calendário Econômico & Trava de Volatilidade (`News Shield`)**: Alimentar o sistema com horários de indicadores Tier-1 (Payrolls, CPI, Copom, FOMC) para suspender novas entradas 5 minutos antes da divulgação (`Debounce / Shield` anti-slippage).
- **Commodities (`Brent/Minério`) & Heatmap das Blue Chips (`WIN`)**: Para operações no Mini Índice, validar se o fluxo de agressão é corroborado pelo saldo à vista nas principais ações (`ITUB4`, `PETR4`, `VALE3`).
- **Relógio Mundial de Bolsas & Janelas Críticas de Abertura (`Global Market Clock & Liquidity Shocks`)**: Monitoramento contínuo das aberturas e fechamentos das principais praças financeiras do mundo (Wellington, Tóquio, Londres/Europa, Nova York/NYSE/Nasdaq, Chicago/CME) em sincronia com o horário de Brasília (`B3`). O modelo deverá alertar e reponderar o risco em janelas de choque de fluxo:
  * **09:00 - 09:30 BRT**: Abertura do Futuro/Vista B3 sob influência dos futuros americanos e sessões europeias em andamento.
  * **10:30 - 11:30 BRT (`US Open Shock`)**: Abertura do mercado à vista em Wall Street (`NYSE / Nasdaq`). Altíssima probabilidade de reversão abrupta de fluxo no Mini Dólar e Mini Índice devido ao rebalanceamento de portfólios institucionais globais (uma posição comprada pode virar vendida em segundos). Ativar modo `Alert / Protective Trailing Stop`.
  * **16:00 - 17:00 BRT**: Fechamento dos mercados europeus e ajuste final em Wall Street.
- **Janelas Operacionais da Ptax BCB (`PTAX Windows & Dealer Battle Engine`)**: O Dólar (`WDO/DOL`) sofre forte influência das 4 consultas diárias do Banco Central para o cálculo da taxa oficial (`10:00-10:10`, `11:00-11:10`, `12:00-12:10`, `13:00-13:10` + divulgação às `13:30`), com volatilidade extrema no último dia útil do mês (`Briga pela Ptax Mensal`). O ML deverá incorporar features temporais específicas para mapear o comportamento institucional dos *dealers de câmbio*:
  * **`time_to_next_ptax` (Pré-PTAX Push)**: Nos 5 minutos que antecedem cada janela (`09:55`, `10:55`, `11:55`, `12:55`), detectar puxadas ou marcações direcionais provocadas por tesourarias bancárias querendo influenciar a média oficial do BC (`Impulso Ptax de Alta Convicção`).
  * **`is_ptax_window` (PTAX Battle)**: Durante os 10 minutos da consulta do BC, recalibrar os limiares de absorção para acomodar o aumento súbito de ordens Iceberg e lotes gigantescos no book.
  * **`time_since_ptax` (Exaustão Pós-PTAX / Hangover)**: Assim que a janela do BC fecha (`10:11`, `11:11`, `12:11`, `13:11`), monitorar o cessar das agressões institucionais para capturar operações de reversão à média (`Mean Reversion / Ptax Hangover`).
- **Ajuste Diário da B3 & Janela de Formação (`B3 Clearing Adjustment & Mark-to-Market Engine`)**: O Preço de Ajuste é o equalizador financeiro de todas as posições em aberto no Dólar Futuro (`WDO/DOL - R$ 10,00/pt no WDO` e `WIN/IND`). O modelo ML incorporará duas mecânicas quantitativas fundamentais atreladas ao Ajuste:
  * **`is_ajuste_window` (Ajuste Battle — 15:50 às 16:00 BRT no Dólar / 17:00 às 17:15 BRT no Índice)**: Durante os 10 minutos de apuração da média ponderada dos negócios pela B3, tesourarias institucionais entram em forte disputa para empurrar ou defender a cotação de ajuste. O modelo deverá tratar agressões nessa janela com peso extra (`Ajuste Push de Alta Convicção`).
  * **`distance_to_prev_ajuste` (Defesa Institucional do Ajuste Anterior)**: A linha do Preço de Ajuste do dia anterior atua como o suporte/resistência mais respeitado da B3. Quando o preço se aproximar do Ajuste Anterior (`+/- 2,5 pontos no WDO`), o modelo ativará o modo de detecção de absorção institucional (`Ajuste Shield / Mean Reversion na Defesa de Clearing`).
- **Monitoramento Cruzado Dólar Cheio vs Mini (`Cross-Market Smart Money Tracking — DOL vs WDO`)**: Embora o Mini (`WDO`) concentre a maior liquidez e velocidade na descoberta do preço (`Price Discovery`), as grandes tesourarias bancárias e fundos estrangeiros continuam operando lotes maciços de hedge e obrigações comerciais no Dólar Cheio (`DOL` - lotes de 5 contratos, equivalente a 25 minis cada). O modelo deverá realizar o cruzamento contínuo das agressões entre `DOL` e `WDO`:
  * **`dol_wdo_divergence` (Falso Rompimento / Armadilha HFT)**: Se o Mini (`WDO`) romper topo com agressão compradora, mas o Cheio (`DOL`) apresentar fortes vendas ocultas/absorção institucional por grandes players (`UBS, Morgan, etc.`), classificar o rompimento do WDO como falso (`Fakeout / Retail Trap`) e vetar compras.
  * **`dol_wdo_sync` (Convicção Máxima de Tesouraria)**: Quando tanto o Mini (`WDO`) quanto o Cheio (`DOL`) explodirem na mesma direção com CVD institucional fortemente alinhado, sinalizar entrada direcional de altíssima confiança (`High Conviction Trend / Smart Money Sync`).
- **Cálculo do `Macro-Micro Score`**: Cruzamento quantitativo entre o gatilho microestrutural (ex: Absorção no Book) e o viés macro (Vento a Favor vs Vento Contra) para ajuste dinâmico de metas de ganho e Stop Loss.

### Infraestrutura

- **Treinamento:** offline, agendado (noturno ou semanal)
- **Inferência:** tempo real, modelo carregado como artefato no início da sessão
- **Versionamento de modelo:** rastrear qual versão do modelo gerou cada sinal
- **Testes A/B:** rodar múltiplas versões de modelo em paralelo, comparar desfechos

---

## Fase 5 — Automação (Validação Primeiro)

**Objetivo:** Fechar o loop do sinal à ordem. Conectar o motor de sinais ao roteamento de ordens da DLL.

**Pré-requisito:** Modelos da Fase 4 com acurácia comprovada ao longo de 6+ meses de operação ao vivo com validação manual. O trader deve aprovar explicitamente cada estratégia antes da automação.

> ⚠️ **Filosofia:** Automatizar apenas o que foi validado manualmente. O sistema gera sinais → trader valida → padrões que funcionam consistentemente → candidatos para automação. Nunca automatizar um novo tipo de sinal sem um período de validação manual.

### Protocolo de Validação (antes de qualquer automação)

1. Motor de sinais roda em "modo papel" por mínimo de 30 dias
2. Mínimo de 100 instâncias disparadas por tipo de sinal
3. Taxa de acerto significativamente acima do aleatório (teste de significância estatística)
4. Trader rotula explicitamente cada tipo de sinal como "aprovado para automação"
5. Limites de tamanho de posição definidos de forma conservadora (1 contrato inicialmente)

### Roteamento de Ordens

Usa `DLLInitializeLogin` (em vez de `DLLInitializeMarketLogin`) para habilitar o roteamento de ordens.

```python
# Pseudocódigo — Fase 5
if sinal.score > LIMIAR and sinal.tipo in SINAIS_APROVADOS:
    ordem = Ordem(
        ticker     = sinal.ticker,
        direcao    = sinal.direcao,
        qtd        = gestor_risco.dimensionar(sinal),
        stop_pts   = 5,          # stop máximo: 5 pontos
        alvo_pts   = sinal.alvo_pts,
    )
    bridge.enviar_ordem(ordem)
```

### Gestão de Risco

- Stop fixo: 5 pontos por operação (corresponde ao stop máximo declarado pelo trader)
- Limite de perda diária: halt configurável por drawdown
- Limite de posição: máximo N contratos abertos simultaneamente
- Circuit breaker: interromper automação após 3 perdas consecutivas

---

## O que não está no escopo (decisões explícitas)

- **Análise gráfica e indicadores**: Este sistema opera inteiramente em fluxo de ordens. Sem médias móveis, sem padrões de candle, sem análise técnica. Histórico de preço é usado apenas como contexto (ex: distância da máxima/mínima recente).
- **Mercados de crypto**: O principal valor deste sistema é a identificação de agente, que existe apenas na B3. Mercados de crypto são anônimos e estruturalmente diferentes.
- **Múltiplas bolsas**: Foco em futuros da B3 (WDO/DOL/DOLPRO). Ações e opções têm microestrutura diferente.
- **Interface gráfica/dashboard**: O trader usa o ProfitPro como interface principal. Este sistema é um motor de backend. Saída no CLI e queries no banco são suficientes para as Fases 1–3. Fase 4+ pode adicionar uma overlay mínima.

---

## Estimativa de Cronograma & Status Real

| Fase | Gatilho | Status / Progresso Atual |
|---|---|---|
| **Fase 1 (Coleta de Dados)** | Primeira conexão com a DLL | ✅ **100% Concluída** |
| **Fase 2 (Padrões Offline & ML)** | 20–30 dias de dados acumulados | ✅ **Núcleo Concluído** (`K-Means` + `corretoras.py`). Em calibração histórica contínua. |
| **Fase 3 (Motor Real-Time)** | Padrões da Fase 2 calibrados | 🟡 **Em Produção / Operação** (`ml_live_predictor.py` com `max_ts` ativo). |
| **Fase 4 (ML Supervisionado)** | 3–6 meses de sinais rotulados | ⏳ Aguardando acúmulo de histórico na tabela `signals` |
| **Fase 5 (Automação de Ordens)** | Fase 4 validada pelo trader | ⏳ Planejado após validação estatística ao vivo |

---

## Questões em aberto

1. **Estabilidade do ID de agente**: Os IDs numéricos de agentes mudam entre datas de vencimento dos contratos? Se sim, o mapeamento precisa ser reconstruído a cada vencimento.
2. **Frequência do `TNewDailyCallback`**: Com que exatidão ele dispara? A cada minuto? A cada negócio? Isso afeta como usamos os dados de delta diário.
3. **DOLPRO vs WDO/DOL**: O DOLPRO é um instrumento composto — ele expõe a mesma granularidade de dados de agente que os contratos subjacentes?
4. **Profundidade histórica**: Até onde o `GetHistoryTrades` realmente vai? A documentação da Nelogica diz ~10 dias por requisição, mas qual é o máximo no servidor?
5. **Motor de replay**: Para backtesting de estratégias de sinal em dados históricos sem conexão ao vivo com a DLL — requer uma camada de simulação que reproduz `trades` e `book_events` do PostgreSQL na ordem temporal correta.
