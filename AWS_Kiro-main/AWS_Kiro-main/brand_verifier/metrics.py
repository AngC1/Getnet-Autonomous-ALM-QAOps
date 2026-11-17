"""Metricas de ejecucion para el dashboard (contrato fijo, claves bajo ``brand/metrics/``).

- ``brand/metrics/<id>.json``  por activo verificado (tokens, latencia, fechas).
- ``brand/metrics/comfyui.json`` trabajos ComfyUI (solo el host de AgentUrl).
- ``brand/metrics/run.json`` y ``runs.json`` (ultimas 50) por ejecucion de ``run``.
- ``brand/metrics/models.json`` uso acumulado por modelo (triaje, Stable Audio).
Todo es best-effort: un fallo al escribir metricas nunca rompe el flujo principal.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

KEY_PREFIX = "brand/"
METRICS_PREFIX = "brand/metrics/"
RUNS_MAX = 50
REGION = "us-east-1"
SVC_VISION = "Amazon Bedrock Converse (visión)"
SVC_TEXT = "Amazon Bedrock Converse (texto)"
SVC_AUDIO = "Stability AI Stable Audio"

log = logging.getLogger(__name__)
_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def metrics_key(name: str) -> str:
    return "%s%s.json" % (METRICS_PREFIX, name)


class UsageStats:
    """Acumula uso de Converse (todos los intentos y fotogramas) de un activo."""

    def __init__(self, asset_id: str, tipo: str, model_id: str, region: str = REGION):
        self.asset_id, self.tipo, self.model_id, self.region = asset_id, tipo, model_id, region
        self.calls = 0
        self.frames = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.latency_ms = 0
        self.started_at = now_iso()
        self.finished_at: Optional[str] = None

    def add_response(self, resp: Any) -> None:
        self.calls += 1
        if not isinstance(resp, dict):
            return
        usage = resp.get("usage") or {}
        met = resp.get("metrics") or {}
        self.input_tokens += _int(usage.get("inputTokens"))
        self.output_tokens += _int(usage.get("outputTokens"))
        self.latency_ms += _int(met.get("latencyMs"))

    def to_dict(self, veredicto: Optional[str]) -> Dict[str, Any]:
        return {
            "id": self.asset_id, "tipo": self.tipo, "model_id": self.model_id,
            "region": self.region, "calls": self.calls, "frames": self.frames,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "latency_ms": self.latency_ms, "started_at": self.started_at,
            "finished_at": self.finished_at or now_iso(), "veredicto": veredicto,
        }


def _int(v: Any) -> int:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _local_file(out_dir: Optional[str], key: str) -> Optional[Path]:
    if out_dir is None:
        return None
    rel = key[len(KEY_PREFIX):] if key.startswith(KEY_PREFIX) else key
    return Path(out_dir) / rel


def read_json(s3: Any, out_dir: Optional[str], name: str) -> Any:
    """Lee metricas previas de S3 y, si no hay, de la copia local. None si no existen."""
    key = metrics_key(name)
    if s3 is not None:
        try:
            return json.loads(s3.get(key).decode("utf-8"))
        except Exception:  # noqa: BLE001 - ausente o ilegible
            pass
    path = _local_file(out_dir, key)
    if path is not None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return None


def write_json(s3: Any, out_dir: Optional[str], name: str, obj: Any) -> bool:
    """Escribe en S3 y copia local. Devuelve False (sin lanzar) si algo falla."""
    key = metrics_key(name)
    body = (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    ok = True
    if s3 is not None:
        try:
            s3.put(key, body, asset_id=None, content_type="application/json")
        except Exception as exc:  # noqa: BLE001
            log.warning("metricas: no se pudo subir %s (%s)", key, type(exc).__name__)
            ok = False
    path = _local_file(out_dir, key)
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        except OSError as exc:
            log.warning("metricas: no se pudo escribir %s (%s)", path, type(exc).__name__)
            ok = False
    return ok


def write_asset(s3: Any, out_dir: Optional[str], stats: UsageStats, veredicto: Optional[str]) -> Dict[str, Any]:
    stats.finished_at = now_iso()
    data = stats.to_dict(veredicto)
    write_json(s3, out_dir, stats.asset_id, data)
    return data


def merge_comfyui(s3: Any, out_dir: Optional[str], agent_url_host: str,
                  jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fusiona ``jobs`` con comfyui.json existente por (id, step); los nuevos ganan."""
    with _lock:
        prev = read_json(s3, out_dir, "comfyui")
        merged: Dict[Any, Dict[str, Any]] = {}
        if isinstance(prev, dict):
            for j in prev.get("jobs", []):
                if isinstance(j, dict):
                    merged[(j.get("id"), j.get("step"))] = j
        for j in jobs:
            merged[(j["id"], j["step"])] = j
        data = {"agent_url_host": agent_url_host, "jobs": list(merged.values())}
        write_json(s3, out_dir, "comfyui", data)
    return data


def record_model(s3: Any, out_dir: Optional[str], model_id: str, service: str, *,
                 calls: int = 1, input_tokens: int = 0, output_tokens: int = 0) -> None:
    """Acumula uso en models.json: {model_id: {service, calls, input_tokens, output_tokens}}."""
    try:
        with _lock:
            data = read_json(s3, out_dir, "models")
            if not isinstance(data, dict):
                data = {}
            cur = data.get(model_id)
            if not isinstance(cur, dict):
                cur = {"service": service, "calls": 0, "input_tokens": 0, "output_tokens": 0}
            cur["service"] = service
            cur["calls"] = _int(cur.get("calls")) + calls
            cur["input_tokens"] = _int(cur.get("input_tokens")) + input_tokens
            cur["output_tokens"] = _int(cur.get("output_tokens")) + output_tokens
            data[model_id] = cur
            write_json(s3, out_dir, "models", data)
    except Exception as exc:  # noqa: BLE001 - nunca rompe el flujo
        log.warning("metricas: models.json no actualizado (%s)", type(exc).__name__)


def write_run(s3: Any, out_dir: Optional[str], run: Dict[str, Any]) -> None:
    write_json(s3, out_dir, "run", run)
    with _lock:
        prev = read_json(s3, out_dir, "runs")
        runs = [r for r in prev if isinstance(r, dict)] if isinstance(prev, list) else []
        runs.append(run)
        write_json(s3, out_dir, "runs", runs[-RUNS_MAX:])
