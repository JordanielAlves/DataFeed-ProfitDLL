"""
ml_live_predictor.py
Módulo Preditivo de Microestrutura em Tempo Real com Inteligência Adaptativa — ProfitDLL
Monitora continuamente os dados recebidos pelo DataRecorder (PostgreSQL) durante o pregão aberto,
calcula métricas instantâneas de absorção/exaustão/CVD de Big Players, detecta o Regime de Mercado,
aplica Cooldown Espacial (anti-spam de caixote) e Filtro de Exaustão em Extremos.

Uso CLI:
    python ml_live_predictor.py --ticker WDOU26 --interval 10 --window 5
    python ml_live_predictor.py --ticker WINV26 --interval 15 --window 5
"""

import os
import sys
import time
import json
import pickle
import argparse
import logging
import warnings
import pandas as pd
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

try:
    from dynamic_harmonics import get_daily_harmonic_step, get_closest_harmonic_distance
except ImportError:
    get_daily_harmonic_step = None
    get_closest_harmonic_distance = None

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from config import DB_DSN
except ImportError:
    DB_DSN = "host=localhost port=5432 dbname=fluxo_ordens user=postgres password=postgres"

from price_utils import to_real_points, format_price_b3
from global_context import get_global_context, start_global_context
from domestic_context import get_domestic_context, start_domestic_context
from market_regime import get_market_regime
from spatial_cooldown import should_suppress_signal

try:
    from alerts import send_alert
except ImportError:
    send_alert = lambda msg, level="INFO": None

try:
    from corretoras import get_nome_corretora, get_corretora_label
except ImportError:
    get_nome_corretora = lambda x: str(x)
    get_corretora_label = lambda x: f"Corretora {x}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] live_ml — %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("live_ml")

# Constantes de horário do pregão
_MARKET_OPEN_HOUR   = 9
_MARKET_OPEN_MIN    = 0
_MARKET_CLOSE_HOUR  = 18
_MARKET_CLOSE_MIN   = 0
_PTAX_WINDOW_HOUR   = 13
_PTAX_WINDOW_MIN    = 0


def calcular_features_temporais(ts: datetime) -> dict:
    """Calcula features de sazonalidade intradiária a partir de um timestamp."""
    open_dt  = ts.replace(hour=_MARKET_OPEN_HOUR,  minute=_MARKET_OPEN_MIN,  second=0, microsecond=0)
    close_dt = ts.replace(hour=_MARKET_CLOSE_HOUR, minute=_MARKET_CLOSE_MIN, second=0, microsecond=0)
    ptax_dt  = ts.replace(hour=_PTAX_WINDOW_HOUR,  minute=_PTAX_WINDOW_MIN,  second=0, microsecond=0)

    minutes_since_open = int((ts - open_dt).total_seconds() / 60)
    minutes_to_ptax    = int((ptax_dt - ts).total_seconds() / 60)
    minutes_to_close   = int((close_dt - ts).total_seconds() / 60)

    return {
        "hour":               ts.hour,
        "minute":             ts.minute,
        "minutes_since_open": minutes_since_open,
        "minutes_to_ptax":    minutes_to_ptax,
        "minutes_to_close":   minutes_to_close,
    }


