#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
data_service.py
Serviço de dados em tempo real para o Dashboard Web Quantitativo B3.
Conecta ao PostgreSQL e integra os módulos de regime, harmônicos, players e ML.
"""

import os
import sys
from datetime import datetime, date, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

# Adicionar raiz do projeto ao path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import DB_DSN
from price_utils import to_real_points, format_price_b3
from dynamic_harmonics import get_daily_harmonic_step
from market_regime import get_market_regime
from global_context import get_global_context, start_global_context
from domestic_context import get_domestic_context, start_domestic_context
from agent_registry import get_agent_name, get_agent_category

# Inicializar contextos em background se necessário
start_global_context()
start_domestic_context()


class DashboardDataService:
    def __init__(self, dsn: str = DB_DSN):
        self.dsn = dsn

    def _get_connection(self):
        return psycopg2.connect(self.dsn)

    def get_market_snapshot(self, ticker: str = "WDOU26") -> dict:
        """
        Compila o snapshot completo de microestrutura para o dashboard em tempo real.
        """
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        ts_start = f"{today_str} 00:00:00"
        ts_end = f"{today_str} 23:59:59"

        # Se for fim de semana ou fora do pregão sem trades hoje, busca a última data com trades
        target_date = today_str
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT MAX(ts::date) FROM trades WHERE ticker = %s;
                """, (ticker,))
                row = cur.fetchone()
                if row and row[0]:
                    target_date = row[0].strftime("%Y-%m-%d")

        ts_start = f"{target_date} 00:00:00"
        ts_end = f"{target_date} 23:59:59"
        ref_date = datetime.strptime(target_date, "%Y-%m-%d").date()

        # 1. Obter Estatísticas de Preço do Ativo
        day_open = 0.0
        day_high = 0.0
        day_low = 0.0
        last_price = 0.0
        total_trades = 0
        total_qty = 0

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*), MIN(price), MAX(price), SUM(qty)
                    FROM trades
                    WHERE ticker = %s AND ts >= %s AND ts <= %s;
                """, (ticker, ts_start, ts_end))
                stats = cur.fetchone()
                if stats and stats[0] and stats[0] > 0:
                    total_trades = stats[0]
                    day_low = to_real_points(stats[1], ticker)
                    day_high = to_real_points(stats[2], ticker)
                    total_qty = stats[3] or 0

                # Preço de Abertura
                cur.execute("""
                    SELECT price FROM trades
                    WHERE ticker = %s AND ts >= %s AND ts <= %s
                    ORDER BY ts ASC LIMIT 1;
                """, (ticker, ts_start, ts_end))
                row_open = cur.fetchone()
                if row_open:
                    day_open = to_real_points(row_open[0], ticker)

                # Último Preço
                cur.execute("""
                    SELECT price FROM trades
                    WHERE ticker = %s AND ts >= %s AND ts <= %s
                    ORDER BY ts DESC LIMIT 1;
                """, (ticker, ts_start, ts_end))
                row_last = cur.fetchone()
                if row_last:
                    last_price = to_real_points(row_last[0], ticker)

        day_range = round(day_high - day_low, 2) if day_high >= day_low else 0.0
        delta_open = round(last_price - day_open, 2) if day_open > 0 else 0.0

        # 2. Obter Regime de Mercado
        regime_info = get_market_regime(ticker, datetime.combine(ref_date, datetime.min.time()) + timedelta(hours=17))
        regime_name = regime_info.get("regime", "LATERALIDADE_AMPLA")
        step = regime_info.get("harmonic_step", 15.0)
        is_chop = regime_info.get("is_chop_zone", False)
        relative_pos = regime_info.get("relative_pos", 0.5)

        # 3. Construir Grade Harmônica (Ladder)
        harmonic_ladder = []
        anchor = day_open if day_open > 0 else last_price
        levels = [
            (4, "Exaustão Máxima / R4", "resistencia"),
            (3, "Resistência Institucional 3", "resistencia"),
            (2, "Resistência Institucional 2", "resistencia"),
            (1, "Resistência 1 / Alvo de Alta", "resistencia"),
            (0, "Eixo Central / Abertura", "eixo"),
            (-1, "Suporte 1 / Alvo de Baixa", "suporte"),
            (-2, "Suporte Institucional 2", "suporte"),
            (-3, "Suporte Institucional 3", "suporte"),
            (-4, "Exaustão Máxima / S4", "suporte"),
        ]

        closest_level = None
        min_dist = 999999.0

        for mult, role, ltype in levels:
            p_level = round(anchor + (mult * step), 2)
            dist = round(abs(last_price - p_level), 2) if last_price > 0 else 0.0
            if dist < min_dist:
                min_dist = dist
                closest_level = mult

            harmonic_ladder.append({
                "multiplier": mult,
                "name": f"+{mult}º Harmônico" if mult > 0 else (f"{mult}º Harmônico" if mult < 0 else "Abertura"),
                "price": p_level,
                "price_formatted": format_price_b3(p_level, ticker),
                "distance_pts": dist,
                "role": role,
                "type": ltype,
                "is_closest": False
            })

        for h in harmonic_ladder:
            if h["multiplier"] == closest_level:
                h["is_closest"] = True

        # 4. Top Big Players no Ativo
        top_buyers = []
        top_sellers = []
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        t.agent_id,
                        COALESCE(r.broker_name, 'Agente ' || t.agent_id) as broker_name,
                        COALESCE(r.broker_abbr, CAST(t.agent_id AS text)) as broker_abbr,
                        SUM(CASE WHEN t.side = 1 THEN t.qty WHEN t.side = 2 THEN -t.qty ELSE 0 END) as net_qty,
                        SUM(CASE WHEN t.side = 1 THEN t.qty ELSE 0 END) as buy_qty,
                        SUM(CASE WHEN t.side = 2 THEN t.qty ELSE 0 END) as sell_qty,
                        SUM(t.qty) as turnover
                    FROM (
                        SELECT buy_agent as agent_id, 1 as side, qty FROM trades WHERE ticker = %s AND ts >= %s AND ts <= %s
                        UNION ALL
                        SELECT sell_agent as agent_id, 2 as side, qty FROM trades WHERE ticker = %s AND ts >= %s AND ts <= %s
                    ) t
                    LEFT JOIN agent_registry r ON t.agent_id = r.agent_id
                    GROUP BY t.agent_id, r.broker_name, r.broker_abbr
                    ORDER BY net_qty DESC;
                """, (ticker, ts_start, ts_end, ticker, ts_start, ts_end))
                agents_data = cur.fetchall()

                # Compradores
                for a in agents_data[:6]:
                    if a[3] > 0:
                        top_buyers.append({
                            "id": a[0],
                            "name": a[1],
                            "abbr": a[2],
                            "net_qty": a[3],
                            "buy_qty": a[4],
                            "turnover": a[6],
                        })

                # Vendedores
                for a in sorted(agents_data, key=lambda x: x[3])[:6]:
                    if a[3] < 0:
                        top_sellers.append({
                            "id": a[0],
                            "name": a[1],
                            "abbr": a[2],
                            "net_qty": a[3],
                            "sell_qty": a[5],
                            "turnover": a[6],
                        })

        # 5. Contexto Macro Global e Doméstico
        global_ctx = get_global_context()
        domestic_ctx = get_domestic_context()
        dxy_var = global_ctx.get("dxy_var", 0.0) if global_ctx else 0.0
        dxy_price = global_ctx.get("dxy_price", 0.0) if global_ctx else 0.0
        spx_var = global_ctx.get("spx_var", 0.0) if global_ctx else 0.0
        spx_price = global_ctx.get("spx_price", 0.0) if global_ctx else 0.0
        win_delta = domestic_ctx.get("win_delta_pts", 0.0) if domestic_ctx else 0.0
        di1_delta = domestic_ctx.get("di1_delta_pts", 0.0) if domestic_ctx else 0.0

        # Alinhamento Macro
        macro_score = 0
        if dxy_var > 0.1: macro_score += 1
        elif dxy_var < -0.1: macro_score -= 1
        if spx_var < -0.3: macro_score += 1
        elif spx_var > 0.3: macro_score -= 1
        if win_delta < -300: macro_score += 1
        elif win_delta > 300: macro_score -= 1
        if di1_delta > 5: macro_score += 1
        elif di1_delta < -5: macro_score -= 1

        macro_status = "NEUTRO"
        macro_label = "Contexto Macro Neutro — Seguir gerenciamento padrão"
        if macro_score >= 2:
            macro_status = "ALTA_DOLAR"
            macro_label = "Macro Favorável à Compra (DXY Alto / WIN em Queda)"
        elif macro_score <= -2:
            macro_status = "BAIXA_DOLAR"
            macro_label = "Macro Favorável à Venda (DXY Fraco / WIN em Alta)"

        # 6. Sinais Recentes
        recent_signals = []
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT 
                        id, ticker, ts, signal_type, direction, price_at_signal,
                        context, outcome_pts, outcome_window
                    FROM signals
                    WHERE ticker = %s AND ts >= %s AND ts <= %s
                    ORDER BY ts DESC
                    LIMIT 20;
                """, (ticker, ts_start, ts_end))
                raw_signals = cur.fetchall()

                for s in raw_signals:
                    ctx = s.get("context") or {}
                    ml_conv = ctx.get("ml_conviction")
                    p_sig = float(s.get("price_at_signal") or 0.0)
                    dir_val = s.get("direction", 0)

                    # Tier ML
                    tier = "LOW"
                    if ml_conv is not None:
                        if ml_conv >= 32.0:
                            tier = "SNIPER"
                        elif ml_conv >= 24.0:
                            tier = "CONVICTION"

                    # Stop e Alvo Recomendados
                    rec_stop = p_sig - 2.0 if dir_val == 1 else p_sig + 2.0
                    rec_gain = p_sig + 2.5 if dir_val == 1 else p_sig - 2.5
                    
                    if s["signal_type"] == "DISTRIBUICAO_TOPO":
                        rec_stop = max(p_sig + 2.0, (day_high or p_sig) + 1.0)
                    elif s["signal_type"] == "ACUMULACAO_FUNDO":
                        rec_stop = min(p_sig - 2.0, (day_low or p_sig) - 1.0)

                    recent_signals.append({
                        "id": s["id"],
                        "signal_type": s["signal_type"],
                        "direction": dir_val,
                        "direction_label": "COMPRA" if dir_val == 1 else ("VENDA" if dir_val == -1 else "NEUTRO"),
                        "price": p_sig,
                        "price_formatted": format_price_b3(p_sig, ticker),
                        "stop_formatted": format_price_b3(rec_stop, ticker),
                        "target_formatted": format_price_b3(rec_gain, ticker),
                        "ml_conviction": ml_conv,
                        "ml_tier": tier,
                        "outcome_pts": float(s["outcome_pts"]) if s["outcome_pts"] is not None else None,
                        "time_str": s["ts"].strftime("%H:%M:%S") if s.get("ts") else "",
                        "context": ctx
                    })

        return {
            "ticker": ticker,
            "session_date": target_date,
            "server_time": now.strftime("%H:%M:%S"),
            "price": {
                "last": last_price,
                "last_formatted": format_price_b3(last_price, ticker),
                "open": day_open,
                "open_formatted": format_price_b3(day_open, ticker),
                "high": day_high,
                "high_formatted": format_price_b3(day_high, ticker),
                "low": day_low,
                "low_formatted": format_price_b3(day_low, ticker),
                "range": day_range,
                "delta_open": delta_open,
                "total_trades": total_trades,
                "total_qty": total_qty,
            },
            "regime": {
                "name": regime_name,
                "description": regime_info.get("description", ""),
                "harmonic_step": step,
                "is_chop_zone": is_chop,
                "relative_pos": relative_pos,
                "range_ratio": regime_info.get("range_ratio", 1.0),
                "recommended_gain": regime_info.get("recommended_gain", 2.5),
                "recommended_stop": regime_info.get("recommended_stop", 2.0),
            },
            "macro": {
                "dxy_var": dxy_var,
                "dxy_price": dxy_price,
                "spx_var": spx_var,
                "spx_price": spx_price,
                "win_delta_pts": win_delta,
                "di1_delta_bps": di1_delta,
                "status": macro_status,
                "label": macro_label,
            },
            "harmonic_ladder": harmonic_ladder,
            "players": {
                "buyers": top_buyers,
                "sellers": top_sellers,
            },
            "recent_signals": recent_signals
        }


# Instância Singleton
_data_service = DashboardDataService()


def get_dashboard_data(ticker: str = "WDOU26") -> dict:
    return _data_service.get_market_snapshot(ticker)


if __name__ == "__main__":
    import json
    data = get_dashboard_data("WDOU26")
    print(json.dumps(data, indent=2, default=str))
