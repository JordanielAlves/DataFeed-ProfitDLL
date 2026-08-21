"""
alerts.py
=========
Módulo de alertas assíncronos com suporte a Telegram e log local.

Interface pública
-----------------
    start_alert_worker()          – inicia a thread de despacho (chamar uma vez)
    stop_alert_worker(timeout=5)  – encerra graciosamente a thread
    send_alert(message, level)    – enfileira um alerta (nunca bloqueia)

Níveis suportados: 'INFO', 'WARNING', 'CRITICAL'

Configuração (config.py):
    TELEGRAM = {
        'token':   '',     # token do BotFather
        'chat_id': '',     # ID do chat / canal
        'enabled': False,  # True apenas quando configurado
    }

Comportamento quando Telegram não configurado:
    - Loga localmente em logs/alerts.log
    - NÃO lança exceção, NÃO bloqueia o coletor
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Configuração do logger local de alertas
# ---------------------------------------------------------------------------
_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_alert_logger = logging.getLogger("alerts")
_alert_logger.setLevel(logging.DEBUG)
_alert_logger.propagate = False  # não contaminar o logger raiz

if not _alert_logger.handlers:
    _file_handler = TimedRotatingFileHandler(
        filename=str(_LOG_DIR / "alerts.log"),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    _file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                          datefmt="%Y-%m-%d %H:%M:%S")
    )
    _alert_logger.addHandler(_file_handler)

    # Também ecoa no console (útil em modo interativo)
    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(
        logging.Formatter("%(asctime)s ALERT [%(levelname)s] %(message)s",
                          datefmt="%H:%M:%S")
    )
    _alert_logger.addHandler(_console_handler)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
Level = Literal["INFO", "WARNING", "CRITICAL"]

_PREFIXES: dict[str, str] = {
    "INFO":     "ℹ️ [INFO]",
    "WARNING":  "⚠️ [WARNING]",
    "CRITICAL": "🔴 [CRÍTICO]",
}

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_RATE_LIMIT_SEC: float = 1.0   # mínimo de segundos entre mensagens Telegram

# ---------------------------------------------------------------------------
# Estado interno da fila / worker
# ---------------------------------------------------------------------------
_alert_queue: queue.Queue[tuple[str, str] | None] = queue.Queue(maxsize=1_000)
_worker_thread: threading.Thread | None = None
_stop_event = threading.Event()


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------
def _load_telegram_config() -> dict:
    """Carrega config.TELEGRAM de forma segura (sem importar na carga do módulo)."""
    try:
        import config  # type: ignore[import-untyped]
        return getattr(config, "TELEGRAM", {})
    except Exception:
        return {}


def _telegram_enabled(cfg: dict) -> bool:
    """Retorna True somente se Telegram estiver habilitado e configurado."""
    return bool(
        cfg.get("enabled")
        and cfg.get("token", "").strip()
        and cfg.get("chat_id", "").strip()
    )


def _post_telegram(token: str, chat_id: str, text: str) -> bool:
    """
    Faz POST para a API do Telegram.

    Returns:
        True em caso de sucesso, False caso contrário (loga o erro).
    """
    url = _TELEGRAM_API.format(token=token)
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return True
            _alert_logger.warning("Telegram HTTP %s: %s", resp.status, resp.read())
            return False
    except urllib.error.HTTPError as exc:
        _alert_logger.error("Telegram HTTPError %s: %s", exc.code, exc.read())
    except urllib.error.URLError as exc:
        _alert_logger.error("Telegram URLError: %s", exc.reason)
    except Exception as exc:  # noqa: BLE001
        _alert_logger.error("Telegram erro inesperado: %s", exc)
    return False


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------
def _worker() -> None:
    """
    Thread daemon que consome a fila de alertas.

    - Loga SEMPRE no arquivo local.
    - Envia ao Telegram somente se habilitado, respeitando o rate-limit.
    """
    _alert_logger.info("Alert worker iniciado.")
    last_telegram_ts: float = 0.0

    while not _stop_event.is_set():
        try:
            item = _alert_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        if item is None:
            # Sentinela de encerramento
            _alert_queue.task_done()
            break

        message, level = item
        prefix = _PREFIXES.get(level, _PREFIXES["INFO"])
        full_text = f"{prefix} {message}"

        # --- Log local (sempre) ---
        log_level = {
            "INFO":     logging.INFO,
            "WARNING":  logging.WARNING,
            "CRITICAL": logging.CRITICAL,
        }.get(level, logging.INFO)
        _alert_logger.log(log_level, message)

        # --- Telegram (se configurado) ---
        cfg = _load_telegram_config()
        if _telegram_enabled(cfg):
            # Rate-limit: aguarda se necessário (sem bloquear o lock da fila)
            elapsed = time.monotonic() - last_telegram_ts
            wait = _RATE_LIMIT_SEC - elapsed
            if wait > 0:
                time.sleep(wait)

            success = _post_telegram(cfg["token"], cfg["chat_id"], full_text)
            if success:
                last_telegram_ts = time.monotonic()

        _alert_queue.task_done()

    _alert_logger.info("Alert worker encerrado.")


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------
def start_alert_worker() -> None:
    """
    Inicia a thread daemon de despacho de alertas.
    Deve ser chamada uma única vez (ex.: em main.py ou watchdog.py).
    Chamadas subsequentes são ignoradas se o worker já estiver ativo.
    """
    global _worker_thread

    if _worker_thread is not None and _worker_thread.is_alive():
        _alert_logger.debug("Alert worker já está em execução — ignorando start.")
        return

    _stop_event.clear()
    _worker_thread = threading.Thread(
        target=_worker,
        name="alert-worker",
        daemon=True,   # encerra junto com o processo principal
    )
    _worker_thread.start()


def stop_alert_worker(timeout: float = 5.0) -> None:
    """
    Para graciosamente o worker:
    1. Enfileira sentinela None para encerrar o loop interno.
    2. Sinaliza o stop_event.
    3. Aguarda até ``timeout`` segundos pelo join.
    """
    global _worker_thread

    if _worker_thread is None or not _worker_thread.is_alive():
        return

    _stop_event.set()
    try:
        _alert_queue.put_nowait(None)   # sentinela
    except queue.Full:
        pass

    _worker_thread.join(timeout=timeout)
    if _worker_thread.is_alive():
        _alert_logger.warning("Alert worker não encerrou no tempo limite de %.1fs.", timeout)
    _worker_thread = None


def send_alert(message: str, level: Level = "INFO") -> None:
    """
    Enfileira um alerta para despacho assíncrono.

    Nunca bloqueia o chamador: se a fila estiver cheia, descarta o alerta
    e loga um aviso localmente.

    Args:
        message: Texto do alerta.
        level:   'INFO' | 'WARNING' | 'CRITICAL'
    """
    if level not in _PREFIXES:
        level = "INFO"

    # Garantir que o worker esteja rodando mesmo se start não foi chamado
    if _worker_thread is None or not _worker_thread.is_alive():
        start_alert_worker()

    try:
        _alert_queue.put_nowait((message, level))
    except queue.Full:
        _alert_logger.warning(
            "Fila de alertas cheia — mensagem descartada: [%s] %s", level, message
        )


# ---------------------------------------------------------------------------
# Teste rápido (python alerts.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    start_alert_worker()
    send_alert("Sistema inicializado.", level="INFO")
    send_alert("Latência alta detectada!", level="WARNING")
    send_alert("Conexão com broker perdida!", level="CRITICAL")
    time.sleep(2)
    stop_alert_worker()
    print("Teste concluído — verifique logs/alerts.log")
