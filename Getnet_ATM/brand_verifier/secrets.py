"""Gestor_Secretos: lectura de secretos en tiempo de ejecucion y redaccion de logs.

Los secretos se leen de AWS (Outputs de CloudFormation / Secrets Manager) y, si no
estan disponibles, de variables de entorno. Nunca se escriben a disco.
Importar como ``brand_verifier.secrets`` (no choca con la stdlib ``secrets``).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

REGION = "us-east-2"
TIMEOUT_S = 30.0
REDACTED = "[REDACTED]"

AGENT_URL_OUTPUT = "AgentUrl"
AGENT_TOKEN_SECRET_OUTPUT = "AgentTokenSecret"
ENV_AGENT_URL = "COMFY_URL"
ENV_AGENT_TOKEN = "COMFY_AGENT_TOKEN"

_lock = threading.Lock()
_loaded: List[str] = []  # valores de secretos cargados (solo en memoria)


class SecretNotFound(Exception):
    """El secreto no se encontro en ninguna fuente. Contiene solo el NOMBRE."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name

    def __str__(self) -> str:
        return self.name


# --------------------------------------------------------------------------
# Redaccion de logs
# --------------------------------------------------------------------------
def register_secret(value: Optional[str]) -> None:
    """Registra un valor para que los logs lo sustituyan por [REDACTED]."""
    if not value:
        return
    with _lock:
        if value not in _loaded:
            _loaded.append(value)


def clear_registered_secrets() -> None:
    with _lock:
        _loaded.clear()


def redact(text: str) -> str:
    with _lock:
        values = sorted(_loaded, key=len, reverse=True)
    for v in values:
        if v in text:
            text = text.replace(v, REDACTED)
    return text


class RedactionFilter(logging.Filter):
    """Sustituye en el mensaje de log los valores de secretos cargados."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        redacted = redact(message)
        if redacted != message or record.args:
            record.msg = redacted
            record.args = None
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


_FILTER = RedactionFilter()
_factory_installed = False


def install_redaction_filter() -> RedactionFilter:
    """Instala el filtro de forma global (todos los loggers) de forma idempotente.

    Se engancha a la fabrica de LogRecord para cubrir cualquier logger, no solo root.
    """
    global _factory_installed
    with _lock:
        if _factory_installed:
            return _FILTER
        _factory_installed = True
        old_factory = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = old_factory(*args, **kwargs)
        _FILTER.filter(record)
        return record

    logging.setLogRecordFactory(factory)
    return _FILTER


install_redaction_filter()


# --------------------------------------------------------------------------
# Clientes inyectables
# --------------------------------------------------------------------------
_cfn_client: Any = None
_sm_client: Any = None


def set_clients(cloudformation: Any = None, secretsmanager: Any = None) -> None:
    """Inyecta clientes boto3 (o falsos en tests). ``None`` restablece el valor por defecto."""
    global _cfn_client, _sm_client
    _cfn_client = cloudformation
    _sm_client = secretsmanager


def _make_client(service: str) -> Any:
    import boto3
    from botocore.config import Config

    cfg = Config(
        connect_timeout=5,
        read_timeout=10,
        retries={"max_attempts": 1},
    )
    return boto3.client(service, region_name=REGION, config=cfg)


def _cfn() -> Any:
    return _cfn_client if _cfn_client is not None else _make_client("cloudformation")


def _sm() -> Any:
    return _sm_client if _sm_client is not None else _make_client("secretsmanager")


# --------------------------------------------------------------------------
# Lectura con timeout total
# --------------------------------------------------------------------------
def _run_with_deadline(fn: Callable[[], Optional[str]], deadline: float) -> Optional[str]:
    """Ejecuta ``fn`` en un hilo; devuelve None si falla o excede el plazo."""
    result: Dict[str, Optional[str]] = {"v": None}

    def target() -> None:
        try:
            result["v"] = fn()
        except Exception:
            result["v"] = None

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(remaining)
    return result["v"] if not t.is_alive() else None


def _stack_output(key: str) -> Optional[str]:
    client = _cfn()
    token = None
    while True:
        kwargs = {"NextToken": token} if token else {}
        resp = client.describe_stacks(**kwargs)
        for stack in resp.get("Stacks", []):
            for out in stack.get("Outputs", []) or []:
                if out.get("OutputKey") == key and out.get("OutputValue"):
                    return out["OutputValue"]
        token = resp.get("NextToken")
        if not token:
            return None


def _secret_value(secret_id: str) -> Optional[str]:
    resp = _sm().get_secret_value(SecretId=secret_id)
    return resp.get("SecretString") or None


def _resolve(name: str, sources: List[Callable[[], Optional[str]]], timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    for source in sources:
        value = _run_with_deadline(source, deadline)
        if value and value.strip():
            value = value.strip()
            register_secret(value)
            return value
    raise SecretNotFound(name)


def _env(name: str) -> Callable[[], Optional[str]]:
    return lambda: os.environ.get(name)


def get_agent_url(timeout_s: float = TIMEOUT_S) -> str:
    """Output ``AgentUrl`` (us-east-2) -> variable de entorno ``COMFY_URL``."""
    return _resolve(
        AGENT_URL_OUTPUT,
        [lambda: _stack_output(AGENT_URL_OUTPUT), _env(ENV_AGENT_URL)],
        timeout_s,
    )


def get_agent_token(timeout_s: float = TIMEOUT_S) -> str:
    """Secrets Manager ``AgentTokenSecret`` (us-east-2) -> ``COMFY_AGENT_TOKEN``."""

    def from_aws() -> Optional[str]:
        secret_id = _stack_output(AGENT_TOKEN_SECRET_OUTPUT)
        return _secret_value(secret_id) if secret_id else None

    return _resolve(
        AGENT_TOKEN_SECRET_OUTPUT,
        [from_aws, _env(ENV_AGENT_TOKEN)],
        timeout_s,
    )


ENV_FALLBACKS = {"StabilityAIApiKey": "STABILITY_API_KEY"}


def get_optional(name: str, timeout_s: float = TIMEOUT_S) -> str:
    """Secreto opcional (usuario/clave del canvas, clave Stability): Output -> env.

    Solo en memoria; lanza ``SecretNotFound(name)`` si no existe en ninguna fuente.
    Algunos nombres tienen una variable de entorno alternativa (``ENV_FALLBACKS``).
    """
    sources = [lambda: _stack_output(name), _env(name)]
    if name in ENV_FALLBACKS:
        sources.append(_env(ENV_FALLBACKS[name]))
    return _resolve(name, sources, timeout_s)
