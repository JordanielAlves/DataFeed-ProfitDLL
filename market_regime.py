"""
market_regime.py
Módulo de Detecção Adaptativa de Regime de Mercado — ProfitDLL
Analisa a amplitude acumulada do dia, volatilidade em relação ao harmônico
e fluxo intradiário para classificar o regime de mercado em tempo real.
"""

import logging
from datetime import datetime, date, timedelta
import psycopg2
from config import DB_DSN
from price_utils import to_real_points

try:
    from dynamic_harmonics import get_daily_harmonic_step
except ImportError:
    get_daily_harmonic_step = lambda d: 16.0

log = logging.getLogger("MarketRegime")


class MarketRegimeDetector:
    """
    Classifica o regime de mercado em tempo real:
      - CONSOLIDACAO_ESTREITA: Mercado travado em caixote curto (amplitude < 1.2x do Harmônico).
      - LATERALIDADE_AMPLA: Mercado oscilando em caixote amplo entre suportes e resistências.
      - EXPANSAO_DIRECIONAL: Mercado em tendência/rompimento forte com deslocamento de níveis.
    """

    def __init__(self, dsn: str = DB_DSN, cache_ttl_sec: int = 30):
        self.dsn = dsn
        self.cache_ttl_sec = cache_ttl_sec
        self._cache = {}

    def get_regime(self, ticker: str, current_ts: datetime = None) -> dict:
        """
        Retorna as métricas e o regime do ativo para o timestamp informado.
        """
        if current_ts is None:
            current_ts = datetime.now()

        today_str = current_ts.strftime("%Y-%m-%d")
        cache_key = f"{ticker}_{today_str}"
        now_time = datetime.now()

        # Checar cache em memória para não sobrecarregar o DB
        cached = self._cache.get(cache_key)
        if cached and (now_time - cached["cached_at"]).total_seconds() < self.cache_ttl_sec:
            return cached["data"]

        # 1. Obter Step Harmônico Histórico (ex: 16.0 pts)
        step = get_daily_harmonic_step(current_ts.date()) if get_daily_harmonic_step else 16.0

        # 2. Consultar estatísticas de preço do dia no PostgreSQL
        d_start = f"{today_str} 00:00:00"
        d_end = f"{today_str} 23:59:59"

        day_open = None
        day_high = None
        day_low = None
        day_last = None
        total_trades = 0

        try:
            with psycopg2.connect(self.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT MIN(price), MAX(price), COUNT(*)
                        FROM trades
                        WHERE ticker = %s AND ts >= %s AND ts <= %s;
                    """, (ticker, d_start, d_end))
                    row = cur.fetchone()
                    if row and row[0] is not None and row[2] > 0:
                        day_low = to_real_points(row[0], ticker)
                        day_high = to_real_points(row[1], ticker)
                        total_trades = row[2]

                    # Abertura do dia
                    cur.execute("""
                        SELECT price FROM trades
                        WHERE ticker = %s AND ts >= %s AND ts <= %s
                        ORDER BY ts ASC LIMIT 1;
                    """, (ticker, d_start, d_end))
                    row_open = cur.fetchone()
                    if row_open:
                        day_open = to_real_points(row_open[0], ticker)

                    # Último preço do dia
                    cur.execute("""
                        SELECT price FROM trades
                        WHERE ticker = %s AND ts >= %s AND ts <= %s
                        ORDER BY ts DESC LIMIT 1;
                    """, (ticker, d_start, d_end))
                    row_last = cur.fetchone()
                    if row_last:
                        day_last = to_real_points(row_last[0], ticker)

        except Exception as e:
            log.debug(f"Erro ao consultar dados de regime para {ticker}: {e}")

        # Fallbacks defensivos caso o mercado ainda não tenha trades
        if day_open is None or day_high is None or day_low is None:
            data = {
                "regime": "INDEFINIDO",
                "day_range": 0.0,
                "harmonic_step": step,
                "range_ratio": 0.0,
                "day_open": day_open or 0.0,
                "day_high": day_high or 0.0,
                "day_low": day_low or 0.0,
                "day_last": day_last or 0.0,
                "total_trades": total_trades,
                "recommended_gain": 2.5,
                "recommended_stop": 2.0,
                "description": "Aguardando volume de abertura do pregão"
            }
            return data

        day_range = round(day_high - day_low, 2)
        # Razão entre a amplitude do dia e o Harmônico de 45 dias
        range_ratio = round(day_range / max(1.0, step), 2)

        # 3. Classificação de Regime Intradiário
        if range_ratio <= 1.3:
            regime = "CONSOLIDACAO_ESTREITA"
            desc = f"Caixote Curto (Amp={day_range:.1f}p vs H={step:.1f}p) — Reversão à Média"
            rec_gain = 1.5
            rec_stop = 1.5
        elif range_ratio >= 2.5:
            regime = "EXPANSAO_DIRECIONAL"
            desc = f"Tendência / Expansão Forte (Amp={day_range:.1f}p) — Seguir Fluxo"
            rec_gain = 4.0
            rec_stop = 2.5
        else:
            regime = "LATERALIDADE_AMPLA"
            desc = f"Oscilação Moderada (Amp={day_range:.1f}p) — Operar Extremos de Caixote"
            rec_gain = 2.5
            rec_stop = 2.0

        # Posição relativa do preço dentro do range do dia (0.0 = mínima, 1.0 = máxima)
        ref_price = day_last if day_last is not None else day_open
        relative_pos = round((ref_price - day_low) / max(0.5, day_range), 2) if day_range > 0 else 0.5
        relative_pos = max(0.0, min(1.0, relative_pos))

        # Zona de Miolo / Chop: Terço central do range em dias de caixote / lateralidade
        is_chop_zone = (0.35 <= relative_pos <= 0.65) and (regime in ["CONSOLIDACAO_ESTREITA", "LATERALIDADE_AMPLA"])

        data = {
            "regime": regime,
            "day_range": day_range,
            "harmonic_step": step,
            "range_ratio": range_ratio,
            "relative_pos": relative_pos,
            "is_chop_zone": is_chop_zone,
            "day_open": day_open,
            "day_high": day_high,
            "day_low": day_low,
            "day_last": day_last,
            "total_trades": total_trades,
            "recommended_gain": rec_gain,
            "recommended_stop": rec_stop,
            "description": desc
        }

        self._cache[cache_key] = {"cached_at": now_time, "data": data}
        return data


# Instância Singleton
_detector = MarketRegimeDetector()


def get_market_regime(ticker: str, current_ts: datetime = None) -> dict:
    return _detector.get_regime(ticker, current_ts)


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    reg = get_market_regime("WDOU26")
    print(json.dumps(reg, indent=2, default=str))
