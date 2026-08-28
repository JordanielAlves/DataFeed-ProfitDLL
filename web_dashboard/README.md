# ProfitDLL Quantitative Dashboard — B3

Dashboard web institucional de alta performance para monitoramento de microestrutura e fluxo de ordens na B3 (Mini Dólar e Mini Índice) em tempo real.

---

## 🏛️ Arquitetura

O sistema é dividido em duas camadas isoladas no diretório `C:\DEV\ProfitDLL\web_dashboard`:

```
C:\DEV\ProfitDLL\web_dashboard/
├── backend/
│   ├── server.py             # Servidor FastAPI + WebSocket de baixa latência (<10ms)
│   └── data_service.py       # Serviço de agregação (Harmônicos, Regime, Players, Sinais ML)
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── HeaderMacro.tsx       # Ticker bar macro (DXY, SPX, WIN, DI1) e status WS
│   │   │   ├── HarmonicLadder.tsx    # Termômetro vertical da Grade Harmônica (+4 a -4)
│   │   │   ├── MarketStateCard.tsx   # Preço Hero, Min/Max/Amp e Barra de Chop Zone
│   │   │   ├── PlayersRadar.tsx      # Radar dos Big Players com barras de saldo/giro
│   │   │   ├── SignalStream.tsx      # Feed de Sinais com Score ML, Stops e Alvos
│   │   │   └── AudioAlerts.ts        # Sintetizador Web Audio API para alertas sonoros
│   │   ├── App.tsx                   # Grid responsivo e sincronização WebSocket
│   │   └── types.ts                  # Contratos de tipos TypeScript
│   └── dist/                         # Build de produção estático empacotado pelo Vite
├── start_dashboard.bat               # Inicializador rápido em 1 clique
└── README.md                         # Esta documentação
```

---

## 🚀 Como Iniciar

### Modo 1: Produção / Uso Diário (1 Clique)
Basta dar dois cliques no arquivo:
```cmd
C:\DEV\ProfitDLL\web_dashboard\start_dashboard.bat
```
O servidor iniciará automaticamente na porta `8000` e abrirá seu navegador em `http://localhost:8000`.

---

### Modo 2: Desenvolvimento com Hot-Reload (Opcional)

1. **Terminal 1 (Backend):**
   ```powershell
   cd C:\DEV\ProfitDLL\web_dashboard\backend
   python server.py
   ```

2. **Terminal 2 (Frontend React/Vite):**
   ```powershell
   cd C:\DEV\ProfitDLL\web_dashboard\frontend
   npm run dev
   ```
   Acesse: `http://localhost:5173`.

---

## 💎 Recursos Quantitativos

1. **Macro Ticker Bar:** Atualizações em tempo real de DXY, S&P 500, Mini Índice e DI Futuro com indicador de alinhamento direcional.
2. **Grade Harmônica Vertical:** Termômetro com todos os níveis harmônicos diários (+4 a -4), preços em formato B3 (`5.167,00`), distâncias em pontos e papel tático (suporte, resistência, exaustão).
3. **Barra de Chop Zone:** Mostrador do percentual da cotação no range diário (0% a 100%) com destaque visual em amarelo se o preço estiver preso na Zona de Miolo (35% a 65%).
4. **Radar de Big Players:** Balanço dinâmico dos 5 maiores compradores e 5 maiores vendedores (Citi, JP Morgan, Ativa, BTG, XP) com volume e giro.
5. **Feed de Sinais e Alertas Sonoros:** Cards dos setups armados com probabilidade ML, tiers (`⭐ SNIPER`, `CONVICÇÃO`, `BAIXA`), indicação de Stop Técnico protegido e alvo adaptativo.
