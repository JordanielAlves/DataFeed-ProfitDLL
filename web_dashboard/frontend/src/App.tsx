import React, { useState, useEffect, useRef } from "react";
import { HeaderMacro } from "./components/HeaderMacro";
import { HarmonicLadder } from "./components/HarmonicLadder";
import { MarketStateCard } from "./components/MarketStateCard";
import { PlayersRadar } from "./components/PlayersRadar";
import { SignalStream } from "./components/SignalStream";
import { soundManager } from "./components/AudioAlerts";
import { MarketSnapshot } from "./types";

export function App() {
  const [ticker, setTicker] = useState<string>("WDOU26");
  const [snapshot, setSnapshot] = useState<MarketSnapshot | null>(null);
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [soundEnabled, setSoundEnabled] = useState<boolean>(true);

  const lastSignalIdRef = useRef<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Inicializar som
  const handleToggleSound = () => {
    const nextVal = !soundEnabled;
    setSoundEnabled(nextVal);
    soundManager.setEnabled(nextVal);
    if (nextVal) {
      soundManager.playConvictionAlert(); // Som de teste
    }
  };

  // Conexão WebSocket em Tempo Real
  useEffect(() => {
    let isMounted = true;
    let reconnectTimer: any;

    const connectWebSocket = () => {
      // Determinar URL do WebSocket dinâmica (suporta ngrok, IP local, localhost e Vite dev)
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const host = window.location.host;
      const wsHost = window.location.port === "5173" ? `${window.location.hostname}:8000` : (host || "localhost:8000");
      const wsUrl = `${protocol}//${wsHost}/ws/live?ticker=${ticker}`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isMounted) return;
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        if (!isMounted) return;
        try {
          const data: MarketSnapshot = JSON.parse(event.data);
          setSnapshot(data);

          // Verificar novos sinais e disparar alerta sonoro
          if (data.recent_signals && data.recent_signals.length > 0) {
            const newest = data.recent_signals[0];
            if (lastSignalIdRef.current !== null && newest.id > lastSignalIdRef.current) {
              if (newest.ml_tier === "SNIPER" || newest.signal_type.includes("COMBO")) {
                soundManager.playSniperAlert();
              } else if (newest.ml_tier === "CONVICTION") {
                soundManager.playConvictionAlert();
              }
            }
            lastSignalIdRef.current = newest.id;
          }
        } catch (err) {
          console.error("Erro ao processar mensagem do WebSocket:", err);
        }
      };

      ws.onclose = () => {
        if (!isMounted) return;
        setIsConnected(false);
        // Tentar reconectar a cada 2 segundos
        reconnectTimer = setTimeout(connectWebSocket, 2000);
      };

      ws.onerror = () => {
        if (!isMounted) return;
        setIsConnected(false);
      };
    };

    connectWebSocket();

    return () => {
      isMounted = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [ticker]);

  // Loading State inicial
  if (!snapshot) {
    return (
      <div className="min-h-screen bg-bg-darkest flex flex-col items-center justify-center text-slate-200 font-mono gap-4">
        <div className="w-12 h-12 border-4 border-trade-accent/30 border-t-trade-accent rounded-full animate-spin" />
        <p className="text-sm font-semibold tracking-wider animate-pulse">
          CONECTANDO À ENGINE QUANTITATIVA PROFITDLL...
        </p>
        <span className="text-xs text-slate-500">ws://localhost:8000/ws/live?ticker={ticker}</span>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg-darkest flex flex-col text-slate-100 selection:bg-trade-accent/30">
      {/* Header Macro */}
      <HeaderMacro
        ticker={ticker}
        onSelectTicker={(t) => setTicker(t)}
        macro={snapshot.macro}
        serverTime={snapshot.server_time}
        sessionDate={snapshot.session_date}
        isConnected={isConnected}
        soundEnabled={soundEnabled}
        onToggleSound={handleToggleSound}
      />

      {/* Main Dashboard Workspace Grid */}
      <main className="flex-1 p-3 grid grid-cols-1 lg:grid-cols-12 gap-3 max-w-[1920px] w-full mx-auto">
        {/* Coluna Esquerda: Grade Harmônica (Ladder Vertical) — 3 colunas */}
        <div className="lg:col-span-3 h-[calc(100vh-75px)] min-h-[600px]">
          <HarmonicLadder
            ladder={snapshot.harmonic_ladder}
            harmonicStep={snapshot.regime.harmonic_step}
            currentPrice={snapshot.price.last}
            currentPriceFormatted={snapshot.price.last_formatted}
          />
        </div>

        {/* Coluna Central: Market State Hero + Feed de Sinais — 5 colunas */}
        <div className="lg:col-span-5 h-[calc(100vh-75px)] min-h-[600px] flex flex-col gap-3">
          <div className="flex-shrink-0">
            <MarketStateCard
              price={snapshot.price}
              regime={snapshot.regime}
              ticker={snapshot.ticker}
            />
          </div>

          <div className="flex-1 overflow-hidden">
            <SignalStream signals={snapshot.recent_signals} />
          </div>
        </div>

        {/* Coluna Direita: Radar dos Big Players — 4 colunas */}
        <div className="lg:col-span-4 h-[calc(100vh-75px)] min-h-[600px]">
          <PlayersRadar
            buyers={snapshot.players.buyers}
            sellers={snapshot.players.sellers}
          />
        </div>
      </main>
    </div>
  );
}

export default App;
