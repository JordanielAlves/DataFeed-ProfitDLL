import React, { useState } from "react";
import { Zap, Shield, Flame, Compass, Crosshair, Target, CheckCircle2, XCircle, Filter } from "lucide-react";
import { SignalEvent } from "../types";

interface SignalStreamProps {
  signals: SignalEvent[];
}

export const SignalStream: React.FC<SignalStreamProps> = ({ signals }) => {
  const [filter, setFilter] = useState<"ALL" | "SNIPER" | "BUY" | "SELL">("ALL");

  const filteredSignals = signals.filter((s) => {
    if (filter === "SNIPER") return s.ml_tier === "SNIPER" || s.signal_type.includes("COMBO");
    if (filter === "BUY") return s.direction === 1;
    if (filter === "SELL") return s.direction === -1;
    return true;
  });

  const getSignalIcon = (type: string) => {
    if (type.includes("ABSORCAO")) return <Flame className="w-4 h-4 text-amber-400" />;
    if (type.includes("DISTRIBUICAO") || type.includes("ACUMULACAO"))
      return <Compass className="w-4 h-4 text-purple-400" />;
    if (type.includes("IMPULSO")) return <Zap className="w-4 h-4 text-sky-400" />;
    return <Shield className="w-4 h-4 text-slate-400" />;
  };

  return (
    <div className="glass-panel rounded-xl p-4 flex flex-col h-full shadow-lg border border-bg-border">
      {/* Header & Filter Controls */}
      <div className="flex flex-wrap items-center justify-between border-b border-bg-border pb-3 mb-3 gap-2">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-trade-accent" />
          <h2 className="text-sm font-bold tracking-wide text-slate-200 uppercase font-mono">
            Feed de Sinais Quantitativos
          </h2>
          <span className="text-xs text-slate-500 font-mono">({filteredSignals.length})</span>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1 bg-bg-darkest border border-bg-border rounded-lg p-0.5 font-mono text-[11px]">
          <button
            onClick={() => setFilter("ALL")}
            className={`px-2.5 py-0.5 rounded transition-all ${
              filter === "ALL"
                ? "bg-bg-panel text-slate-200 border border-slate-700 font-bold"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            Todos
          </button>
          <button
            onClick={() => setFilter("SNIPER")}
            className={`px-2.5 py-0.5 rounded transition-all flex items-center gap-1 ${
              filter === "SNIPER"
                ? "bg-trade-sniper/20 text-trade-sniper border border-trade-sniper/40 font-bold"
                : "text-slate-500 hover:text-trade-sniper"
            }`}
          >
            ⭐ Sniper
          </button>
          <button
            onClick={() => setFilter("BUY")}
            className={`px-2.5 py-0.5 rounded transition-all ${
              filter === "BUY"
                ? "bg-trade-buy/20 text-trade-buy border border-trade-buy/40 font-bold"
                : "text-slate-500 hover:text-trade-buy"
            }`}
          >
            Compras
          </button>
          <button
            onClick={() => setFilter("SELL")}
            className={`px-2.5 py-0.5 rounded transition-all ${
              filter === "SELL"
                ? "bg-trade-sell/20 text-trade-sell border border-trade-sell/40 font-bold"
                : "text-slate-500 hover:text-trade-sell"
            }`}
          >
            Vendas
          </button>
        </div>
      </div>

      {/* Signal Cards Feed */}
      <div className="flex-1 overflow-y-auto flex flex-col gap-2.5 pr-1 font-mono">
        {filteredSignals.map((sig) => {
          const isSniper = sig.ml_tier === "SNIPER";
          const isConviction = sig.ml_tier === "CONVICTION";
          const isBuy = sig.direction === 1;

          return (
            <div
              key={sig.id}
              className={`rounded-xl p-3 border transition-all flex flex-col gap-2 ${
                isSniper
                  ? "bg-bg-panel/90 border-trade-sniper/60 shadow-lg ring-1 ring-trade-sniper/40 animate-neon-pulse"
                  : isConviction
                  ? "bg-bg-darkest/90 border-trade-accent/40 shadow-sm"
                  : "bg-bg-darkest/60 border-bg-border/70 opacity-80 hover:opacity-100"
              }`}
            >
              {/* Card Top Row: Type, Direction, Price, Time */}
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <div className="p-1 rounded bg-bg-panel border border-bg-border">
                    {getSignalIcon(sig.signal_type)}
                  </div>
                  <span className="font-bold text-xs text-slate-100 uppercase tracking-wide">
                    {sig.signal_type.replace(/_/g, " ")}
                  </span>
                  <span
                    className={`text-[10px] font-extrabold px-2 py-0.5 rounded border ${
                      isBuy
                        ? "bg-trade-buy/15 border-trade-buy/30 text-trade-buy"
                        : "bg-trade-sell/15 border-trade-sell/30 text-trade-sell"
                    }`}
                  >
                    {sig.direction_label}
                  </span>
                </div>

                <div className="flex items-center gap-2 text-xs">
                  <span className="font-extrabold text-sm text-slate-100 bg-bg-panel px-2 py-0.5 rounded border border-bg-border">
                    {sig.price_formatted}
                  </span>
                  <span className="text-[10px] text-slate-400">{sig.time_str}</span>
                </div>
              </div>

              {/* Card Middle: ML Score & Targets */}
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs pt-1 border-t border-bg-border/60">
                {/* ML Score Pill */}
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-slate-400">Score IA:</span>
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-bold border ${
                      isSniper
                        ? "bg-trade-sniper/20 border-trade-sniper/50 text-trade-sniper"
                        : isConviction
                        ? "bg-trade-accent/20 border-trade-accent/50 text-trade-accent"
                        : "bg-amber-950/40 border-amber-500/40 text-amber-400"
                    }`}
                  >
                    {isSniper && "⭐ "}
                    {sig.ml_conviction ? `${sig.ml_conviction.toFixed(1)}%` : "N/A"}
                    {isSniper && " (Sniper)"}
                    {isConviction && " (Convicção)"}
                    {!isSniper && !isConviction && " (Baixa)"}
                  </span>
                </div>

                {/* Tactical Target & Stop */}
                <div className="flex items-center gap-2 text-[11px]">
                  <div className="flex items-center gap-1 text-trade-buy">
                    <Target className="w-3 h-3" />
                    <span>Alvo: {sig.target_formatted}</span>
                  </div>
                  <div className="flex items-center gap-1 text-trade-sell">
                    <Crosshair className="w-3 h-3" />
                    <span>Stop: {sig.stop_formatted}</span>
                  </div>
                </div>
              </div>

              {/* Context Summary Footer if Available */}
              {sig.context && sig.context.top_agents && (
                <div className="text-[10px] text-slate-400 flex items-center justify-between pt-1 border-t border-bg-border/40">
                  <span>
                    Players:{" "}
                    {sig.context.top_agents
                      .slice(0, 2)
                      .map((a) => `${a.corretora} (${a.saldo > 0 ? "+" : ""}${a.saldo})`)
                      .join(", ")}
                  </span>
                  {sig.outcome_pts !== null && (
                    <span
                      className={`font-bold flex items-center gap-0.5 ${
                        sig.outcome_pts >= 2.5
                          ? "text-trade-buy"
                          : sig.outcome_pts <= -2.0
                          ? "text-trade-sell"
                          : "text-slate-400"
                      }`}
                    >
                      {sig.outcome_pts >= 2.5 ? (
                        <CheckCircle2 className="w-3 h-3 text-trade-buy" />
                      ) : sig.outcome_pts <= -2.0 ? (
                        <XCircle className="w-3 h-3 text-trade-sell" />
                      ) : null}
                      Resultado: {sig.outcome_pts > 0 ? "+" : ""}
                      {sig.outcome_pts.toFixed(1)}p
                    </span>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {filteredSignals.length === 0 && (
          <div className="flex flex-col items-center justify-center p-8 text-slate-500 gap-2">
            <Filter className="w-8 h-8 opacity-40" />
            <p className="text-xs">Nenhum sinal encontrado para o filtro selecionado.</p>
          </div>
        )}
      </div>
    </div>
  );
};
