"""Nucleo puro del Verificador_Marca (Requirements 2.6, 2.7, 3.x, 4.4).

Sin E/S: agregacion de fotogramas, muestreo, seleccion de evidencias,
normalizacion de la salida del modelo y validacion de imagen de entrada.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Union

from .models import Evidence, FrameVerdict, VALORES_VEREDICTO

MAX_VIDEO_SECONDS = 60
MAX_IMAGE_BYTES = 5 * 1024 * 1024
SUPPORTED_IMAGE_FORMATS = ("PNG", "JPEG", "WEBP")
_FORMAT_ALIASES = {"JPG": "JPEG"}

RECOMENDACION_MAX = 500
_LOGO_DESCARTABLE = ("AMBIGUO", "SIN_LOGO")
_SUSTITUIR = "Sustituir el logotipo por Ayesa Digital."


# --------------------------------------------------------------------------
# Agregacion de video (Properties 1 y 2)
# --------------------------------------------------------------------------
def _valor(fv: Union[str, FrameVerdict]) -> str:
    return fv if isinstance(fv, str) else fv.veredicto


def aggregate_frames(frame_verdicts: Iterable[Union[str, FrameVerdict]]) -> str:
    """INCORRECTO > AMBIGUO > CORRECTO; todos SIN_LOGO -> SIN_LOGO.

    Calculo sobre el conjunto de valores, por tanto independiente del orden.
    Acepta FrameVerdict o directamente Valor_Veredicto. Lista vacia -> ValueError.
    """
    valores = {_valor(fv) for fv in frame_verdicts}
    if not valores:
        raise ValueError("aggregate_frames requiere al menos un fotograma")
    desconocidos = valores - set(VALORES_VEREDICTO)
    if desconocidos:
        raise ValueError("Valor_Veredicto desconocido: %s" % ", ".join(sorted(desconocidos)))
    for valor in ("INCORRECTO", "AMBIGUO", "CORRECTO"):
        if valor in valores:
            return valor
    return "SIN_LOGO"


# --------------------------------------------------------------------------
# Muestreo a 1 fps (Property 4)
# --------------------------------------------------------------------------
def sample_timestamps(duration_s: Union[int, float]) -> List[int]:
    """Marcas de tiempo (s) a 1 fps: 0, 1, 2... sin exceder la duracion ni 60 muestras."""
    if not isinstance(duration_s, (int, float)) or isinstance(duration_s, bool):
        raise ValueError("duration_s debe ser numerico")
    if not math.isfinite(duration_s) or duration_s <= 0:
        return []
    count = min(max(int(math.floor(duration_s)), 1), MAX_VIDEO_SECONDS)
    return list(range(count))


# --------------------------------------------------------------------------
# Seleccion de evidencias de video (Property 3)
# --------------------------------------------------------------------------
def select_video_evidence(frames: Iterable[FrameVerdict]) -> List[Evidence]:
    """Todas las evidencias de fotogramas INCORRECTO/AMBIGUO y al menos una CORRECTO."""
    frames = list(frames)
    selected: List[Evidence] = []
    for f in frames:
        if f.veredicto in ("INCORRECTO", "AMBIGUO"):
            selected.extend(f.evidencias)
    for f in frames:
        if f.veredicto == "CORRECTO" and f.evidencias:
            selected.append(f.evidencias[0])
            break
    return selected


# --------------------------------------------------------------------------
# Normalizacion de la salida del modelo (Property 8, Requirement 4.4)
# --------------------------------------------------------------------------
def normalize_model_output(raw: Any) -> Any:
    """Aplica las reglas de decision a la salida cruda (dict) del modelo.

    - Evidencias de ambos logos -> INCORRECTO, conservando las evidencias
      (al menos una por logotipo).
    - Evidencias con logo_detectado AMBIGUO/SIN_LOGO -> se descartan; si no queda
      ninguna y el veredicto era CORRECTO/INCORRECTO, pasa a AMBIGUO.
    - SIN_LOGO -> evidencias vacias.
    - INCORRECTO -> la recomendacion menciona Ayesa Digital.
    Entradas que no son dict o sin forma reconocible se devuelven sin cambios
    para que validate_verdict las rechace.
    """
    if not isinstance(raw, dict):
        return raw
    out: Dict[str, Any] = dict(raw)
    evs = out.get("evidencias")
    if isinstance(evs, list):
        # logo_detectado solo admite CORRECTO/INCORRECTO: una evidencia con AMBIGUO
        # (o SIN_LOGO) no senala un logotipo concreto y se descarta.
        kept = [e for e in evs
                if not (isinstance(e, dict) and e.get("logo_detectado") in _LOGO_DESCARTABLE)]
        dropped = len(kept) != len(evs)
        out["evidencias"] = kept
        logos = {e.get("logo_detectado") for e in kept if isinstance(e, dict)}
        if "CORRECTO" in logos and "INCORRECTO" in logos:
            out["veredicto"] = "INCORRECTO"
        elif dropped and not kept and out.get("veredicto") in ("CORRECTO", "INCORRECTO"):
            # Sin evidencia valida no se puede afirmar nada: AMBIGUO admite lista vacia.
            out["veredicto"] = "AMBIGUO"

    if out.get("veredicto") == "SIN_LOGO":
        out["evidencias"] = []

    if out.get("veredicto") == "INCORRECTO":
        rec = out.get("recomendacion")
        if not isinstance(rec, str) or not rec.strip():
            out["recomendacion"] = _SUSTITUIR
        elif "ayesa digital" not in rec.lower():
            suffix = " " + _SUSTITUIR
            base = rec[: RECOMENDACION_MAX - len(suffix)].rstrip()
            out["recomendacion"] = base + suffix
    return out


# --------------------------------------------------------------------------
# Imagen soportada (Property 9)
# --------------------------------------------------------------------------
def is_supported_image(fmt: Optional[str], size_bytes: Union[int, float]) -> bool:
    """PNG/JPEG/WebP y tamano <= 5 MB (5 * 1024 * 1024 bytes)."""
    if not isinstance(fmt, str):
        return False
    if not isinstance(size_bytes, (int, float)) or isinstance(size_bytes, bool):
        return False
    if size_bytes < 0 or not math.isfinite(size_bytes):
        return False
    name = fmt.strip().lstrip(".").upper()
    name = _FORMAT_ALIASES.get(name, name)
    return name in SUPPORTED_IMAGE_FORMATS and size_bytes <= MAX_IMAGE_BYTES
