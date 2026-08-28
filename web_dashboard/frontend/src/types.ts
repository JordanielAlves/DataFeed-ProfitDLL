export interface PriceData {
  last: number;
  last_formatted: string;
  open: number;
  open_formatted: string;
  high: number;
  high_formatted: string;
  low: number;
  low_formatted: string;
  range: number;
  delta_open: number;
  total_trades: number;
  total_qty: number;
}

export interface RegimeData {
  name: string;
  description: string;
  harmonic_step: number;
  is_chop_zone: boolean;
  relative_pos: number;
  range_ratio: number;
  recommended_gain: number;
  recommended_stop: number;
}

export interface MacroData {
  dxy_var: number;
  dxy_price: number;
  spx_var: number;
  spx_price: number;
  win_delta_pts: number;
  di1_delta_bps: number;
  status: string;
  label: string;
}

export interface HarmonicLevel {
  multiplier: number;
  name: string;
  price: number;
  price_formatted: string;
  distance_pts: number;
  role: string;
  type: "resistencia" | "eixo" | "suporte";
  is_closest: boolean;
}

export interface Player {
  id: number;
  name: string;
  abbr: string;
  net_qty: number;
  buy_qty?: number;
  sell_qty?: number;
  turnover: number;
}

export interface SignalEvent {
  id: number;
  signal_type: string;
  direction: number;
  direction_label: string;
  price: number;
  price_formatted: string;
  stop_formatted: string;
  target_formatted: string;
  ml_conviction: number | null;
  ml_tier: "SNIPER" | "CONVICTION" | "LOW";
  outcome_pts: number | null;
  time_str: string;
  context: {
    cvd_big?: number;
    cvd_varejo?: number;
    delta_p?: number;
    total_qty?: number;
    regime?: string;
    is_exhausted?: boolean;
    dist_to_macro_harmonic?: number;
    top_agents?: Array<{
      agent_id: number;
      corretora: string;
      saldo: number;
      lote_med: number;
    }>;
  };
}

export interface MarketSnapshot {
  ticker: string;
  session_date: string;
  server_time: string;
  price: PriceData;
  regime: RegimeData;
  macro: MacroData;
  harmonic_ladder: HarmonicLevel[];
  players: {
    buyers: Player[];
    sellers: Player[];
  };
  recent_signals: SignalEvent[];
}
