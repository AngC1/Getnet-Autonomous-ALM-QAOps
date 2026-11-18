"""Modelos de datos y validacion pura del Veredicto (Requirement 4).

Sin E/S: todo el modulo es determinista y se puede probar con hypothesis.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

VALORES_VEREDICTO = ("CORRECTO", "INCORRECTO", "SIN_LOGO", "AMBIGUO")
VALORES_LOGO = ("CORRECTO", "INCORRECTO")
RECOMENDACION_MIN = 1
RECOMENDACION_MAX = 500

ASSET_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
VERDICT_PREFIX = "brand/verdicts/"


@dataclass(frozen=True)
class Evidence:
    """Evidencia: instante (s; 0 en imagenes), caja normalizada y logo detectado."""

    timestamp_s: Union[int, float]
    bbox: Tuple[float, float, float, float]
    logo_detectado: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp_s": self.timestamp_s,
            "bbox": list(self.bbox),
            "logo_detectado": self.logo_detectado,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Evidence":
        x0, y0, x1, y1 = d["bbox"]
        return Evidence(d["timestamp_s"], (x0, y0, x1, y1), d["logo_detectado"])


@dataclass(frozen=True)
class Verdict:
    veredicto: str
    confianza: Union[int, float]
    evidencias: List[Evidence] = field(default_factory=list)
    recomendacion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "veredicto": self.veredicto,
            "confianza": self.confianza,
            "evidencias": [e.to_dict() for e in self.evidencias],
            "recomendacion": self.recomendacion,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Verdict":
        """Construye un Verdict desde un dict ya validado."""
        return Verdict(
            d["veredicto"],
            d["confianza"],
            [Evidence.from_dict(e) for e in d["evidencias"]],
            d["recomendacion"],
        )


@dataclass(frozen=True)
class FrameVerdict:
    """Veredicto de un fotograma muestreado de un video."""

    timestamp_s: Union[int, float]
    veredicto: str
    confianza: Union[int, float] = 0.0
    evidencias: List[Evidence] = field(default_factory=list)


@dataclass(frozen=True)
class VerifyError:
    """Resultado de error: nunca lleva Valor_Veredicto."""

    asset_id: Optional[str]
    motivo: str


# --------------------------------------------------------------------------
# Identificadores y claves S3
# --------------------------------------------------------------------------
def is_valid_asset_id(asset_id: Any) -> bool:
    return isinstance(asset_id, str) and ASSET_ID_RE.fullmatch(asset_id) is not None


def verdict_s3_key(asset_id: str) -> str:
    if not is_valid_asset_id(asset_id):
        raise ValueError("id_activo invalido")
    return "%s%s.json" % (VERDICT_PREFIX, asset_id)


# --------------------------------------------------------------------------
# Validacion
# --------------------------------------------------------------------------
def _is_number(x: Any) -> bool:
    return (
        isinstance(x, (int, float))
        and not isinstance(x, bool)
        and math.isfinite(x)
    )


def _validate_bbox(bbox: Any) -> bool:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False
    if not all(_is_number(v) for v in bbox):
        return False
    x0, y0, x1, y1 = bbox
    return 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1


def validate_verdict(obj: Any) -> List[str]:
    """Devuelve la lista de campos invalidos (vacia si el Veredicto es valido)."""
    if isinstance(obj, Verdict):
        obj = obj.to_dict()
    if not isinstance(obj, dict):
        return ["veredicto: debe ser un objeto"]

    errors: List[str] = []

    valor = obj.get("veredicto")
    valor_ok = isinstance(valor, str) and valor in VALORES_VEREDICTO
    if not valor_ok:
        errors.append("veredicto: debe ser uno de %s" % ", ".join(VALORES_VEREDICTO))

    conf = obj.get("confianza")
    if not (_is_number(conf) and 0 <= conf <= 1):
        errors.append("confianza: debe ser un numero entre 0 y 1")

    rec = obj.get("recomendacion")
    rec_ok = isinstance(rec, str) and RECOMENDACION_MIN <= len(rec) <= RECOMENDACION_MAX
    if not rec_ok:
        errors.append(
            "recomendacion: debe ser texto de %d a %d caracteres"
            % (RECOMENDACION_MIN, RECOMENDACION_MAX)
        )

    evs = obj.get("evidencias")
    evs_ok = isinstance(evs, list)
    if not evs_ok:
        errors.append("evidencias: debe ser una lista")
    else:
        for i, ev in enumerate(evs):
            pre = "evidencias[%d]" % i
            if not isinstance(ev, dict):
                errors.append("%s: debe ser un objeto" % pre)
                evs_ok = False
                continue
            ts = ev.get("timestamp_s")
            if not (_is_number(ts) and ts >= 0):
                errors.append("%s.timestamp_s: debe ser un numero >= 0" % pre)
                evs_ok = False
            if not _validate_bbox(ev.get("bbox")):
                errors.append(
                    "%s.bbox: debe cumplir 0 <= x_min < x_max <= 1 y 0 <= y_min < y_max <= 1"
                    % pre
                )
                evs_ok = False
            logo = ev.get("logo_detectado")
            if not (isinstance(logo, str) and logo in VALORES_LOGO):
                errors.append(
                    "%s.logo_detectado: debe ser uno de %s" % (pre, ", ".join(VALORES_LOGO))
                )
                evs_ok = False

    # Reglas por veredicto (solo si los campos implicados tienen forma valida).
    if valor_ok and isinstance(evs, list):
        if valor == "INCORRECTO":
            if len(evs) < 1:
                errors.append("evidencias: INCORRECTO requiere al menos una evidencia")
            if rec_ok and "ayesa digital" not in rec.lower():
                errors.append("recomendacion: INCORRECTO debe indicar sustituir por Ayesa Digital")
        elif valor == "CORRECTO":
            if len(evs) < 1:
                errors.append("evidencias: CORRECTO requiere al menos una evidencia")
        elif valor == "SIN_LOGO":
            if len(evs) != 0:
                errors.append("evidencias: SIN_LOGO requiere una lista vacia")

    return errors


# --------------------------------------------------------------------------
# Serializacion
# --------------------------------------------------------------------------
def verdict_to_json(v: Verdict) -> str:
    return json.dumps(v.to_dict(), ensure_ascii=False, sort_keys=True)


def verdict_from_json(s: str) -> Verdict:
    """Parsea y valida; lanza ValueError nombrando cada campo invalido."""
    try:
        obj = json.loads(s)
    except (TypeError, ValueError) as exc:
        raise ValueError("veredicto: JSON no valido (%s)" % type(exc).__name__)
    errors = validate_verdict(obj)
    if errors:
        raise ValueError("; ".join(errors))
    return Verdict.from_dict(obj)