class MLLivePredictor:
    """Motor de monitoramento e emissão de alertas quantitativos adaptativos em tempo real."""

    def __init__(self, dsn: str = DB_DSN):
        self.dsn = dsn
        self.armed_combo = {}
        self.daily_open_price = {}
        self.daily_harmonic_step = {}
        self.ml_model = None
        self.ml_scaler = None
        self.ml_threshold = 0.24
        self.ml_feature_names = []
        
        # Iniciar serviços de contexto
        start_global_context()
        start_domestic_context()
        self._load_ml_model()

    def _get_daily_harmonic_step_cached(self, ticker: str, current_ts: datetime) -> float:
        """Busca o step harmônico adaptativo em cache para o dia."""
        if not get_daily_harmonic_step:
            return 16.0
            
        date_str = current_ts.strftime('%Y-%m-%d')
        cache_key = f"{ticker}_{date_str}"
        if cache_key in self.daily_harmonic_step:
            return self.daily_harmonic_step[cache_key]
            
        step = get_daily_harmonic_step(current_ts.date())
        self.daily_harmonic_step[cache_key] = step
        return step

    def _get_daily_open(self, ticker: str, current_ts: datetime) -> float:
        """Busca o preço de abertura oficial do dia no PostgreSQL em pontos reais."""
        date_str = current_ts.strftime('%Y-%m-%d')
        cache_key = f"{ticker}_{date_str}"
        if cache_key in self.daily_open_price:
            return self.daily_open_price[cache_key]

        try:
            with psycopg2.connect(self.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT price FROM trades WHERE ticker = %s AND ts >= %s::timestamp AND ts <= %s::timestamp ORDER BY ts ASC LIMIT 1",
                        (ticker, f"{date_str} 00:00:00", f"{date_str} 23:59:59")
                    )
                    row = cur.fetchone()
                    if row:
                        open_p = to_real_points(row[0], ticker)
                        self.daily_open_price[cache_key] = open_p
                        return open_p
        except Exception:
            pass
        return None

    def _load_ml_model(self):
        """Carrega o modelo supervisionado calibrado com threshold ótimo."""
        models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
        pkl_path = os.path.join(models_dir, "quant_signals_v1.pkl")
        if os.path.exists(pkl_path):
            try:
                with open(pkl_path, "rb") as f:
                    payload = pickle.load(f)
                self.ml_model = payload.get("model")
                self.ml_scaler = payload.get("scaler")
                self.ml_threshold = payload.get("optimal_threshold", 0.24)
                self.ml_feature_names = payload.get("feature_names", [])
                log.info(f"🤖 [PILAR 3 MLOps] Modelo quantitativo carregado ({len(self.ml_feature_names)} features | Threshold Ótimo: {self.ml_threshold*100:.1f}%)!")
            except Exception as e:
                log.warning(f"Erro ao carregar modelo ML em {pkl_path}: {e}")
        else:
            log.info("ℹ️ [PILAR 3 MLOps] Modelo supervisionado não encontrado em `models/quant_signals_v1.pkl`. Operando com heurística pura.")

    def _predict_ml_conviction(self, signal_type: str, direction: int, cvd_b: float, cvd_v: float, delta_p: float, total_qty: float, dist_to_macro: float = None) -> float:
        """Calcula o score de convicção supervisionado (0 a 100%)."""
        if not self.ml_model or not self.ml_feature_names:
            return None

        try:
            row_dict = {
                "direction": direction,
                "cvd_big": cvd_b,
                "cvd_varejo": cvd_v,
                "delta_p": delta_p,
                "total_qty": total_qty,
                "dist_to_macro_harmonic": dist_to_macro if dist_to_macro is not None else 10.0
            }
            try:
                from market_calendar import get_market_calendar_features
                row_dict.update(get_market_calendar_features(datetime.now()))
            except Exception:
                pass

            for fname in self.ml_feature_names:
                if fname.startswith("sig__"):
                    sig_name = fname.replace("sig__", "")
                    row_dict[fname] = 1.0 if signal_type == sig_name else 0.0
                elif fname not in row_dict:
                    row_dict[fname] = 0.0

            x_dict = {col: [row_dict.get(col, 0.0)] for col in self.ml_feature_names}
            x_df = pd.DataFrame(x_dict)[self.ml_feature_names]

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=UserWarning)
                if self.ml_scaler:
                    x_arr = self.ml_scaler.transform(x_df)
                else:
                    x_arr = x_df

                prob = self.ml_model.predict_proba(x_arr)[0][1]
            return round(prob * 100, 1)
        except Exception as e:
            log.warning(f"Erro ao calcular Score ML ao vivo: {e}")
            return None

    @staticmethod
    def print_powerline_alert(title: str, price_str: str, extra_str: str, direction: int, agents_str: str = "", details_list: list = None):
        """Imprime o alerta estilo Badges Powerline."""
        RESET = "\033[0m"
        ARROW = ""

        if direction >= 1:
            bg1, fg1_next = "\033[48;2;0;168;107m", "\033[38;2;0;168;107m"
        else:
            bg1, fg1_next = "\033[48;2;229;57;53m", "\033[38;2;229;57;53m"

        bg2, fg2_next = "\033[48;2;55;71;79m", "\033[38;2;55;71;79m"
        bg3, fg3_next = "\033[48;2;26;35;126m", "\033[38;2;26;35;126m"

        badge1 = f"{bg1}\033[1;38;2;255;255;255m  {title}  {RESET}"
        arrow1 = f"{fg1_next}{bg2}{ARROW}{RESET}"
        badge2 = f"{bg2}\033[1;38;2;255;255;255m  {price_str}  {RESET}"
        arrow2 = f"{fg2_next}{bg3}{ARROW}{RESET}"
        badge3 = f"{bg3}\033[1;38;2;255;255;255m  {extra_str}  {RESET}"
        arrow3 = f"{fg3_next}\033[49m{ARROW}{RESET}"

        print()
        print(f"{badge1}{arrow1}{badge2}{arrow2}{badge3}{arrow3}")

        if details_list:
            for i, det in enumerate(details_list):
                prefix = "  └─ " if i == len(details_list) - 1 and not agents_str else "  ├─ "
                print(f"\033[1;38;2;200;200;200m{prefix}\033[0m{det}")

        if agents_str:
            print(f"\033[1;38;2;200;200;200m  └─ \033[1;38;2;255;215;0mTop Players no Dia:\033[0m {agents_str}")
        print()

    def get_latest_session_id(self, conn, ticker: str) -> int:
        """Obtém o ID da sessão mais recente para o ativo."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM sessions WHERE ticker = %s ORDER BY started_at DESC LIMIT 1",
                (ticker,)
            )
            res = cur.fetchone()
            return res[0] if res else None

    def analisar_janela_atual(self, ticker: str, window_minutes: int = 5, current_ts: datetime = None):
        """Calcula as métricas quantitativas nos últimos N minutos de pregão."""
        if current_ts is None:
            current_ts = datetime.now()
        query_trades = """
            SELECT 
                COUNT(*) AS n_trades,
                SUM(qty) AS total_qty,
                MIN(price) AS low_p,
                MAX(price) AS high_p,
                MAX(ts) AS max_ts,
                (SELECT price FROM trades WHERE ticker = %s AND ts >= %s::timestamp - (%s * interval '1 minute') ORDER BY ts ASC LIMIT 1) AS open_p,
                (SELECT price FROM trades WHERE ticker = %s AND ts <= %s::timestamp ORDER BY ts DESC LIMIT 1) AS close_p,
                SUM(CASE WHEN qty <= 2 AND trade_type = 2 THEN qty 
                         WHEN qty <= 2 AND trade_type = 3 THEN -qty ELSE 0 END) AS cvd_varejo,
                SUM(CASE WHEN qty >= 20 AND trade_type = 2 THEN qty 
                         WHEN qty >= 20 AND trade_type = 3 THEN -qty ELSE 0 END) AS cvd_big,
                SUM(CASE WHEN trade_type = 2 THEN qty ELSE -qty END) AS cvd_total
            FROM trades
            WHERE ticker = %s AND ts >= %s::timestamp - (%s * interval '1 minute') AND ts <= %s::timestamp AND trade_type IN (2, 3)
        """
        
        query_top_agents = """
            SELECT 
                agent_id,
                (buy_qty - sell_qty) AS saldo,
                ROUND((buy_qty + sell_qty)::numeric / NULLIF(buy_trades + sell_trades, 0), 2) AS lote_med
            FROM agent_daily
            WHERE ticker = %s AND date = CURRENT_DATE
            ORDER BY ABS(buy_qty - sell_qty) DESC
            LIMIT 3
        """

        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query_trades, (ticker, current_ts, window_minutes, ticker, current_ts, ticker, current_ts, window_minutes, current_ts))
                trade_data = cur.fetchone()
                
                cur.execute(query_top_agents, (ticker,))
                top_agents = cur.fetchall()
                
                session_id = self.get_latest_session_id(conn, ticker)

        return trade_data, top_agents, session_id

    def avaliar_e_disparar_sinais(self, ticker: str, trade_data: dict, top_agents: list, session_id: int, current_ts: datetime = None):
        """Avalia a microestrutura recente, aplica filtros adaptativos e emite alertas."""
        if current_ts is None:
            current_ts = datetime.now()
        if not trade_data or not trade_data.get("n_trades") or trade_data["n_trades"] == 0:
            return None

        open_p = to_real_points(trade_data.get("open_p"), ticker)
        close_p = to_real_points(trade_data.get("close_p"), ticker)
        cvd_v = int(trade_data["cvd_varejo"] or 0)
        cvd_b = int(trade_data["cvd_big"] or 0)
        delta_p = round(close_p - open_p, 2)
        total_qty = int(trade_data["total_qty"] or 0)

        signal_type = "NEUTRAL"
        direction = 0
        strength = "Baixa"
        prob_reversao = 30.0
        msg_alerta = None

        # Limpar setup armado se passou de 120 segundos
        now = current_ts
        armed = self.armed_combo.get(ticker)
        if armed and (now - armed["time"]).total_seconds() > 120:
            self.armed_combo[ticker] = None
            armed = None

        # 1. Lógica Preditiva Primária de Microestrutura
        if cvd_b > 1200 and delta_p <= 1.5:
            signal_type = "ABSORCAO_VENDEDORA"
            direction = -1
            strength = "ALTA"
            prob_reversao = 82.5
            msg_alerta = "🔥 ABSORÇÃO VENDEDORA INSTITUCIONAL"
            self.armed_combo[ticker] = {"time": now, "direction": direction, "price": close_p, "cvd_b": cvd_b}

        elif cvd_v > 400 and cvd_b < -400:
            signal_type = "DISTRIBUICAO_TOPO"
            direction = -1
            strength = "MEDIA"
            prob_reversao = 78.0
            msg_alerta = "🎣 DISTRIBUIÇÃO INSTITUCIONAL"

        elif cvd_b < -1200 and delta_p >= -1.5:
            signal_type = "ABSORCAO_COMPRADORA"
            direction = 1
            strength = "ALTA"
            prob_reversao = 85.0
            msg_alerta = "🛡️ ABSORÇÃO COMPRADORA INSTITUCIONAL"
            self.armed_combo[ticker] = {"time": now, "direction": direction, "price": close_p, "cvd_b": cvd_b}

        elif cvd_v < -400 and cvd_b > 400:
            signal_type = "ACUMULACAO_FUNDO"
            direction = 1
            strength = "MEDIA"
            prob_reversao = 79.0
            msg_alerta = "🚀 ACUMULAÇÃO INSTITUCIONAL"

        elif cvd_b > 2500 and delta_p > 4.0:
            if armed and armed["direction"] == 1:
                signal_type = "COMBO_ABSORCAO_IMPULSO_COMPRA"
                direction = 1
                strength = "ALTA"
                prob_reversao = 92.5
                msg_alerta = "👑 COMBO DE OURO ATIVADO -> COMPRA"
                self.armed_combo[ticker] = None
            else:
                signal_type = "IMPULSO_COMPRADOR"
                direction = 1
                strength = "ALTA"
                prob_reversao = 15.0
                msg_alerta = "⚡ ROMPIMENTO / IMPULSO COMPRADOR"

        elif cvd_b < -2500 and delta_p < -4.0:
            if armed and armed["direction"] == -1:
                signal_type = "COMBO_ABSORCAO_IMPULSO_VENDA"
                direction = -1
                strength = "ALTA"
                prob_reversao = 92.5
                msg_alerta = "👑 COMBO DE OURO ATIVADO -> VENDA"
                self.armed_combo[ticker] = None
            else:
                signal_type = "IMPULSO_VENDEDOR"
                direction = -1
                strength = "ALTA"
                prob_reversao = 15.0
                msg_alerta = "⚡ ROMPIMENTO / IMPULSO VENDEDOR"

        if signal_type == "NEUTRAL":
            return "NEUTRAL"

        # 2. Obter Contexto Adaptativo de Regime de Mercado
        regime_info = get_market_regime(ticker, now)
        regime_name = regime_info.get("regime", "LATERALIDADE_AMPLA")
        day_high = regime_info.get("day_high", close_p)
        day_low = regime_info.get("day_low", close_p)
        day_open = regime_info.get("day_open", open_p)
        day_range = max(1.0, regime_info.get("day_range", 1.0))

        # 3. FILTRO DE EXAUSTÃO EM EXTREMOS (Evitar Compras de Topo e Vendas de Fundo em Caixote)
        is_exhausted = False
        exhaustion_warning = ""

        if signal_type == "IMPULSO_COMPRADOR":
            dist_to_high = day_high - close_p
            run_from_open = close_p - (day_open or open_p)
            stretch_pct = (close_p - day_low) / day_range

            if (dist_to_high <= 1.5 or stretch_pct >= 0.88) and run_from_open >= 7.0 and regime_name != "EXPANSAO_DIRECIONAL":
                is_exhausted = True
                signal_type = "IMPULSO_ESTENDIDO_TOPO"
                msg_alerta = "⚠️ IMPULSO ESTENDIDO EM TOPO (RISCO EXAUSTÃO)"
                exhaustion_warning = f"⚠️ [ALERTA DE EXAUSTÃO: COMPRA ESTICADA A {dist_to_high:.1f}p DA MÁXIMA DO DIA EM CAIXOTE!]"

        elif signal_type == "IMPULSO_VENDEDOR":
            dist_to_low = close_p - day_low
            run_down_from_open = (day_open or open_p) - close_p
            stretch_pct = (day_high - close_p) / day_range

            if (dist_to_low <= 1.5 or stretch_pct >= 0.88) and run_down_from_open >= 7.0 and regime_name != "EXPANSAO_DIRECIONAL":
                is_exhausted = True
                signal_type = "IMPULSO_ESTENDIDO_FUNDO"
                msg_alerta = "⚠️ IMPULSO ESTENDIDO EM FUNDO (RISCO EXAUSTÃO)"
                exhaustion_warning = f"⚠️ [ALERTA DE EXAUSTÃO: VENDA ESTICADA A {dist_to_low:.1f}p DA MÍNIMA DO DIA EM CAIXOTE!]"

        # 4. COOLDOWN ESPACIAL INTELIGENTE (Anti-Spam de Caixote)
        suppress, test_count, suppress_reason = should_suppress_signal(
            ticker, signal_type, close_p, current_ts=now, tolerance_pts=2.0, ttl_seconds=180
        )

        if suppress:
            log.debug(f"[SPATIAL COOLDOWN] Sinal suprimido: {signal_type} @ {close_p} -> {suppress_reason}")
            return signal_type

        # 5. Cálculo de Distância Harmônica & Score ML
        step = self._get_daily_harmonic_step_cached(ticker, now)
        dist_to_macro_harmonic = None
        harmonic_alert = ""
        if day_open is not None and get_closest_harmonic_distance:
            dist_to_macro_harmonic = get_closest_harmonic_distance(close_p, day_open, step)

        ml_conviction = self._predict_ml_conviction(signal_type, direction, cvd_b, cvd_v, delta_p, total_qty, dist_to_macro_harmonic)

        # Se houver exaustão detectada, ajustar score defensivamente
        if is_exhausted and ml_conviction is not None:
            ml_conviction = round(ml_conviction * 0.65, 1)

        # 5.1 FILTRO DE ZONA DE MIOLO (CHOP ZONE FILTER)
        # Em caixotes / lateralidade ampla, absorções no miolo (35% a 65% do range) com baixa convicção são ruído puro
        is_chop = regime_info.get("is_chop_zone", False)
        base_threshold = round(self.ml_threshold * 100, 1)
        if is_chop and "ABSORCAO" in signal_type and "COMBO" not in signal_type:
            if ml_conviction is None or ml_conviction < base_threshold:
                log.debug(
                    f"[CHOP ZONE FILTER] Sinal de absorção de miolo suprimido: {signal_type} @ {close_p} "
                    f"(Pos={regime_info.get('relative_pos'):.2f} | ML={ml_conviction}%)"
                )
                return signal_type

        # 6. Teste de Níveis de Harmônicos
        if day_open is not None and step is not None:
            dist_to_open = close_p - day_open
            mod_step = abs(dist_to_open) % step
            tol = min(1.0, step * 0.15)
            if mod_step <= tol or mod_step >= (step - tol):
                multiple = round(abs(dist_to_open) / step)
                if multiple > 0:
                    direction_str = "Superior" if dist_to_open > 0 else "Inferior"
                    harmonic_val = day_open + (multiple * step if dist_to_open > 0 else -multiple * step)
                    harmonic_alert = f"🎯 [FREQUÊNCIA HARMÔNICA] Testando {multiple}º Harmônico {direction_str} (H={harmonic_val:.2f} | Passo={step:.1f} pts)"

        # 7. Montar Detalhes e Injetar Contexto Macro
        agents_str = ", ".join([f"{get_corretora_label(a['agent_id'])} ({a['saldo']:+d} ctrs)" for a in top_agents]) if top_agents else ""
        details_list = []

        # Tag de Regime de Mercado no Topo
        details_list.append(f"📊 \033[1;34m[REGIME: {regime_name}]\033[0m {regime_info.get('description', '')}")

        if exhaustion_warning:
            details_list.append(f"\033[1;33m{exhaustion_warning}\033[0m")

        if harmonic_alert:
            details_list.append(f"\033[1;35m{harmonic_alert}\033[0m")

        global_ctx = get_global_context()
        domestic_ctx = get_domestic_context()
        macro_info = "🌐 Macro: "
        context_alignment = 0

        if global_ctx:
            dxy = global_ctx.get('dxy_var', 0.0)
            spx = global_ctx.get('spx_var', 0.0)
            macro_info += f"DXY={dxy:+.2f}% | SPX={spx:+.2f}% "
            if dxy > 0.1: context_alignment += 1
            elif dxy < -0.1: context_alignment -= 1
            if spx < -0.3: context_alignment += 1
            elif spx > 0.3: context_alignment -= 1

        if domestic_ctx:
            win = domestic_ctx.get('win_delta_pts', 0.0)
            di1 = domestic_ctx.get('di1_delta_pts', 0.0)
            macro_info += f"| WIN={win:+.0f}pts | DI1={di1:+.1f}bps"
            if win < -300: context_alignment += 1
            elif win > 300: context_alignment -= 1
            if di1 > 5: context_alignment += 1
            elif di1 < -5: context_alignment -= 1

        details_list.append(macro_info)

        if direction == 1 and context_alignment >= 2:
            details_list.append("🟢 \033[1;32m[CONTEXTO MACRO FAVORÁVEL: ALONGAR ALVO NA COMPRA!]\033[0m")
        elif direction == -1 and context_alignment <= -2:
            details_list.append("🔴 \033[1;31m[CONTEXTO MACRO FAVORÁVEL: ALONGAR ALVO NA VENDA!]\033[0m")
        elif (direction == 1 and context_alignment < 0) or (direction == -1 and context_alignment > 0):
            details_list.append("⚠️ \033[1;33m[CONTEXTO MACRO CONTRÁRIO: FAZER PARCIAIS CURTAS (SCALP)!]\033[0m")
        else:
            details_list.append("⚖️ [CONTEXTO MACRO NEUTRO: SEGUIR GERENCIAMENTO PADRÃO]")

        if "ABSORCAO" in signal_type and "COMBO" not in signal_type:
            details_list.append(f"Agressão de Big Players ({cvd_b:+d} ctrs) absorvida no book passivo.")
            details_list.append(f"Preço travado na região de {format_price_b3(close_p, ticker)} (Δ = {delta_p:+.2f} pts). Setup ARMADO (TTL 120s)!")
        elif "COMBO" in signal_type:
            details_list.append(f"✅ Ignição confirmada após Absorção previa! Rompimento com tração de Big Players ({cvd_b:+d} ctrs).")
            details_list.append(f"Preço de acionamento: {format_price_b3(close_p, ticker)} (Δ = {delta_p:+.2f} pts) | Alvo rápido liberado!")
        elif "IMPULSO" in signal_type:
            details_list.append(f"Big Players agredindo pesado ({cvd_b:+d} ctrs) rompendo níveis técnicos (Δ = {delta_p:+.2f} pts).")
        elif "DISTRIBUICAO" in signal_type or "ACUMULACAO" in signal_type:
            details_list.append(f"Divergência institucional: Varejo ({cvd_v:+d} ctrs) vs Big Players ({cvd_b:+d} ctrs).")
            if signal_type == "DISTRIBUICAO_TOPO":
                stop_ref = (day_high or close_p) + 1.0
                if step and day_open:
                    dist_to_open = close_p - day_open
                    next_harm = day_open + (int(dist_to_open / step) + 1) * step if dist_to_open >= 0 else day_open
                    if next_harm > close_p:
                        stop_ref = max(stop_ref, next_harm + 1.0)
                details_list.append(f"🎯 \033[1;36m[STOP TÉCNICO SUGERIDO: ACIMA DE {format_price_b3(stop_ref, ticker)} (PROTEÇÃO CONTRA SWEEP DE LIQUIDEZ)]\033[0m")
            elif signal_type == "ACUMULACAO_FUNDO":
                stop_ref = (day_low or close_p) - 1.0
                if step and day_open:
                    dist_to_open = close_p - day_open
                    next_harm = day_open + (int(dist_to_open / step) - 1) * step if dist_to_open <= 0 else day_open
                    if next_harm < close_p:
                        stop_ref = min(stop_ref, next_harm - 1.0)
                details_list.append(f"🎯 \033[1;36m[STOP TÉCNICO SUGERIDO: ABAIXO DE {format_price_b3(stop_ref, ticker)} (PROTEÇÃO CONTRA SWEEP DE LIQUIDEZ)]\033[0m")

        # 8. Avaliação Quantitativa Calibrada
        sniper_threshold = 32.0
        base_threshold = round(self.ml_threshold * 100, 1)

        if ml_conviction is not None:
            if ml_conviction >= sniper_threshold and not is_exhausted:
                details_list.insert(0, f"🤖 \033[1;32m[ML HIGH CONVICTION ⭐] Convicção Quantitativa: {ml_conviction}%\033[0m (IA supervisionada valida entrada Sniper — Win Rate ~85.9%!)")
                strength += " | ML: ⭐ ALTA"
                prob_reversao = ml_conviction
            elif ml_conviction < base_threshold or is_exhausted:
                details_list.insert(0, f"🤖 \033[1;33m[ML LOW CONVICTION ⚠️] Convicção Quantitativa: {ml_conviction}%\033[0m (Abaixo do limiar ótimo de {base_threshold}% — Risco de Stop)")
                strength += " | ML: ⚠️ BAIXA"
                prob_reversao = ml_conviction
            else:
                details_list.insert(0, f"🤖 \033[1;36m[ML CONVICTION] Convicção Quantitativa: {ml_conviction}%\033[0m (Setup regular acima do limiar {base_threshold}%)")
                prob_reversao = ml_conviction

        # 9. Disparar Badges Powerline no Terminal
        self.print_powerline_alert(
            title=f"{ticker} | {msg_alerta}",
            price_str=f"PREÇO: {format_price_b3(close_p, ticker)} (Δ {delta_p:+.2f} pts)",
            extra_str=f"PROB / FORÇA: {prob_reversao}% ({strength})",
            direction=direction,
            agents_str=agents_str,
            details_list=details_list
        )

        # 10. Disparar Notificação Telegram (Apenas Sniper / Combo sem exaustão)
        if ml_conviction and (ml_conviction >= sniper_threshold or "COMBO" in signal_type) and not is_exhausted and direction != 0:
            dxy_val = global_ctx.get("dxy_var", 0.0) if global_ctx else 0.0
            spx_val = global_ctx.get("spx_var", 0.0) if global_ctx else 0.0
            win_val = domestic_ctx.get("win_delta_pts", 0.0) if domestic_ctx else 0.0
            dir_icon = "🟢 COMPRA" if direction == 1 else "🔴 VENDA"
            rec_gain = regime_info.get("recommended_gain", 2.5)
            rec_stop = regime_info.get("recommended_stop", 2.0)
            tg_msg = (
                f"🚨 <b>SINAL QUANT B3 — {ticker}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚡ <b>Setup:</b> {msg_alerta}\n"
                f"🧭 <b>Direção:</b> {dir_icon}\n"
                f"💰 <b>Preço:</b> <code>{format_price_b3(close_p, ticker)}</code> (Δ {delta_p:+.2f} pts)\n"
                f"🤖 <b>Score ML:</b> <b>{ml_conviction:.1f}%</b> ⭐ (Filtro Sniper Ativado)\n"
                f"📊 <b>Regime:</b> {regime_name}\n"
                f"🌐 <b>Macro:</b> DXY {dxy_val:+.2f}% | SPX {spx_val:+.2f}% | WIN {win_val:+.0f} pts\n"
                f"🎯 <b>Alvo Adaptativo:</b> +{rec_gain:.1f} pts | <b>Stop:</b> {rec_stop:.1f} pts\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            )
            try:
                send_alert(tg_msg, level="INFO")
            except Exception as e:
                log.debug(f"Falha ao enviar alerta Telegram: {e}")

        # 11. Gravação no PostgreSQL em Pontos Reais
        enriched_agents = []
        for a in top_agents:
            d = dict(a)
            d["corretora"] = get_corretora_label(a["agent_id"])
            enriched_agents.append(d)

        signal_ts_ref = trade_data.get("max_ts") or datetime.now()
        if hasattr(signal_ts_ref, "tzinfo") and signal_ts_ref.tzinfo is not None:
            signal_ts_ref = signal_ts_ref.replace(tzinfo=None)

        if session_id:
            self.registrar_sinal(session_id, ticker, signal_type, direction, close_p, {
                "cvd_varejo":    cvd_v,
                "cvd_big":       cvd_b,
                "delta_p":       delta_p,
                "prob_reversao": prob_reversao,
                "ml_conviction": ml_conviction,
                "total_qty":     total_qty,
                "regime":        regime_name,
                "is_exhausted":  is_exhausted,
                "dist_to_macro_harmonic": dist_to_macro_harmonic,
                "global_dxy": global_ctx.get("dxy_var") if global_ctx else None,
                "global_spx": global_ctx.get("spx_var") if global_ctx else None,
                "domestic_win": domestic_ctx.get("win_delta_pts") if domestic_ctx else None,
                "domestic_di1": domestic_ctx.get("di1_delta_pts") if domestic_ctx else None,
                **calcular_features_temporais(signal_ts_ref),
                "top_agents":    enriched_agents,
            }, signal_ts=signal_ts_ref)

        return signal_type

    def registrar_sinal(self, session_id: int, ticker: str, signal_type: str, direction: int, price: float, context: dict, signal_ts=None):
        """Salva o alerta disparado na tabela `signals` para validação quantitativa posterior."""
        query = """
            INSERT INTO signals (session_id, ticker, ts, signal_type, direction, price_at_signal, context)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        ts_val = signal_ts if signal_ts else datetime.now()
        try:
            with psycopg2.connect(self.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (
                        session_id, ticker, ts_val, signal_type, direction, price, json.dumps(context, default=float)
                    ))
            log.info(f"Sinal gravado no banco de dados: {signal_type} ({ticker} @ {format_price_b3(price, ticker)} | ts: {ts_val})")
        except Exception as e:
            log.error(f"Erro ao salvar sinal no banco: {e}")

    def loop_monitoramento(self, ticker: str, interval_seconds: int = 10, window_minutes: int = 5):
        """Executa em loop contínuo monitorando o fluxo em tempo real."""
        log.info(f"Iniciando monitoramento ML ADAPTATIVO em TEMPO REAL para {ticker} (Janela de {window_minutes}m, Polling a cada {interval_seconds}s)...")
        print("Pressione Ctrl+C para encerrar o monitoramento.")
        try:
            while True:
                now = datetime.now()
                trade_data, top_agents, session_id = self.analisar_janela_atual(ticker, window_minutes, now)
                self.avaliar_e_disparar_sinais(ticker, trade_data, top_agents, session_id, now)
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            log.info("Monitoramento encerrado pelo usuário.")


def main():
    parser = argparse.ArgumentParser(description="Módulo Preditivo ML em Tempo Real com Inteligência Adaptativa - ProfitDLL")
    parser.add_argument("--ticker", type=str, default="WDOU26", help="Ativo para monitorar (padrão: WDOU26)")
    parser.add_argument("--interval", type=int, default=10, help="Intervalo de verificação em segundos (padrão: 10s)")
    parser.add_argument("--window", type=int, default=5, help="Janela móvel de análise em minutos (padrão: 5m)")
    parser.add_argument("--once", action="store_true", help="Executa apenas uma leitura pontual (sem loop)")
    args = parser.parse_args()

    predictor = MLLivePredictor()
    ticker = args.ticker.upper()

    if args.once:
        now = datetime.now()
        trade_data, top_agents, session_id = predictor.analisar_janela_atual(ticker, args.window, now)
        sig = predictor.avaliar_e_disparar_sinais(ticker, trade_data, top_agents, session_id, now)
        if sig == "NEUTRAL":
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {ticker} — Fluxo Neutro / Sem anomalias na janela de {args.window} min.")
    else:
        predictor.loop_monitoramento(ticker, interval_seconds=args.interval, window_minutes=args.window)


if __name__ == "__main__":
    main()
