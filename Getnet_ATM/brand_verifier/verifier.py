"""Verificador_Marca: imagen y video via Bedrock Converse (us-east-1).

- Rechazo previo (formato/tamano) sin invocar a Bedrock.
- Converse con muestra + Logo_Correcto + Logo_Incorrecto, timeout 30 s,
  un reintento; dos fallos -> VerifyError (sin veredicto).
- Video: fotogramas a 1 fps, agregacion pura y evidencias seleccionadas.
- Clientes (Bedrock, S3IO) y extractor de fotogramas inyectables.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from . import core
from .metrics import UsageStats
from .models import (
    Evidence,
    FrameVerdict,
    Verdict,
    VerifyError,
    is_valid_asset_id,
    validate_verdict,
    verdict_s3_key,
    verdict_to_json,
)
from .references import LOGO_CORRECTO, LOGO_INCORRECTO

REGION = "us-east-1"
MODEL_ENV = "BRAND_MODEL_ID"
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
TIMEOUT_S = 30
MAX_ATTEMPTS = 2  # intento + un reintento
DEFAULT_REF_DIR = "assets/brand"

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres un verificador de marca. Comparas el logotipo de una imagen de MUESTRA con dos referencias:
- REFERENCIA CORRECTA: logotipo "Ayesa Digital" (simbolo + wordmark 'ayesa' con la palabra 'digital' debajo).
- REFERENCIA INCORRECTA: logotipo "Ayesa" sin 'digital' (simbolo + wordmark 'ayesa' solo).

Reglas de decision:
1. Simbolo + wordmark 'ayesa' con 'digital' debajo => CORRECTO.
2. Simbolo + wordmark 'ayesa' SIN 'digital' => INCORRECTO.
3. No aparece ningun logotipo de Ayesa => SIN_LOGO (evidencias vacias).
4. Si no puedes determinar si 'digital' esta presente (borroso, tapado, muy pequeno) => AMBIGUO.
   INCORRECTO solo si ves con claridad que bajo 'ayesa' NO hay ningun texto. Si bajo 'ayesa' hay una linea de texto
   pequena, aunque ilegible, deformada o de baja resolucion, NO la declares ausente: usa AMBIGUO.
5. Si aparecen ambos logotipos (correcto e incorrecto) en la muestra => INCORRECTO, con una evidencia por cada logotipo.
Si el veredicto es INCORRECTO, la recomendacion debe indicar sustituir el logotipo por Ayesa Digital.

Responde SOLO con un objeto JSON estricto, sin texto adicional ni markdown, con esta forma:
{"veredicto": "CORRECTO|INCORRECTO|SIN_LOGO|AMBIGUO",
 "confianza": <numero entre 0 y 1>,
 "evidencias": [{"timestamp_s": 0, "bbox": [x_min, y_min, x_max, y_max], "logo_detectado": "CORRECTO|INCORRECTO"}],
 "recomendacion": "<texto de 1 a 500 caracteres>"}
bbox esta normalizada a [0,1] respecto al ancho y alto de la muestra, con 0 <= x_min < x_max <= 1 y 0 <= y_min < y_max <= 1.
logo_detectado SOLO puede ser CORRECTO o INCORRECTO (el logotipo concreto que ves en esa evidencia); nunca AMBIGUO.
Si no puedes identificar el logotipo, no incluyas esa evidencia.
CORRECTO e INCORRECTO requieren al menos una evidencia; SIN_LOGO ninguna; AMBIGUO puede llevar evidencias o ninguna."""

FrameExtractor = Callable[[Any], List[Tuple[int, bytes]]]


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _model_id() -> str:
    return os.environ.get(MODEL_ENV) or DEFAULT_MODEL_ID


def _default_client() -> Any:
    import boto3  # import perezoso
    from botocore.config import Config

    cfg = Config(read_timeout=TIMEOUT_S, connect_timeout=TIMEOUT_S, retries={"max_attempts": 1})
    return boto3.client("bedrock-runtime", region_name=REGION, config=cfg)


