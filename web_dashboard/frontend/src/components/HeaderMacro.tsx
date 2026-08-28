import React from "react";
import { Globe, TrendingUp, TrendingDown, Activity, Volume2, VolumeX, Radio, Clock } from "lucide-react";
import { MacroData } from "../types";

interface HeaderMacroProps {
  ticker: string;
  onSelectTicker: (t: string) => void;
  macro: MacroData;
  serverTime: string;
  sessionDate: string;
  isConnected: boolean;
  soundEnabled: boolean;
  onToggleSound: () => void;
}

export const HeaderMacro: React.FC<HeaderMacroProps> = ({
  ticker,
  onSelectTicker,
  macro,
  serverTime,
  sessionDate,
  isConnected,
  soundEnabled,
  onToggleSound,
}) => {
  return (
    <header className="w-full glass-panel border-b border-bg-border px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 shadow-lg z-20">
      {/* Brand & Ticker Switcher */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-trade-accent/20 border border-trade-accent/40 flex items-center justify-center text-trade-accent shadow-sm">
            <Activity className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <h1 className="text-base font-bold tracking-wider text-slate-100 flex items-center gap-1.5 font-mono">
              QUANT<span className="text-trade-accent">PROFIT</span>
              <span className="text-xs bg-bg-panel border border-bg-border text-slate-400 px-1.5 py-0.5 rounded uppercase">
                B3
              </span>
            </h1>
            <p className="text-[10px] text-slate-400 font-mono flex items-center gap-1">
              <Clock className="w-3 h-3" /> {sessionDate} • {serverTime || "00:00:00"}
            </p>
          </div>
        </div>

        {/* Ticker Selector */}
        <div className="flex bg-bg-darkest border border-bg-border rounded-lg p-0.5 ml-2 font-mono text-xs font-semibold">
          <button
            onClick={() => onSelectTicker("WDOU26")}
            className={`px-3 py-1 rounded transition-all ${
              ticker.startsWith("WDO") || ticker.startsWith("DOL")
                ? "bg-trade-accent/20 text-trade-accent border border-trade-accent/40 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            WDOU26
          </button>
          <button
            onClick={() => onSelectTicker("WINV26")}
            className={`px-3 py-1 rounded transition-all ${
              ticker.startsWith("WIN") || ticker.startsWith("IND")
                ? "bg-trade-accent/20 text-trade-accent border border-trade-accent/40 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            WINV26
          </button>
        </div>
      </div>

      {/* Macro Indicators */}
      <div className="flex items-center flex-wrap gap-2 text-xs font-mono">
        {/* DXY */}
        <div className="flex items-center gap-1.5 bg-bg-darkest/80 border border-bg-border/80 px-2.5 py-1 rounded-md">
          <Globe className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-slate-400 font-medium">DXY:</span>
          <span
            className={`font-bold flex items-center ${
              macro.dxy_var > 0
                ? "text-trade-buy"
                : macro.dxy_var < 0
                ? "text-trade-sell"
                : "text-slate-300"
            }`}
          >
            {macro.dxy_var > 0 ? "+" : ""}
            {macro.dxy_var.toFixed(2)}%
          </span>
        </div>

        {/* SPX */}
        <div className="flex items-center gap-1.5 bg-bg-darkest/80 border border-bg-border/80 px-2.5 py-1 rounded-md">
          <span className="text-slate-400 font-medium">SPX:</span>
          <span
            className={`font-bold ${
              macro.spx_var > 0
                ? "text-trade-buy"
                : macro.spx_var < 0
                ? "text-trade-sell"
                : "text-slate-300"
            }`}
          >
            {macro.spx_var > 0 ? "+" : ""}
            {macro.spx_var.toFixed(2)}%
          </span>
        </div>

        {/* Mini Índice WIN */}
        <div className="flex items-center gap-1.5 bg-bg-darkest/80 border border-bg-border/80 px-2.5 py-1 rounded-md">
          <span className="text-slate-400 font-medium">WIN:</span>
          <span
            className={`font-bold flex items-center ${
              macro.win_delta_pts > 0
                ? "text-trade-buy"
                : macro.win_delta_pts < 0
                ? "text-trade-sell"
                : "text-slate-300"
            }`}
          >
            {macro.win_delta_pts > 0 ? "+" : ""}
            {macro.win_delta_pts.toFixed(0)} pts
          </span>
        </div>

        {/* Juros DI1 */}
        <div className="flex items-center gap-1.5 bg-bg-darkest/80 border border-bg-border/80 px-2.5 py-1 rounded-md">
          <span className="text-slate-400 font-medium">DI1:</span>
          <span
            className={`font-bold ${
              macro.di1_delta_bps > 0
                ? "text-trade-buy"
                : macro.di1_delta_bps < 0
                ? "text-trade-sell"
                : "text-slate-300"
            }`}
          >
            {macro.di1_delta_bps > 0 ? "+" : ""}
            {macro.di1_delta_bps.toFixed(1)} bps
          </span>
        </div>

        {/* Macro Context Alignment Badge */}
        <div
          className={`px-2.5 py-1 rounded-md border text-[11px] font-semibold flex items-center gap-1 ${
            macro.status === "ALTA_DOLAR"
              ? "bg-trade-buy/15 border-trade-buy/30 text-trade-buy"
              : macro.status === "BAIXA_DOLAR"
              ? "bg-trade-sell/15 border-trade-sell/30 text-trade-sell"
              : "bg-slate-800/60 border-slate-700 text-slate-300"
          }`}
        >
          {macro.status === "ALTA_DOLAR" ? (
            <TrendingUp className="w-3.5 h-3.5" />
          ) : macro.status === "BAIXA_DOLAR" ? (
            <TrendingDown className="w-3.5 h-3.5" />
          ) : null}
          {macro.label}
        </div>
      </div>

      {/* Right Actions: WebSocket Status & Sound */}
      <div className="flex items-center gap-2">
        {/* Sound Toggle */}
        <button
          onClick={onToggleSound}
          title={soundEnabled ? "Desativar alertas sonoros" : "Ativar alertas sonoros"}
          className={`p-1.5 rounded-lg border transition-all ${
            soundEnabled
              ? "bg-trade-accent/20 border-trade-accent/50 text-trade-accent hover:bg-trade-accent/30"
              : "bg-bg-darkest border-bg-border text-slate-500 hover:text-slate-300"
          }`}
        >
          {soundEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
        </button>

        {/* WebSocket Pulse Badge */}
        <div
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono border ${
            isConnected
              ? "bg-trade-buy/10 border-trade-buy/30 text-trade-buy"
              : "bg-trade-sell/10 border-trade-sell/30 text-trade-sell"
          }`}
        >
          <Radio className={`w-3.5 h-3.5 ${isConnected ? "animate-pulse" : ""}`} />
          <span className="font-semibold">{isConnected ? "LIVE STREAM" : "OFFLINE"}</span>
        </div>
      </div>
    </header>
  );
};
