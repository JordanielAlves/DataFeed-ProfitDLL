# 📘 Manual de Operação e Rotina Matinal — ProfitDLL & ML Microstructure

Este manual descreve o passo a passo diário para inicialização, monitoramento em tempo real e análise de fechamento do sistema quantitativo de fluxo de ordens (ProfitDLL + PostgreSQL + Machine Learning).

---

## ⏰ 1. Rotina de Abertura do Mercado (08:50 – 08:55)

Antes da abertura do pregão (09:00), prepare a infraestrutura em **dois terminais do PowerShell**:

### 🔹 Terminal 1 — Captura de Dados (Data Recorder & DLL Bridge)
Responsável por conectar na DLL da Nelogica, assinar o Market Data e gravar todos os negócios (*Trades*), livro de ofertas (*Book Events*) e agressões de corretoras (*Agent Daily*) no PostgreSQL.

1. Abra o PowerShell na pasta do projeto:
   ```powershell
   cd C:\DEV\ProfitDLL
   ```
2. Execute o capturador principal:
   ```powershell
   python.exe .\main.py
   ```
3. **O que verificar na tela:**
   * Você verá mensagens como `[INFO] recorder — Sessão aberta: WDOU26 -> session_id=...`
   * Em seguida: `[CONECTADO]` e `Inscrevendo nos ativos: ['WDOU26', 'WINV26', ...]`
   * O terminal exibirá uma tabela contínua atualizada em tempo real mostrando o **CVD**, **Δ Dia** e **Imbalance** dos ativos. Deixe este terminal aberto e rodando durante todo o pregão.

---

### 🔹 Terminal 2 — Monitor Quantitativo & Alertas ML em Tempo Real
Responsável por rodar o modelo preditivo (`ml_live_predictor.py`), analisando janelas móveis de 5 a 15 minutos para disparar alertas visuais e gravar na tabela `signals` sempre que detectar **Absorção Institucional**, **Exaustão** ou **Rompimento HFT**.

1. Abra um **segundo terminal** do PowerShell na mesma pasta:
   ```powershell
   cd C:\DEV\ProfitDLL
   ```
2. Execute o preditor ao vivo (exemplo para o Dólar `WDOU26`):
   ```powershell
   python.exe .\ml_live_predictor.py --ticker WDOU26 --interval 10 --window 5
   ```
   *(Nota: Se preferir monitorar o Índice Futuro, substitua por `--ticker WINV26`).*

3. **O que esperar na tela:**
   * O script rodará silenciosamente checando o banco de dados a cada 10 segundos.
   * Quando uma anomalia de fluxo ocorrer, um alerta visual de destaque será exibido no terminal e gravado no banco:
     * 🔥 **[ALERTA ML: ABSORÇÃO VENDEDORA INSTITUCIONAL]** (Prob. Reversão > 80%)
     * 🛡️ **[ALERTA ML: ABSORÇÃO COMPRADORA INSTITUCIONAL]** (Prob. Reversão > 80%)
     * ⚡ **[ALERTA ML: IMPULSO COMPRADOR / VENDEDOR]** (Agressão pesada rompendo nível)
     * 🎣 **[ALERTA ML: DISTRIBUIÇÃO TOPO / ACUMULAÇÃO FUNDO]**

---

## ☕ 2. Durante o Pregão (09:00 – 18:00)

* **Nenhuma intervenção manual é necessária no Terminal 1 (`main.py`).** Ele gerencia reconexões automaticamente e faz *flush* dos buffers no PostgreSQL sem travar a DLL.
* No **Terminal 2 (`ml_live_predictor.py`)**, use os alertas quantitativos como **sistema de suporte à decisão** para validar exaustões em suportes/resistências chave do seu gráfico (como em gráficos de pontos 8P ou candles de 15 Minutos).

---

## 🏁 3. Rotina de Fechamento e Análise ML (18:15+)

Após o encerramento do pregão de futuros, encerre a captura no Terminal 1 pressionando `Ctrl + C` e rode os relatórios analíticos de fechamento.

### 🔹 Passo 1: Raio-X de Comportamento dos Agentes (K-Means Clustering) e Preditivo
Para gerar o mapeamento completo do dia de quem operou como **HFT/Market Maker** vs. **Tubarão Institucional**, rode o motor de análise:

