"""
spatial_cooldown.py
Gerenciador de Cooldown Espacial e Agregação de Sinais por Faixa de Preço — ProfitDLL
Elimina a repetição de múltiplos alertas (spam) para o mesmo evento de microestrutura
dentro de um mesmo nível de suporte/resistência ou caixote de absorção.
"""

import logging
from datetime import datetime, timedelta

log = logging.getLogger("SpatialCooldown")


class SpatialCooldownManager:
    """
    Controla o disparo de alertas agrupando eventos por nível de preço e tempo.
    
    Regra:
      Se um sinal de ABSORÇÃO ocorrer em 5.169,50, novos sinais do mesmo tipo
      dentro de ±2.0 pontos (5.167,50 a 5.171,50) serão silenciados pelo período de TTL
      (ex: 180 segundos), contabilizando apenas o número de testes/defesas daquele nível.
    """

    def __init__(self, default_tolerance_pts: float = 2.0, default_ttl_sec: int = 180):
        self.default_tolerance_pts = default_tolerance_pts
        self.default_ttl_sec = default_ttl_sec
        # Mapa: key -> { base_price, ts, last_seen_ts, test_count }
        self.zones = {}

    def should_suppress(
        self,
        ticker: str,
        signal_type: str,
        price: float,
        current_ts: datetime = None,
        tolerance_pts: float = None,
        ttl_seconds: int = None
    ) -> tuple[bool, int, str]:
        """
        Avalia se o sinal deve ser suprimido ou liberado para exibição/alerta.
        
        Retorna:
          (suppress: bool, test_count: int, reason: str)
        """
        if current_ts is None:
            current_ts = datetime.now()

        tol = tolerance_pts if tolerance_pts is not None else self.default_tolerance_pts
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_sec

        # Para absorções e distribuições, o cooldown espacial é estrito
        # Para impulsos/rompimentos, a tolerância de preço é mais justa (1.0 pt)
        if "IMPULSO" in signal_type:
            tol = min(tol, 1.0)
            ttl = min(ttl, 60)

        key = f"{ticker}_{signal_type}"
        zone = self.zones.get(key)

        if zone is None:
            # Primeira ocorrência do setup neste ativo
            self.zones[key] = {
                "base_price": price,
                "ts": current_ts,
                "last_seen_ts": current_ts,
                "test_count": 1
            }
            return False, 1, "Primeira ocorrência do setup"

        dist = abs(price - zone["base_price"])
        elapsed = (current_ts - zone["ts"]).total_seconds()

        # Se ainda está dentro da mesma faixa e dentro do tempo de vida (TTL)
        if dist <= tol and elapsed <= ttl:
            zone["test_count"] += 1
            zone["last_seen_ts"] = current_ts
            reason = (
                f"Faixa {zone['base_price']:.2f} (±{tol:.1f}p) já notificada há "
                f"{int(elapsed)}s [Defesa/Teste #{zone['test_count']}]"
            )
            return True, zone["test_count"], reason

        # Rompeu a faixa ou passou do tempo limite -> Inicia nova zona
        zone["base_price"] = price
        zone["ts"] = current_ts
        zone["last_seen_ts"] = current_ts
        count = zone["test_count"]
        zone["test_count"] = 1

        if dist > tol:
            reason = f"Preço deslocou {dist:.1f}p para fora da faixa anterior ({zone['base_price']:.2f})"
        else:
            reason = f"TTL expirado ({int(elapsed)}s > {ttl}s)"

        return False, 1, reason


# Instância Singleton
_spatial_cooldown = SpatialCooldownManager()


def should_suppress_signal(
    ticker: str,
    signal_type: str,
    price: float,
    current_ts: datetime = None,
    tolerance_pts: float = 2.0,
    ttl_seconds: int = 180
) -> tuple[bool, int, str]:
    return _spatial_cooldown.should_suppress(
        ticker, signal_type, price, current_ts, tolerance_pts, ttl_seconds
    )
