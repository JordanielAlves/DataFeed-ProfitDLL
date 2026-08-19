---
name: profitdll-market-analysis
description: Skill especializada na análise quantitativa e forense de fluxo de ordens tick a tick e microestrutura de mercado via ProfitDLL/PostgreSQL (WDO, DOL, WIN, IND). Ensina como consultar e interpretar escalas de preço, pontos vs ticks, parcerias de players, absorções passivas, divergências Mini vs Cheio e liquidez do book, além de disponibilizar o script automatizado market_inspector.py. Use sempre que o usuário pedir análises do pregão do dia, resumo diário, ou verificação de um trecho/janela do mercado.
---

# ProfitDLL & B3 Market Analysis Skill (`profitdll-market-analysis`)

Esta skill define o padrão quantitativo e forense para analisar o fluxo de ordens e microestrutura dos contratos futuros da B3 capturados em tempo real pelo `ProfitDLL` (tabelas `trades` e `book_events` no PostgreSQL).

---

## 1. Regra de Ouro: Escala no Banco, Pontos e Ticks

### A. Dólar Futuro (`WDO` / `DOL`)
No banco de dados (`fluxo_ordens`), a coluna `price` armazena as cotações multiplicadas por 10 (em décimos inteiros) para evitar erros de precisão decimal:
- **Cotação Real B3 (`Pontos`)** = `price / 10.0`
- **1 Ponto de Dólar** = `2 Ticks` (cada tick é `0,50` ponto = `R$ 5,00` por contrato de WDO / `R$ 25,00` no DOL).
- **Relação com o Banco**: Cada **10 unidades** brutas na coluna `price` correspondem a **1,00 ponto** (ou **2 ticks**).
  - Exemplo: Banco `51150.00` → Cotação B3: **`5.115,00`**
  - Exemplo: Variação de `51050.00` para `51200.00` (`+150` no banco) = **`+15,00 pontos`** = **`30 ticks`**.

> ⚠️ **TERMINOLOGIA CRÍTICA**: Nunca chame unidades brutas do banco de "pontos". Sempre divida `price / 10.0` para falar em Pontos e multiplique os pontos por 2 para falar em Ticks (`0,50 pt`).

### B. Índice Futuro (`WIN` / `IND`)
- A DLL retorna em ticks de 5 pontos. Verificar `config.PRICE_SCALE_BY_PREFIX` (`WIN: 5`), convertendo conforme a pontuação real da B3 (`1 tick = 5 pontos`).

---

## 2. Padrão Obrigatório: Reconciliação Dia Inteiro vs. Janela Recortada

Sempre que o usuário solicitar análise de uma janela específica do dia (ex: *09:30 às 10:00*), o agente **DEVE OBRIGATORIAMENTE** apresentar primeiro os extremos oficiais do **Pregão Completo (`09:00 - 18:00`)** antes de apresentar os números da **Janela Recortada**:

1. **Pregão Completo**: Abertura (`09:00`), Mínima do Dia, Máxima do Dia e Fechamento.
2. **Janela Analisada**: Preço no início do trecho, Mínima do trecho, Máxima do trecho e Preço no fim do trecho.

Isso garante que os valores da tela da plataforma Profit do usuário (que mostram a Máxima e Mínima do dia) coincidam perfeitamente com o relatório, deixando claro o que aconteceu na variação total do dia e o que aconteceu dentro do recorte analítico.

---

## 3. Uso do Script Automatizado (`market_inspector.py`)

Para evitar consultas ad-hoc manuais e padronizar relatórios com os nomes reais das corretoras (via `corretoras.py`), utilize o script incluso na skill:

### Caminho do Script
`python .agents/skills/profitdll-market-analysis/scripts/market_inspector.py`

### Exemplos de Comando no Terminal

- **Resumo Completo do Dia (Abertura, Máxima, Mínima, Volume Total, CVD e Ticks):**
  ```bash
  python .agents/skills/profitdll-market-analysis/scripts/market_inspector.py --ticker WDOQ26 --date 2026-07-16 --daily
  ```

- **Análise Forense de Trecho/Janela com Ranking de Players:**
  ```bash
  python .agents/skills/profitdll-market-analysis/scripts/market_inspector.py --ticker WDOQ26 --date 2026-07-16 --start 09:30 --end 10:00
  ```

- **Análise Completa (Dia + Trecho simultaneamente):**
  ```bash
  python .agents/skills/profitdll-market-analysis/scripts/market_inspector.py --ticker WDOQ26 --date 2026-07-16 --start 09:30 --end 10:00 --daily
  ```

---

## 4. Estrutura do Relatório Analítico (6 Pilares da Microestrutura)

Ao responder ao usuário, estruture a análise cobrindo sistematicamente os 6 pilares abaixo com base no retorno do `market_inspector.py` e consultas SQL adicionais:

1. **Resumo Direcional e Amplitude (`Pontos` e `Ticks`):**
   - Apresente a fotografia do pregão inteiro vs. a fotografia da janela analisada.
   - Calcule a amplitude em pontos e em ticks.

2. **Divergência de Fluxo (Mini vs Cheio — `WDO` vs `DOL`):**
   - Verifique quem liderou o movimento de rompimento ou quem absorveu/defendeu níveis críticos.
   - O Mini puxou na frente por agressão direta enquanto o Cheio ficou com CVD neutro/zero? Or o Cheio bateu pesado na resistência e abortou o movimento? (Lembrar de multiplicar o nocional do DOL por 5x na comparação).

3. **Atuação de Players (Parcerias vs Agressão Solo):**
   - Identifique os grandes players no topo do ranking líquido (`net = compra - venda`).
   - Verifique se houve consórcio/parceria institucional (ex: *Renascença + Ideal + Morgan + XP* atuando simultaneamente na ponta compradora) ou se foi agressão isolada.

4. **Absorção Passiva (`Passive Absorption`):**
   - Localize players com alto saldo vendedor líquido durante uma puxada de alta (ex: *BTG Pactual, Ágora, UBS absorvendo passivamente no ask*), ou vice-versa.

5. **Stop de Posição e Virada de Mão:**
   - Identifique corretoras com giro altíssimo e saldo quase neutro/invertido na puxada, indicando stops forçados a mercado e virada de mão na direção da tendência.

6. **Liquidez e Estado do Book (`book_events`):**
   - Avalie se o deslocamento foi limpo em book pesado ou se ocorreu em book rasgado/rarefeito onde a razão de pontos por lote agredido dobrou.

---

## 5. Checklist de Verificação do Agente
- [ ] Rodou `market_inspector.py` para obter dados matematicamente exatos?
- [ ] Diferenciou com clareza os extremos do **Pregão Completo** dos extremos do **Recorte Temporal**?
- [ ] Aplicou a conversão de escala correta (`price / 10.0` no WDO/DOL) e usou a terminologia exata de **Pontos** vs **Ticks (`0,50 pt`)**?
- [ ] Checou o fluxo cruzado `WDO` + `DOL` para apontar divergências?
- [ ] Identificou nomes das corretoras e parcerias/absorções com base nos saldos líquidos?