```powershell
# Para Dólar Futuro:
python.exe .\ml_behavior_analyzer.py --ticker WDOU26 --action all --barras 15

# Para Índice Futuro:
python.exe .\ml_behavior_analyzer.py --ticker WINV26 --action all --barras 15
```

### 🔹 Passo 2: Verificação de Sinais e Backtest do Dia
Para listar em uma tabela limpa e formatada todos os alertas de microestrutura (Absorção/Exaustão) gerados pelo modelo ML durante o dia:

```powershell
# Para Dólar Futuro:
python.exe .\ml_behavior_analyzer.py --ticker WDOU26 --action signals

# Para Índice Futuro:
python.exe .\ml_behavior_analyzer.py --ticker WINV26 --action signals
```

*(Opção avançada / Consulta direta via linha de comando):*
```powershell
python.exe -c "import psycopg2, warnings, pandas as pd; warnings.filterwarnings('ignore'); from config import DB_DSN; conn = psycopg2.connect(DB_DSN); print(pd.read_sql_query('SELECT TO_CHAR(ts, \'HH24:MI:SS\') AS hora, ticker, signal_type, CASE WHEN direction=1 THEN \'COMPRA (+1)\' ELSE \'VENDA (-1)\' END AS direcao, price_at_signal AS preco FROM signals ORDER BY ts DESC LIMIT 25', conn).to_string(index=False))"
```

### 🔹 Passo 3: Auditoria Forense e Etiquetação Automática MFE/MAE (`Pilar 1 MLOps`)
Para rodar a **etiquetação quantitativa automática (Ground Truth Labeler)** que simula a passagem do tempo tick a tick/segundo a segundo em janelas de 1m, 3m e 5m após cada sinal, gravando as métricas de **MFE** (Excursão Máxima Favorável), **MAE** (Excursão Máxima Adversa) e **Hit Rate do Scalper** (+2.5 pts Gain / -2.0 pts Stop) direto na tabela `signals`:

```powershell
# Etiquetar todos os sinais do dia de hoje com resumo executivo em estilo Powerline:
python.exe .\daily_postmarket_labeler.py

# Etiquetar e recalcular um dia anterior específico testando outros alvos (ex: +3.0 Gain / -1.5 Stop):
python.exe .\daily_postmarket_labeler.py --date 2026-07-16 --recalculate --gain 3.0 --stop 1.5
```
* **O que acontece:** O script altera automaticamente a estrutura do banco (`ALTER TABLE signals ADD COLUMN IF NOT EXISTS mfe_1m...`) se necessário, rotula os sinais e exibe uma tabela de **Performance Executiva em Badges/Cores** no terminal mostrando a taxa de acerto e o retorno médio de cada `signal_type` (incluindo os **Combos de Absorção + Impulso**).

### 🔹 Passo 4: Motor de Re-treinamento Dinâmico de ML (`Pilar 2 MLOps`)
Após executar o etiquetador forense (Passo 3), alimentamos o **Motor Supervisionado de Aprendizado de Máquina** para que ele aprenda quais padrões de fluxo (`CVD_BIG`, `CVD_VAREJO`, `Delta P`, `Total Qty` e `Signal Type`) resultaram em vitórias reais no scalping (+2.5 pts). O modelo treinado é avaliado com **Validação Cruzada Temporal (*Time-Series Split*)** para evitar *vazamento de futuro/look-ahead bias*, e é salvo para uso em tempo real:

```powershell
# Recomendado: Treinar o modelo com TODO o histórico para a IA aprender os ciclos Macro (Harmônicos)
python.exe .\ml_model_trainer.py --splits 5

# ⚠️ ATENÇÃO (OVERFITTING): Evite treinar o modelo usando o filtro "--date YYYY-MM-DD".
# Se você treinar a IA apenas em um único dia que ficou consolidado, a variável "dist_to_macro_harmonic" 
# será ignorada (Relevância 0.0%), pois a IA não terá amplitude suficiente para aprender.
```
* **O que acontece:** O script carrega os sinais auditados do PostgreSQL, treina o classificador quantitativo em blocos temporais progressivos, exibe no terminal o **Ranking de Importância das Features (*Feature Importance*)** em barras visuais e exporta o modelo otimizado e seus metadados para a pasta `models/quant_signals_v1.pkl` e `models/quant_signals_v1.json`.

