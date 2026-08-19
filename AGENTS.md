# Diretrizes e Regras do Projeto ProfitDLL / DataFeed B3

## Regras Obrigatórias de Escala e Cotações de Preço (`trades` e `book_events`)
1. **ESCALA DE PREÇO NO BANCO DE DADOS (PostgreSQL `fluxo_ordens`):**
   - Os preços dos ativos na tabela `trades` e `book_events` são armazenados conforme o fator de escala ou formato em inteiros da DLL/Banco.
   - **MUITO IMPORTANTE:** Para os contratos `WDO` (Mini Dólar) e `DOL` (Dólar Cheio), o valor armazenado na coluna `price` no banco de dados é **10 vezes** o valor real da cotação em pontos da B3!
     - Exemplo: `price = 51150.00` no banco corresponde a **`5.115,00`** pontos na B3.
     - Exemplo: `price = 51340.00` no banco corresponde a **`5.134,00`** pontos na B3.
     - Exemplo: `price = 50995.00` no banco corresponde a **`5.099,50`** pontos na B3.
   - Para os contratos `WIN` (Mini Índice) e `IND` (Índice Cheio), consulte a regra em `config.PRICE_SCALE_BY_PREFIX` (`WIN: 5`), pois a DLL pode retornar em ticks.
   - **NUNCA** apresente ao usuário os valores brutos ou sem conversão sem antes verificar se o número faz sentido para a cotação real daquele dia. NUNCA mencione cotações sem dividir por 10 (para WDO/DOL) ou sem validar a escala correta.

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
