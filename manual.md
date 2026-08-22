# 🚀 Manual de Operação e Rotina — DataFeed B3 / ProfitDLL

Este manual descreve o passo a passo de operação, configuração e automação do sistema quantitativo de fluxo de ordens (ProfitDLL + PostgreSQL + Machine Learning).

Com a "Elevação Fase 1", **boa parte do processo agora é automatizada**. Leia atentamente as novas instruções.

---

## ⚙️ 1. Configuração do Telegram (Alertas)

Para que o sistema consiga avisar você sobre quedas (watchdog) e a qualidade dos dados (resumo diário), configure o bot do Telegram:

1. No aplicativo Telegram, busque por **@BotFather**.
2. Envie o comando `/newbot`. Ele pedirá um nome e um username para o seu bot.
3. Ao finalizar, o BotFather enviará um **TOKEN** (exemplo: `7123456789:AAFxxxxxx...`).
4. Para descobrir o seu ID pessoal, busque no Telegram por **@userinfobot** e inicie uma conversa. Ele mostrará o seu `Id` (exemplo: `123456789`).
5. Alternativamente, mande um "Oi" para o seu novo bot recém criado, e acesse no navegador: `https://api.telegram.org/bot<SEU_TOKEN_AQUI>/getUpdates` para achar seu chat ID.
6. Abra o arquivo `C:\DEV\ProfitDLL\config.py`, localize o bloco `TELEGRAM` no final do arquivo e preencha:
   ```python
   TELEGRAM = {
       "token":    "COLOQUE_SEU_TOKEN_AQUI",
       "chat_id":  "COLOQUE_SEU_CHAT_ID_AQUI",
       "enabled":  True,  # Mude para True
   }
   ```

---

## 🔄 2. Automação do Sistema (Task Scheduler)

O sistema possui scripts para configurar a inicialização e auditoria automaticamente no **Agendador de Tarefas do Windows**. 

### Como Instalar as Automações:
Abra o **PowerShell como Administrador** e execute os scripts de configuração criados na pasta `C:\DEV\ProfitDLL`:
```powershell
cd C:\DEV\ProfitDLL
.\setup_scheduler.ps1
.\setup_quality_scheduler.ps1
```

### O que o Windows fará automaticamente:
1. **`DataFeed-B3-AutoStart`**: Sempre que você fizer logon no Windows, ele executará o script `start_system.bat`.
   * *O que é o `start_system.bat`?* É um script que abre o `main.py` (Coletor) e o `watchdog.py` (Monitor) juntos em janelas de Prompt separadas.
2. **`DataFeed-B3-QualityCheck`**: Todos os dias úteis (Segunda a Sexta) às 18:30, o Windows executará o `daily_quality_check.py`.
   * Ele vai ler o banco de dados do pregão do dia, verificar os buracos, mínimos, máximos e totais de trades, e mandar um relatório via Telegram.

---

## 🌅 3. Rotina Diária (O que você precisa fazer)

Como o Windows iniciará os scripts, sua rotina diária matinal (antes das 08:50) se resume a garantir a infraestrutura primária:

1. **Abra o ProfitPro e faça login.** A DLL da Nelogica *precisa* do terminal do Profit aberto e logado para liberar os dados.
2. Certifique-se de que o **PostgreSQL** está rodando como serviço (normalmente ele inicia sozinho com o Windows).
3. **Verifique se o `main.py` e o `watchdog.py` estão abertos.**
   * Se você reiniciou o PC, eles devem abrir sozinhos (devido ao `setup_scheduler.ps1`).
   * Se preferir abrir manualmente, basta dar dois cliques no arquivo `start_system.bat` na pasta do projeto.
4. **Pronto para a Coleta!** Deixe as janelas pretas minimizadas. O sistema cuidará do resto.
   * Se o `main.py` travar e fechar, o `watchdog.py` vai reiniciar ele sozinho (e te mandar um Telegram).

### Terminal Quantitativo & Alertas ML (Opcional)
Caso você queira os alertas de Absorção, Exaustão e Rompimento na sua tela operando:
1. Abra um PowerShell extra: `cd C:\DEV\ProfitDLL`
2. Execute o preditor:
   ```powershell
   python.exe .\ml_live_predictor.py --ticker WDOU26 --interval 10 --window 5
   ```

---

## 📈 4. Análise de Fechamento do Mercado (Após as 18:30)

O sistema agora faz o relatório de fechamento sozinho!

Às 18:30, você receberá um **Telegram** com o `Quality Check`. Ele te dirá:
* Se houve coleta bem sucedida para todos os ativos.
* A escala correta de Min/Max.
* Se os dados do dia estão 100% gravados no PostgreSQL sem buracos.

Se quiser rodar o check de dados para algum dia anterior manualmente:
```powershell
python.exe .\daily_quality_check.py --date 2026-08-19
```

### (Opcional) Execução do K-Means Behavior Analyzer
Para gerar aquele raio-X das corretoras ao fim do dia:
```powershell
python.exe .\ml_behavior_analyzer.py --ticker WDOU26 --action all --barras 15
```
*(As corretoras conhecidas e catalogadas por nós, como BTG, Ideal e XP, já estão sendo cruzadas com o banco de dados automaticamente através da nova tabela `agent_registry`)*.

---

## 🛠️ Resumo de Comandos e Scripts

| Arquivo/Comando | O que faz |
|-----------------|-----------|
| `start_system.bat` | Dá um duplo clique para iniciar `main.py` e `watchdog.py` de uma vez. |
| `watchdog.py` | Fica sondando a cada 30s. Se o main cair entre 08:45 e 18:15, ele reinicia. |
| `alerts.py` | Motor de mensagens para o Telegram (roda no fundo). |
| `daily_quality_check.py` | Verifica a saúde dos dados gravados no banco PostgreSQL. |
| `agent_registry.py` | Módulo interno Python que mapeia o ID da corretora (ex: 85) para o nome (BTG). |
