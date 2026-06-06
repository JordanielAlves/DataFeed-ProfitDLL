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

- [ ] Popular `KNOWN_AGENTS` no config.py após primeira sessão ao vivo
- [ ] Validar valores de TradeType contra dados observados
- [ ] Mapear `RETAIL_AGENTS` após identificar IDs de corretoras de varejo
- [ ] Adicionar gravação de logs em arquivo (atualmente apenas no console)

---

## Fase 2 — Análise de Padrões Offline

**Objetivo:** Analisar o dataset acumulado para identificar padrões comportamentais estatisticamente significativos: fingerprints de HFT, assinaturas de iceberg, perfis de agentes, estrutura de mercado.

**Pré-requisito:** Mínimo de 20–30 dias úteis de dados no banco.

### `pattern_analyzer.py` (planejado)

Um job em lote que roda diariamente (após o fechamento do mercado) sobre os dados do dia anterior.

#### Perfilagem de Agentes

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

## Fase 3 — Motor de Sinais em Tempo Real

**Objetivo:** Aplicar os padrões aprendidos em tempo real durante a sessão de trading. Gerar alertas. Construir um loop de feedback entre os sinais do sistema e os desfechos do trader.

**Pré-requisito:** Padrões calibrados da Fase 2.

### `signal_engine.py` (planejado)

Roda junto com o coletor. Assina os mesmos eventos. Avalia regras a cada tick.

#### Tipos de Sinal

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

## Estimativa de Cronograma

| Fase | Gatilho | Duração estimada |
|---|---|---|
| Fase 1 | Primeira conexão com a DLL | ✅ Concluída |
| Fase 2 | 20–30 dias de dados | 2–4 semanas de desenvolvimento |
| Fase 3 | Padrões da Fase 2 calibrados | 3–6 semanas de desenvolvimento |
| Fase 4 | 3–6 meses de sinais rotulados | 4–8 semanas de desenvolvimento + 3–6 meses de coleta |
| Fase 5 | Fase 4 validada | Contínuo — validar antes de cada automação |

---

## Questões em aberto

1. **Estabilidade do ID de agente**: Os IDs numéricos de agentes mudam entre datas de vencimento dos contratos? Se sim, o mapeamento precisa ser reconstruído a cada vencimento.
2. **Frequência do `TNewDailyCallback`**: Com que exatidão ele dispara? A cada minuto? A cada negócio? Isso afeta como usamos os dados de delta diário.
3. **DOLPRO vs WDO/DOL**: O DOLPRO é um instrumento composto — ele expõe a mesma granularidade de dados de agente que os contratos subjacentes?
4. **Profundidade histórica**: Até onde o `GetHistoryTrades` realmente vai? A documentação da Nelogica diz ~10 dias por requisição, mas qual é o máximo no servidor?
5. **Motor de replay**: Para backtesting de estratégias de sinal em dados históricos sem conexão ao vivo com a DLL — requer uma camada de simulação que reproduz `trades` e `book_events` do PostgreSQL na ordem temporal correta.