### 🔹 Passo 5: Operação em Tempo Real com Pontuação de Convicção (`Pilar 3 MLOps`)
Com o modelo treinado salvo em `models/quant_signals_v1.pkl`, o nosso monitor ao vivo (**`ml_live_predictor.py`**) carrega automaticamente a inteligência artificial na inicialização e passa a calcular a **Convicção Quantitativa do ML (`0% a 100%`)** a cada sinal disparado em tempo real:

```powershell
# Executar monitoramento ao vivo com pontuação do modelo ML (Pilar 3 ativo):
python.exe .\ml_live_predictor.py --ticker WDOQ26 --interval 10 --window 5
```
* **O que acontece:** Ao detectar um sinal de absorção ou rompimento, o preditor extrai as variáveis microestruturais instantâneas e consulta a probabilidade de vitória no scalper no modelo supervisionado:
  * 🌟 **Convicção Alta ($\ge 65\%$):** Exibe o alerta em verde **`[ML HIGH CONVICTION ⭐]`**, validando a entrada com suporte quantitativo.
  * ⚠️ **Convicção Baixa ($\le 45\%$):** Exibe alerta em amarelo/vermelho **`[ML LOW CONVICTION ⚠️]`**, avisando o trader sobre risco elevado de stop ou falso rompimento.
  * 📁 O valor numérico (`ml_conviction`) também é salvo na coluna `context` da tabela `signals`, fechando o loop de aprendizado contínuo para a próxima auditoria do Pilar 1!

---

## 🛠️ Guia Rápido de Solução de Problemas (Troubleshooting)

| Sintoma / Erro | Causa Provável | Solução |
| :--- | :--- | :--- |
| `[DESCONECTADO]` em loop no `main.py` | ProfitChart/Nelogica fechado ou DLL sem login | Verifique se o ProfitChart está aberto, logado e com o roteamento ativo. |
| `psycopg2.OperationalError: connection to server failed` | PostgreSQL não está rodando no Windows | Abra o *Serviços do Windows* (`services.msc`) e inicie o serviço `postgresql-x64-16` (ou superior). |
| Falha no flush de agentes (`INSERT tem mais colunas...`) | Desalinhamento entre schema SQL e script Python | Já corrigido na v1.2 do `data_recorder.py`. Certifique-se de estar usando os scripts atualizados na pasta `C:\DEV\ProfitDLL`. |

---

## 🔬 4. Análise Forense & Backtests de Microestrutura (`Skill profitdll-market-analysis`)

Além da rotina diária ao vivo, você possui um conjunto de **ferramentas forenses autônomas** na pasta `.agents/skills/profitdll-market-analysis/scripts/` para auditar movimentos específicos ou rodar simulações quantitativas em feixes de dados passados:

1. **Inspeção Forense de Fluxo de Janela Temporal (`market_inspector.py`)**:
   Gera o relatório completo de agressão por corretora, absorção e divergência WDO vs DOL de qualquer janela (ex: rompimento das 09:30 às 10:00).
   ```powershell
   python.exe .agents\skills\profitdll-market-analysis\scripts\market_inspector.py --ticker WDOU26 --start "2026-07-16 09:30:00" --end "2026-07-16 10:00:00"
   ```

2. **Diagnóstico de Stop vs Agressão Nova (`check_stops.py`)**:
   Verifica o inventário diário acumulado dos players para descobrir se quem puxou a alta estava abrindo posição compradora ou estopando posição vendedora.
   ```powershell
   python.exe .agents\skills\profitdll-market-analysis\scripts\check_stops.py --start "2026-07-16 09:30:00" --end "2026-07-16 10:00:00"
   ```

3. **Backtest Quant V2 (Absorção Institucional + Divergência DOL) (`backtest_absorption_v2.py`)**:
   Simula o modelo de absorção sobre todos os pregões acumulados no banco, checando o ganho em 60 segundos.
   ```powershell
   python.exe .agents\skills\profitdll-market-analysis\scripts\backtest_absorption_v2.py
   ```

4. **Matriz MFE/MAE de Sensibilidade de Alvos (`inspect_mfe_mae.py`)**:
   Analisa quanto o preço anda a favor (Gain) e contra (Stop) em 10s, 20s, 30s e 60s após a detecção de absorção institucional.
   ```powershell
   python.exe .agents\skills\profitdll-market-analysis\scripts\inspect_mfe_mae.py
   ```

