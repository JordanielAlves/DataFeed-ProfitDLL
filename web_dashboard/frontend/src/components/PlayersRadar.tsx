import React from "react";
import { Users, TrendingUp, TrendingDown, ArrowLeftRight } from "lucide-react";
import { Player } from "../types";

interface PlayersRadarProps {
  buyers: Player[];
  sellers: Player[];
}

export const PlayersRadar: React.FC<PlayersRadarProps> = ({ buyers, sellers }) => {
  const maxVolume = Math.max(
    ...buyers.map((b) => Math.abs(b.net_qty)),
    ...sellers.map((s) => Math.abs(s.net_qty)),
    1
  );

  return (
    <div className="glass-panel rounded-xl p-4 flex flex-col h-full shadow-lg border border-bg-border">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-bg-border pb-3 mb-3">
        <div className="flex items-center gap-2">
          <Users className="w-4 h-4 text-trade-accent" />
          <h2 className="text-sm font-bold tracking-wide text-slate-200 uppercase font-mono">
            Radar de Grandes Players
          </h2>
        </div>
        <span className="text-[10px] text-slate-400 font-mono flex items-center gap-1">
          <ArrowLeftRight className="w-3 h-3" /> Saldo Líquido Diário
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 flex-1 overflow-y-auto">
        {/* Compradores */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-1 text-xs font-mono font-bold text-trade-buy pb-1 border-b border-trade-buy/20">
            <TrendingUp className="w-3.5 h-3.5" />
            <span>TOP COMPRADORES</span>
          </div>

          <div className="flex flex-col gap-1.5 font-mono text-xs">
            {buyers.map((p) => {
              const barWidth = Math.min(100, Math.round((Math.abs(p.net_qty) / maxVolume) * 100));
              return (
                <div
                  key={p.id}
                  className="bg-bg-darkest/70 border border-bg-border rounded-lg p-2 flex flex-col gap-1 hover:border-trade-buy/40 transition-all"
                >
                  <div className="flex justify-between items-center text-xs">
                    <span className="font-bold text-slate-200 truncate">
                      {p.name} <span className="text-[10px] text-slate-500 font-normal">({p.id})</span>
                    </span>
                    <span className="font-bold text-trade-buy">
                      +{p.net_qty.toLocaleString()} ctrs
                    </span>
                  </div>

                  {/* Volume Bar */}
                  <div className="w-full bg-slate-900 h-1.5 rounded-full overflow-hidden">
                    <div
                      className="bg-trade-buy h-full rounded-full transition-all duration-500"
                      style={{ width: `${barWidth}%` }}
                    />
                  </div>

                  <div className="flex justify-between text-[9px] text-slate-500">
                    <span>Giro: {p.turnover.toLocaleString()}</span>
                    <span>Força: {barWidth}%</span>
                  </div>
                </div>
              );
            })}
            {buyers.length === 0 && (
              <p className="text-xs text-slate-500 italic">Nenhum comprador ativo no momento.</p>
            )}
          </div>
        </div>

        {/* Vendedores */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-1 text-xs font-mono font-bold text-trade-sell pb-1 border-b border-trade-sell/20">
            <TrendingDown className="w-3.5 h-3.5" />
            <span>TOP VENDEDORES</span>
          </div>

          <div className="flex flex-col gap-1.5 font-mono text-xs">
            {sellers.map((p) => {
              const barWidth = Math.min(100, Math.round((Math.abs(p.net_qty) / maxVolume) * 100));
              return (
                <div
                  key={p.id}
                  className="bg-bg-darkest/70 border border-bg-border rounded-lg p-2 flex flex-col gap-1 hover:border-trade-sell/40 transition-all"
                >
                  <div className="flex justify-between items-center text-xs">
                    <span className="font-bold text-slate-200 truncate">
                      {p.name} <span className="text-[10px] text-slate-500 font-normal">({p.id})</span>
                    </span>
                    <span className="font-bold text-trade-sell">
                      {p.net_qty.toLocaleString()} ctrs
                    </span>
                  </div>

                  {/* Volume Bar */}
                  <div className="w-full bg-slate-900 h-1.5 rounded-full overflow-hidden">
                    <div
                      className="bg-trade-sell h-full rounded-full transition-all duration-500"
                      style={{ width: `${barWidth}%` }}
                    />
                  </div>

                  <div className="flex justify-between text-[9px] text-slate-500">
                    <span>Giro: {p.turnover.toLocaleString()}</span>
                    <span>Força: {barWidth}%</span>
                  </div>
                </div>
              );
            })}
            {sellers.length === 0 && (
              <p className="text-xs text-slate-500 italic">Nenhum vendedor ativo no momento.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
