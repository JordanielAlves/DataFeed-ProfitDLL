import React from "react";
import { Gauge, ShieldAlert, Target, Crosshair, BarChart3, ArrowUpRight, ArrowDownRight } from "lucide-react";
import { PriceData, RegimeData } from "../types";

interface MarketStateCardProps {
  price: PriceData;
  regime: RegimeData;
  ticker: string;
}

export const MarketStateCard: React.FC<MarketStateCardProps> = ({
  price,
  regime,
  ticker,
}) => {
  const isPositive = price.delta_open >= 0;
  const chopPct = Math.round(regime.relative_pos * 100);

  return (
    <div className="glass-panel rounded-xl p-4 flex flex-col gap-3 shadow-lg border border-bg-border">
      {/* Top Row: Price Hero + Day Stats */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* Main Price & Delta */}
        <div>
          <div className="flex items-baseline gap-3 font-mono">
            <span className="text-3xl font-extrabold tracking-tight text-slate-100">
              {price.last_formatted}
            </span>
            <span
              className={`text-sm font-bold flex items-center px-2 py-0.5 rounded-md border ${
                isPositive
                  ? "bg-trade-buy/15 border-trade-buy/30 text-trade-buy"
                  : "bg-trade-sell/15 border-trade-sell/30 text-trade-sell"
              }`}
            >
              {isPositive ? (
                <ArrowUpRight className="w-4 h-4 mr-0.5" />
              ) : (
                <ArrowDownRight className="w-4 h-4 mr-0.5" />
              )}
              {isPositive ? "+" : ""}
              {price.delta_open.toFixed(2)} pts
            </span>
          </div>
          <p className="text-[11px] text-slate-400 font-mono mt-0.5">
            Ativo: <span className="text-trade-accent font-semibold">{ticker}</span> • Abertura: {price.open_formatted}
          </p>
        </div>

        {/* Min / Max / Amplitude Grid */}
        <div className="flex items-center gap-3 font-mono text-xs">
          <div className="bg-bg-darkest/80 border border-bg-border px-3 py-1.5 rounded-lg">
            <span className="text-slate-500 block text-[10px]">MÍNIMA</span>
            <span className="font-bold text-trade-sell text-sm">{price.low_formatted}</span>
          </div>

          <div className="bg-bg-darkest/80 border border-bg-border px-3 py-1.5 rounded-lg">
            <span className="text-slate-500 block text-[10px]">MÁXIMA</span>
            <span className="font-bold text-trade-buy text-sm">{price.high_formatted}</span>
          </div>

          <div className="bg-bg-darkest/80 border border-bg-border px-3 py-1.5 rounded-lg">
            <span className="text-slate-500 block text-[10px]">AMPLITUDE</span>
            <span className="font-bold text-slate-200 text-sm">{price.range.toFixed(1)} pts</span>
          </div>

          <div className="bg-bg-darkest/80 border border-bg-border px-3 py-1.5 rounded-lg hidden sm:block">
            <span className="text-slate-500 block text-[10px]">TRADES / CTRS</span>
            <span className="font-bold text-slate-300 text-xs">
              {price.total_trades.toLocaleString()} / {(price.total_qty || 0).toLocaleString()}
            </span>
          </div>
        </div>
      </div>

      {/* Middle Row: Regime Badge & Strategy */}
      <div className="bg-bg-darkest/90 border border-bg-border rounded-lg p-3 flex flex-col gap-2 font-mono">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Gauge className="w-4 h-4 text-trade-accent" />
            <span className="text-xs text-slate-400 font-semibold">REGIME:</span>
            <span
              className={`px-2.5 py-0.5 rounded text-xs font-bold uppercase border ${
                regime.name === "EXPANSAO_DIRECIONAL"
                  ? "bg-purple-950/60 border-purple-500/50 text-purple-300"
                  : regime.name === "CONSOLIDACAO_ESTREITA"
                  ? "bg-amber-950/60 border-amber-500/50 text-amber-300"
                  : "bg-blue-950/60 border-blue-500/50 text-blue-300"
              }`}
            >
              {regime.name}
            </span>
          </div>

          {/* Adaptive Target/Stop Pills */}
          <div className="flex items-center gap-2 text-xs">
            <div className="flex items-center gap-1 bg-trade-buy/10 border border-trade-buy/30 text-trade-buy px-2 py-0.5 rounded">
              <Target className="w-3.5 h-3.5" />
              <span>Alvo: +{regime.recommended_gain.toFixed(1)}p</span>
            </div>
            <div className="flex items-center gap-1 bg-trade-sell/10 border border-trade-sell/30 text-trade-sell px-2 py-0.5 rounded">
              <Crosshair className="w-3.5 h-3.5" />
              <span>Stop: {regime.recommended_stop.toFixed(1)}p</span>
            </div>
          </div>
        </div>

        <p className="text-xs text-slate-300">{regime.description}</p>

        {/* Chop Zone & Range Relative Position Bar */}
        <div className="mt-1">
          <div className="flex justify-between text-[10px] text-slate-400 mb-1 font-mono">
            <span>Fundo (0%)</span>
            <span
              className={
                regime.is_chop_zone
                  ? "text-trade-warn font-bold flex items-center gap-1"
                  : "text-slate-400"
              }
            >
              {regime.is_chop_zone && <ShieldAlert className="w-3 h-3 text-trade-warn" />}
              {regime.is_chop_zone ? `CHOP ZONE (${chopPct}%)` : `Posição no Range: ${chopPct}%`}
            </span>
            <span>Topo (100%)</span>
          </div>

          <div className="relative w-full h-3 bg-slate-900 border border-slate-700 rounded-full overflow-hidden">
            {/* Shaded Chop Zone (35% to 65%) */}
            <div className="absolute left-[35%] w-[30%] h-full bg-amber-500/20 border-x border-amber-500/30" />

            {/* Current Price Pointer */}
            <div
              className={`absolute top-0 bottom-0 w-2.5 rounded-full shadow-md transition-all duration-500 -ml-1 ${
                regime.is_chop_zone ? "bg-amber-400 ring-2 ring-amber-400/50" : "bg-trade-accent ring-2 ring-trade-accent/50"
              }`}
              style={{ left: `${Math.max(2, Math.min(98, chopPct))}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
};
