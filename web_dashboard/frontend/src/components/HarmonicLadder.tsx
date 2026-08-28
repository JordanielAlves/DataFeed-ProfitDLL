import React from "react";
import { Layers, Target, ArrowRight } from "lucide-react";
import { HarmonicLevel } from "../types";

interface HarmonicLadderProps {
  ladder: HarmonicLevel[];
  harmonicStep: number;
  currentPrice: number;
  currentPriceFormatted: string;
}

export const HarmonicLadder: React.FC<HarmonicLadderProps> = ({
  ladder,
  harmonicStep,
  currentPrice,
  currentPriceFormatted,
}) => {
  return (
    <div className="glass-panel rounded-xl p-4 flex flex-col h-full shadow-lg border border-bg-border">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-bg-border pb-3 mb-3">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-trade-accent" />
          <h2 className="text-sm font-bold tracking-wide text-slate-200 uppercase font-mono">
            Grade Harmônica
          </h2>
        </div>
        <span className="text-[11px] font-mono bg-trade-accent/15 border border-trade-accent/30 text-trade-accent px-2 py-0.5 rounded font-semibold">
          Passo: {harmonicStep.toFixed(1)} pts
        </span>
      </div>

      {/* Ladder Levels */}
      <div className="flex-1 flex flex-col justify-between gap-1 font-mono text-xs overflow-y-auto pr-1">
        {ladder.map((level) => {
          const isClosest = level.is_closest;
          const isResistance = level.type === "resistencia";
          const isSupport = level.type === "suporte";
          const isAxis = level.type === "eixo";

          return (
            <div
              key={level.multiplier}
              className={`relative flex items-center justify-between px-2.5 py-1.5 rounded-lg border transition-all ${
                isClosest
                  ? "bg-bg-panel border-trade-accent/60 shadow-md ring-1 ring-trade-accent/30"
                  : isAxis
                  ? "bg-slate-900/60 border-slate-700/80"
                  : isResistance
                  ? "bg-slate-900/40 border-slate-800/80 hover:border-trade-sell/30"
                  : "bg-slate-900/40 border-slate-800/80 hover:border-trade-buy/30"
              }`}
            >
              {/* Level Info */}
              <div className="flex items-center gap-2">
                <span
                  className={`w-6 text-center font-bold text-[11px] ${
                    isResistance
                      ? "text-trade-sell"
                      : isSupport
                      ? "text-trade-buy"
                      : "text-trade-accent"
                  }`}
                >
                  {level.multiplier > 0 ? `+${level.multiplier}` : level.multiplier}
                </span>

                <div className="flex flex-col">
                  <span className="font-semibold text-slate-200 text-xs">
                    {level.price_formatted}
                  </span>
                  <span className="text-[9px] text-slate-400 leading-tight">
                    {level.role}
                  </span>
                </div>
              </div>

              {/* Distance or Current Price Indicator */}
              <div className="flex items-center gap-1.5">
                {isClosest ? (
                  <div className="flex items-center gap-1 bg-trade-accent/20 border border-trade-accent/50 text-trade-accent px-2 py-0.5 rounded text-[10px] font-bold animate-pulse">
                    <Target className="w-3 h-3" />
                    <span>{level.distance_pts.toFixed(1)}p</span>
                  </div>
                ) : (
                  <span className="text-[10px] text-slate-500 font-medium">
                    Δ {level.distance_pts.toFixed(1)}p
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Current Floating Position Summary */}
      <div className="mt-3 pt-2.5 border-t border-bg-border flex items-center justify-between text-xs font-mono">
        <span className="text-slate-400 flex items-center gap-1">
          <ArrowRight className="w-3.5 h-3.5 text-trade-accent" /> Cotação Atual:
        </span>
        <span className="text-sm font-bold text-slate-100 bg-bg-darkest px-2.5 py-0.5 rounded border border-bg-border">
          {currentPriceFormatted}
        </span>
      </div>
    </div>
  );
};
