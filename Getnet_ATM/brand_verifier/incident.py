"""Flujo de Incidencia de ATM (Requirement 8, secundario).

- Nucleo puro: ``validate_incident``, ``redact_pan``, ``scene_prompt``,
  ``validate_triage``, ``incident_to_json`` / ``incident_from_json``.
- E/S fina e inyectable: ``process_incident`` usa ``S3IO`` y un cliente
  Bedrock Runtime (Converse API) en ``us-east-1``.
- La descripcion se persiste ya redactada (PAN enmascarado).
- Sin secretos; los tests inyectan clientes falsos (sin llamadas reales a AWS).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

REGION = "us-east-1"
TEXT_MODEL_ENV = "BRAND_TEXT_MODEL_ID"
FALLBACK_MODEL_ENV = "BRAND_MODEL_ID"
BEDROCK_TIMEOUT_S = 30
PERSIST_BUDGET_S = 5.0

DESCRIPCION_MAX = 2000
ATM_ID_MAX = 50
UBICACION_MAX = 200
TRIAGE_TEXT_MAX = 500

CATEGORIAS = ("TARJETA_RETENIDA", "TARJETA_NO_DEVUELTA", "FALLO_MANIPULACION", "OTRA")
SEVERIDADES = ("BAJA", "MEDIA", "ALTA")
ESTADO_PERSISTIDA = "PERSISTIDA"
ESTADO_TRIAJE_OK = "TRIADA"
ESTADO_TRIAJE_FALLIDO = "TRIAJE_FALLIDO"

log = logging.getLogger(__name__)

ATM_ID_RE = re.compile(r"[A-Za-z0-9-]{1,50}")
ISO_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.(?:\d{3}|\d{6}))?)?"
    r"(?:Z|[+-]\d{2}:\d{2})"
)
INCIDENT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


# --------------------------------------------------------------------------
# Validacion (PURA)
# --------------------------------------------------------------------------
def _is_iso_with_tz(value: Any) -> bool:
    if not isinstance(value, str) or ISO_RE.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def validate_incident(obj: Any) -> List[str]:
    """Devuelve la lista de campos invalidos (vacia si la Incidencia es valida)."""
    if not isinstance(obj, dict):
        return ["incidencia: debe ser un objeto"]
    errors: List[str] = []

    desc = obj.get("descripcion")
    if not (isinstance(desc, str) and 1 <= len(desc) <= DESCRIPCION_MAX):
        errors.append("descripcion: debe ser texto de 1 a %d caracteres" % DESCRIPCION_MAX)

    atm = obj.get("atm_id")
    if not (isinstance(atm, str) and ATM_ID_RE.fullmatch(atm) is not None):
        errors.append(
            "atm_id: debe tener de 1 a %d caracteres alfanumericos o guiones" % ATM_ID_MAX
        )

    ubic = obj.get("ubicacion")
    if not (isinstance(ubic, str) and 1 <= len(ubic) <= UBICACION_MAX):
        errors.append("ubicacion: debe ser texto de 1 a %d caracteres" % UBICACION_MAX)

    if not _is_iso_with_tz(obj.get("fecha_hora")):
        errors.append("fecha_hora: debe ser ISO 8601 con zona horaria")

    return errors


# --------------------------------------------------------------------------
# Redaccion de PAN (PURA)
# --------------------------------------------------------------------------
# 13-19 digitos, consecutivos o agrupados con un espacio o guion entre ellos.
_PAN_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")


def _mask_match(m: "re.Match[str]") -> str:
    s = m.group(0)
    total = sum(1 for c in s if c.isdigit())
    seen = 0
    out = []
    for c in s:
        if c.isdigit():
            seen += 1
            out.append(c if seen > total - 4 else "*")
        else:
            out.append(c)
    return "".join(out)


def redact_pan(text: str) -> str:
    """Sustituye por ``*`` todos los digitos de cada secuencia de 13-19 digitos salvo los 4 ultimos."""
    return _PAN_RE.sub(_mask_match, text)


# --------------------------------------------------------------------------
# Prompt de escena (PURA)
# --------------------------------------------------------------------------
_NUM_RUN_RE = re.compile(r"[\d*](?:[ -]?[\d*])*")
_TITLE_NAME_RE = re.compile(
    r"\b(?:Sr|Sra|Srta|Don|Do[nñ]a|D|D[ñn]a|Mr|Mrs|Ms|Miss)\.?\s+"
    r"(?:[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ'’-]+(?:\s+|\b))+"
)
_BANK_NAMES = (
    "Santander", "BBVA", "CaixaBank", "Caixa", "Bankia", "Sabadell", "Bankinter",
    "Unicaja", "Ibercaja", "Kutxabank", "Abanca", "Openbank", "Cajamar", "Liberbank",
    "ING", "Citibank", "Citi", "HSBC", "Barclays", "Chase", "JPMorgan", "Wells Fargo",
    "Bank of America", "Deutsche Bank", "BNP Paribas", "Visa", "Mastercard", "Maestro",
    "American Express", "Amex",
)
_BANK_RE = re.compile(
    r"\b(?:%s)\b" % "|".join(re.escape(b) for b in sorted(_BANK_NAMES, key=len, reverse=True)),
    re.IGNORECASE,
)
_GENERIC_BANK_RE = re.compile(
    r"\b(?:banco|bank|caja)\s+(?:de\s+|of\s+)?[A-ZÁÉÍÓÚÑ][\wáéíóúñ'-]*", re.IGNORECASE
)
SCENE_DESC_MAX = 300


def _drop_number_runs(match: "re.Match[str]") -> str:
    s = match.group(0)
    return "" if sum(1 for c in s if c.isdigit() or c == "*") >= 4 else s


def scene_prompt(incident: Dict[str, Any]) -> str:
    """Texto de escena para el video de ATM sin nombres, numeros de tarjeta ni bancos."""
    desc = incident.get("descripcion", "") if isinstance(incident, dict) else ""
    if not isinstance(desc, str):
        desc = ""
    desc = _NUM_RUN_RE.sub(_drop_number_runs, desc)
    desc = _TITLE_NAME_RE.sub("una persona ", desc)
    desc = _GENERIC_BANK_RE.sub("una entidad ", desc)
    desc = _BANK_RE.sub("", desc)
    desc = re.sub(r"\s+", " ", desc).strip()[:SCENE_DESC_MAX].strip()
    base = (
        "Cajero automatico de calle por la noche, plano medio realista, pantalla "
        "encendida mostrando el logotipo, sin personas identificables, sin texto "
        "legible y sin numeros."
    )
    return "%s Contexto de la escena: %s" % (base, desc) if desc else base


# --------------------------------------------------------------------------
# Serializacion (ida y vuelta)
# --------------------------------------------------------------------------
def incident_to_json(incident: Dict[str, Any]) -> str:
    return json.dumps(incident, ensure_ascii=False, sort_keys=True)


def incident_from_json(s: str) -> Dict[str, Any]:
    obj = json.loads(s)
    if not isinstance(obj, dict):
        raise ValueError("incidencia: debe ser un objeto")
    return obj


# --------------------------------------------------------------------------
# Triaje (esquema puro)
# --------------------------------------------------------------------------
def validate_triage(obj: Any) -> List[str]:
    if not isinstance(obj, dict):
        return ["triaje: debe ser un objeto"]
    errors: List[str] = []
    if obj.get("categoria") not in CATEGORIAS or not isinstance(obj.get("categoria"), str):
        errors.append("categoria: debe ser uno de %s" % ", ".join(CATEGORIAS))
    if obj.get("severidad") not in SEVERIDADES or not isinstance(obj.get("severidad"), str):
        errors.append("severidad: debe ser uno de %s" % ", ".join(SEVERIDADES))
    for name in ("causa_probable", "accion_recomendada"):
        v = obj.get(name)
        if not (isinstance(v, str) and 1 <= len(v) <= TRIAGE_TEXT_MAX):
            errors.append("%s: debe ser texto de 1 a %d caracteres" % (name, TRIAGE_TEXT_MAX))
    return errors


def parse_triage(text: str) -> Dict[str, Any]:
    """Extrae y valida el JSON de triaje; lanza ValueError si no es conforme."""
    s = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.DOTALL)
    if fence:
        s = fence.group(1)
    try:
        obj = json.loads(s)
    except ValueError:
        raise ValueError("triaje: JSON no valido")
    errors = validate_triage(obj)
    if errors:
        raise ValueError("; ".join(errors))
    return {k: obj[k] for k in ("categoria", "severidad", "causa_probable", "accion_recomendada")}


_TRIAGE_SYSTEM = (
    "Eres un agente de triaje de incidencias de cajeros automaticos (ATM). "
    "Responde SOLO con un objeto JSON con las claves: categoria (TARJETA_RETENIDA, "
    "TARJETA_NO_DEVUELTA, FALLO_MANIPULACION u OTRA), severidad (BAJA, MEDIA o ALTA), "
    "causa_probable (texto, max 500 caracteres) y accion_recomendada (texto, max 500 "
    "caracteres). Sin texto adicional."
)


def _text_model_id() -> str:
    model = os.environ.get(TEXT_MODEL_ENV) or os.environ.get(FALLBACK_MODEL_ENV)
    if not model:
        raise RuntimeError("modelo de texto no configurado (%s o %s)" % (TEXT_MODEL_ENV, FALLBACK_MODEL_ENV))
    return model


def _default_bedrock_client() -> Any:
    import boto3  # import perezoso: los tests inyectan un cliente falso
    from botocore.config import Config

    cfg = Config(
        connect_timeout=10,
        read_timeout=BEDROCK_TIMEOUT_S,
        retries={"max_attempts": 0},
    )
    return boto3.client("bedrock-runtime", region_name=REGION, config=cfg)


def _invoke_triage(client: Any, model_id: str, incident: Dict[str, Any],
                   usage: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    user = json.dumps(
        {
            "descripcion": incident["descripcion"],
            "atm_id": incident["atm_id"],
            "ubicacion": incident["ubicacion"],
            "fecha_hora": incident["fecha_hora"],
        },
        ensure_ascii=False,
    )
    resp = client.converse(
        modelId=model_id,
        system=[{"text": _TRIAGE_SYSTEM}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": 600, "temperature": 0},
    )
    if usage is not None:
        u = resp.get("usage") or {}
        usage["calls"] = usage.get("calls", 0) + 1
        usage["input_tokens"] = usage.get("input_tokens", 0) + int(u.get("inputTokens") or 0)
        usage["output_tokens"] = usage.get("output_tokens", 0) + int(u.get("outputTokens") or 0)
    parts = resp["output"]["message"]["content"]
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return parse_triage(text)


def triage_incident(
    incident: Dict[str, Any], client: Any = None, model_id: Optional[str] = None,
    usage: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    """Triaje con Bedrock de texto; un reintento. Devuelve None si ambos intentos fallan."""
    last: Optional[BaseException] = None
    for _ in range(2):
        try:
            if client is None:
                client = _default_bedrock_client()
            return _invoke_triage(client, model_id or _text_model_id(), incident, usage)
        except Exception as exc:  # noqa: BLE001 - cualquier fallo cuenta como intento fallido
            last = exc
            log.warning("Triaje fallido (incidencia=%s): %s", incident.get("id"), type(exc).__name__)
    log.error("Triaje agotado (incidencia=%s): %s", incident.get("id"), type(last).__name__)
    return None


# --------------------------------------------------------------------------
# Flujo completo
# --------------------------------------------------------------------------
@dataclass
class IncidentResult:
    ok: bool
    id: Optional[str] = None
    estado: Optional[str] = None
    errores: List[str] = field(default_factory=list)
    incidencia: Optional[Dict[str, Any]] = None
    triaje: Optional[Dict[str, Any]] = None


def incident_key(incident_id: str) -> str:
    if not isinstance(incident_id, str) or INCIDENT_ID_RE.fullmatch(incident_id) is None:
        raise ValueError("id de incidencia invalido")
    return "incidents/%s/incident.json" % incident_id


def triage_key(incident_id: str) -> str:
    return incident_key(incident_id)[: -len("incident.json")] + "triage.json"


def process_incident(
    obj: Any,
    s3: Any,
    bedrock_client: Any = None,
    model_id: Optional[str] = None,
    id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    clock: Callable[[], float] = time.monotonic,
    metrics_dir: Optional[str] = None,
) -> IncidentResult:
    """Valida, redacta, persiste y triaja una Incidencia.

    - Invalida: devuelve los campos invalidos y no persiste nada.
    - Valida: guarda ``incidents/<id>/incident.json`` (descripcion ya redactada).
    - Triaje correcto: guarda ``triage.json``; si falla tras un reintento el
      estado es ``TRIAJE_FALLIDO`` y no se guarda ``triage.json``.
    """
    errors = validate_incident(obj)
    if errors:
        return IncidentResult(ok=False, errores=errors)

    incident_id = id_factory()
    incident = {
        "id": incident_id,
        "descripcion": redact_pan(obj["descripcion"]),
        "atm_id": obj["atm_id"],
        "ubicacion": obj["ubicacion"],
        "fecha_hora": obj["fecha_hora"],
    }

    t0 = clock()
    s3.put(incident_key(incident_id), incident_to_json(incident).encode("utf-8"),
           asset_id=incident_id, content_type="application/json")
    elapsed = clock() - t0
    if elapsed > PERSIST_BUDGET_S:
        log.warning("Persistencia de incidencia %s tardo %.1fs (> %.0fs)", incident_id, elapsed,
                    PERSIST_BUDGET_S)

    usage: Dict[str, int] = {}
    triage = triage_incident(incident, bedrock_client, model_id, usage)
    if usage.get("calls"):
        try:
            from brand_verifier import metrics as metrics_mod
            metrics_mod.record_model(s3, metrics_dir, model_id or _text_model_id(), metrics_mod.SVC_TEXT,
                                     calls=usage["calls"], input_tokens=usage.get("input_tokens", 0),
                                     output_tokens=usage.get("output_tokens", 0))
        except Exception as exc:  # noqa: BLE001 - metricas best-effort
            log.warning("metricas de triaje no escritas (%s)", type(exc).__name__)
    if triage is None:
        return IncidentResult(ok=True, id=incident_id, estado=ESTADO_TRIAJE_FALLIDO,
                              incidencia=incident)

    s3.put(triage_key(incident_id), json.dumps(triage, ensure_ascii=False, sort_keys=True).encode("utf-8"),
           asset_id=incident_id, content_type="application/json")
    return IncidentResult(ok=True, id=incident_id, estado=ESTADO_TRIAJE_OK,
                          incidencia=incident, triaje=triage)
