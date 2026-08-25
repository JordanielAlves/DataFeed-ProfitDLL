# Diretrizes e Regras do Projeto ProfitDLL / DataFeed B3

## Regras Obrigatórias de Escala, Armazenamento e Exibição de Preço

1. **PADRONIZAÇÃO DE ARMAZENAMENTO NO BANCO DE DADOS (`fluxo_ordens`):**
   - **Tabelas de Alta Frequência (`trades` e `book_events`):** Armazenam o preço nativo bruto da DLL para máxima performance de inserção.
     - `WDO` / `DOL`: Preço bruto = **10× a cotação real da B3** (ex: `price = 51650.00` corresponde a **`5.165,00`** pontos).
     - `WIN` / `IND`: Preço bruto = cotação em pontos (escala 1×).
   - **Tabelas Quantitativas e Analíticas (`signals` e `daily_ohlc`):**
     - A coluna `price_at_signal` na tabela `signals` armazena **SEMPRE EM PONTOS REAIS DA B3** (ex: `5165.00`).
     - As colunas `open_p, high_p, low_p, close_p` em `daily_ohlc` armazenam **SEMPRE EM PONTOS REAIS DA B3**.

2. **REGRA INVIOLÁVEL DE EXIBIÇÃO EM TELA / LOGS / RELATÓRIOS:**
   - **TODA E QUALQUER EXIBIÇÃO DE COTAÇÃO AO USUÁRIO DEVE ESTAR EM PONTOS REAIS FORMATADOS NO PADRÃO BRASILEIRO:**
     - Exemplo Dólar: **`5.160,00`**, **`5.160,50`**, **`5.161,00`**, **`5.161,50`**.
     - Exemplo Índice: **`134.500`**, **`134.505`**.
     - Exemplo Juros: **`13,725%`**.
   - Utilize sempre o módulo centralizador `price_utils.py` (`from price_utils import to_real_points, format_price_b3`).
   - **NUNCA** apresente cotações em notação crua/americana como `5165.0` ou `51650.00` em relatórios, prints ou mensagens de Telegram.

2. **CONSULTA OBRIGATÓRIA ANTES DE RESPONDER:**
   - Antes de responder qualquer pergunta sobre cotações, faixas de preço, aberturas, máximas, mínimas ou rompimentos em determinado dia/horário, o agente **DEVE SEMPRE** executar uma consulta SQL via Python (`psycopg2` ou `pandas`) no banco de dados para checar:
     ```sql
     SELECT min(price)/10.0, max(price)/10.0 
     FROM trades 
     WHERE ticker = 'WDOQ26' 
       AND ts >= 'DATA_INICIO' AND ts <= 'DATA_FIM';
     ```
   - NUNCA adivinhe cotações nem reutilize números de dias anteriores (ex: `5420.00` de outras sessões ou testes antigos) quando estiver analisando o pregão do dia.

3. **ANÁLISE DE FLUXO DE ORDENS E MICROESTRUTURA:**
   - Quando o usuário solicitar análise forense ou tick a tick de um intervalo de tempo, utilize sempre a skill `profitdll-market-analysis` em `.agents/skills/profitdll-market-analysis/SKILL.md`.
   - Estruture a análise cobrindo todos os pilares:
     1. **Resumo Direcional:** Abertura, máxima, mínima e fechamento do intervalo em pontos reais.
     2. **Divergências Mini vs Cheio (`WDO` vs `DOL`):** Liderança de movimento, divergência de delta (CVD) e volume no segundo a segundo.
     3. **Atuação de Players (`agent_id`):** Identificar parcerias ou agressões isoladas (`trade_type = 2` compra agressiva, `trade_type = 3` venda agressiva).
     4. **Absorção Passiva:** Localizar onde as agressões pararam de deslocar o preço e quem estava no book passivo na contraparte.
     5. **Acionamento de Stops:** Identificar varreduras rápidas (`sweeps`) de múltiplos níveis em milissegundos.
     6. **Liquidez do Book (`book_events`):** Profundidade, lote médio (`avg_lote`) e taxa de renovação/cancelamento (`action`).