def _detect_format(data: bytes) -> Optional[str]:
    """Formato real de la imagen (PNG/JPEG/WEBP) o None si no es legible."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            return img.format
    except Exception:  # noqa: BLE001
        return None


_CONVERSE_FORMAT = {"PNG": "png", "JPEG": "jpeg", "WEBP": "webp"}


def _load_refs(ref_dir: Union[str, Path]) -> Tuple[bytes, bytes]:
    base = Path(ref_dir)
    return (base / LOGO_CORRECTO).read_bytes(), (base / LOGO_INCORRECTO).read_bytes()


def _image_block(data: bytes) -> Dict[str, Any]:
    fmt = _CONVERSE_FORMAT[_detect_format(data) or "PNG"]
    return {"image": {"format": fmt, "source": {"bytes": data}}}


def build_request(sample: bytes, correct: bytes, incorrect: bytes, model_id: str) -> Dict[str, Any]:
    """Peticion Converse: muestra + ambos logos de referencia etiquetados."""
    content = [
        {"text": "REFERENCIA CORRECTA (Ayesa Digital):"},
        _image_block(correct),
        {"text": "REFERENCIA INCORRECTA (Ayesa sin 'digital'):"},
        _image_block(incorrect),
        {"text": "MUESTRA a verificar:"},
        _image_block(sample),
        {"text": "Devuelve solo el JSON del veredicto."},
    ]
    return {
        "modelId": model_id,
        "system": [{"text": SYSTEM_PROMPT}],
        "messages": [{"role": "user", "content": content}],
        "inferenceConfig": {"maxTokens": 1024, "temperature": 0},
    }


def _parse_json(text: str) -> Any:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _response_text(resp: Dict[str, Any]) -> str:
    parts = resp["output"]["message"]["content"]
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


def _call_model(client: Any, request: Dict[str, Any], asset_id: Optional[str],
                stats: Optional[UsageStats] = None) -> Union[Dict[str, Any], str]:
    """Hasta MAX_ATTEMPTS intentos. Devuelve el dict valido o el motivo (str) del fallo."""
    reason = "sin intentos"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.converse(**request)
            if stats is not None:
                stats.add_response(resp)
            raw = _parse_json(_response_text(resp))
            norm = core.normalize_model_output(raw)
            errors = validate_verdict(norm)
            if not errors:
                return norm
            reason = "veredicto invalido: " + "; ".join(errors)
        except Exception as exc:  # noqa: BLE001 - cualquier fallo se reintenta
            reason = "fallo de Bedrock o salida no JSON (%s)" % type(exc).__name__
        log.warning("Verificacion fallida (activo=%s, intento %d/%d): %s",
                    asset_id, attempt, MAX_ATTEMPTS, reason)
    log.error("Verificacion fallida definitivamente (activo=%s): %s", asset_id, reason)
    return reason


def _save(s3: Any, asset_id: str, verdict: Verdict) -> None:
    s3.put(verdict_s3_key(asset_id), verdict_to_json(verdict).encode("utf-8"),
           asset_id=asset_id, content_type="application/json")


def _check_id(asset_id: Any) -> Optional[VerifyError]:
    if not is_valid_asset_id(asset_id):
        return VerifyError(None, "id_activo invalido")
    return None


def _read_sample(path_or_bytes: Union[str, Path, bytes]) -> Union[bytes, str]:
    if isinstance(path_or_bytes, (bytes, bytearray)):
        return bytes(path_or_bytes)
    try:
        return Path(path_or_bytes).read_bytes()
    except OSError as exc:
        return "no se puede leer la imagen (%s)" % type(exc).__name__


def _verify_bytes(data: bytes, asset_id: str, client: Any, refs: Tuple[bytes, bytes],
                  model_id: str, stats: Optional[UsageStats] = None) -> Union[Verdict, VerifyError]:
    req = build_request(data, refs[0], refs[1], model_id)
    if stats is not None:
        stats.frames += 1
    res = _call_model(client, req, asset_id, stats)
    if isinstance(res, str):
        return VerifyError(asset_id, res)
    return Verdict.from_dict(res)


# --------------------------------------------------------------------------
# Imagen
# --------------------------------------------------------------------------
def verify_image(path_or_bytes: Union[str, Path, bytes], asset_id: str, *,
                 client: Any = None, s3: Any = None,
                 ref_dir: Union[str, Path] = DEFAULT_REF_DIR,
                 model_id: Optional[str] = None,
                 stats: Optional[UsageStats] = None) -> Union[Verdict, VerifyError]:
    bad = _check_id(asset_id)
    if bad:
        return bad
    data = _read_sample(path_or_bytes)
    if isinstance(data, str):
        return VerifyError(asset_id, data)
    # Rechazo previo: nunca se invoca a Bedrock.
    fmt = _detect_format(data)
    if not core.is_supported_image(fmt, len(data)):
        return VerifyError(asset_id, "imagen no soportada (formato=%s, %d bytes)" % (fmt, len(data)))
    try:
        refs = _load_refs(ref_dir)
    except OSError as exc:
        return VerifyError(asset_id, "referencias no disponibles (%s)" % type(exc).__name__)
    if client is None:
        client = _default_client()
    result = _verify_bytes(data, asset_id, client, refs, model_id or _model_id(), stats)
    if isinstance(result, Verdict) and s3 is not None:
        _save(s3, asset_id, result)
    return result


# --------------------------------------------------------------------------
# Video
# --------------------------------------------------------------------------
def extract_frames_cv2(path: Any) -> List[Tuple[int, bytes]]:
    """Fotogramas a 1 fps como (segundo, JPEG). Lanza ValueError si es ilegible."""
    import cv2  # import perezoso

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError("no se puede abrir el video")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if fps <= 0 or count <= 0:
            raise ValueError("video sin duracion legible")
        frames: List[Tuple[int, bytes]] = []
        for t in core.sample_timestamps(count / fps):
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok:
                continue
            ok, buf = cv2.imencode(".jpg", frame)
            if ok:
                frames.append((t, buf.tobytes()))
        if not frames:
            raise ValueError("no se pudo extraer ningun fotograma")
        return frames
    finally:
        cap.release()


def verify_video(path: Union[str, Path], asset_id: str, *,
                 client: Any = None, s3: Any = None,
                 extractor: Optional[FrameExtractor] = None,
                 ref_dir: Union[str, Path] = DEFAULT_REF_DIR,
                 model_id: Optional[str] = None,
                 pegasus: Optional[Callable[[Any, str], Any]] = None,
                 extras: Optional[Dict[str, Any]] = None,
                 stats: Optional[UsageStats] = None) -> Union[Verdict, VerifyError]:
    """``pegasus`` (opcional) guarda su resultado en ``extras['complementario']``
    y nunca altera el veredicto; sus fallos se ignoran."""
    bad = _check_id(asset_id)
    if bad:
        return bad
    try:
        frames = (extractor or extract_frames_cv2)(path)
    except Exception as exc:  # noqa: BLE001
        return VerifyError(asset_id, "video ilegible (%s)" % type(exc).__name__)
    if not frames:
        return VerifyError(asset_id, "video sin fotogramas")
    try:
        refs = _load_refs(ref_dir)
    except OSError as exc:
        return VerifyError(asset_id, "referencias no disponibles (%s)" % type(exc).__name__)
    if client is None:
        client = _default_client()
    mid = model_id or _model_id()

    fvs: List[FrameVerdict] = []
    recs: Dict[str, Tuple[float, str]] = {}
    for ts, data in frames:
        res = _verify_bytes(data, asset_id, client, refs, mid, stats)
        if isinstance(res, VerifyError):
            return VerifyError(asset_id, "fotograma %s: %s" % (ts, res.motivo))
        evs = [Evidence(ts, e.bbox, e.logo_detectado) for e in res.evidencias]
        fvs.append(FrameVerdict(ts, res.veredicto, res.confianza, evs))
        best = recs.get(res.veredicto)
        if best is None or res.confianza > best[0]:
            recs[res.veredicto] = (res.confianza, res.recomendacion)

    value = core.aggregate_frames(fvs)
    conf = max(f.confianza for f in fvs if f.veredicto == value)
    evidencias = [] if value == "SIN_LOGO" else core.select_video_evidence(fvs)
    raw = {"veredicto": value, "confianza": conf,
           "evidencias": [e.to_dict() for e in evidencias],
           "recomendacion": recs[value][1]}
    norm = core.normalize_model_output(raw)
    # El valor de video lo fija aggregate_frames; la normalizacion solo ajusta la recomendacion.
    norm["veredicto"] = value
    errors = validate_verdict(norm)
    if errors:
        return VerifyError(asset_id, "veredicto de video invalido: " + "; ".join(errors))
    verdict = Verdict.from_dict(norm)

    if pegasus is not None:
        try:
            comp = pegasus(path, asset_id)
            if extras is not None:
                extras["complementario"] = comp
        except Exception as exc:  # noqa: BLE001
            log.warning("Pegasus fallo (activo=%s): %s", asset_id, type(exc).__name__)
    if s3 is not None:
        _save(s3, asset_id, verdict)
    return verdict
