"""Cortina sonora por video con Stable Audio (Stability AI).

Stability no ofrece TTS: se genera una cortina/musica corta cuyo prompt depende
del veredicto, se guarda como ``brand/generated/<id>/audio.mp3`` y se mezcla con
el video original en ``brand/generated/<id>/output_audio.mp4``.

- Endpoint: POST https://api.stability.ai/v2beta/audio/stable-audio-2/text-to-audio
  (multipart/form-data; ``Authorization: Bearer``; ``Accept: audio/*``).
- Cliente HTTP y S3 inyectables; un solo trabajo a la vez; timeouts.
- La clave se lee en memoria con ``secrets.get_optional`` y nunca se registra ni
  aparece en excepciones (se redacta cualquier mensaje).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from brand_verifier import metrics as metrics_mod
from brand_verifier import secrets as secrets_mod
from brand_verifier.models import verdict_s3_key

ENDPOINT = "https://api.stability.ai/v2beta/audio/stable-audio-2/text-to-audio"
MODEL = "stable-audio-2.5"
OUTPUT_FORMAT = "mp3"
STEPS = 8
SECRET_NAME = "StabilityAIApiKey"
HTTP_TIMEOUT_S = 120.0
FFMPEG_TIMEOUT_S = 120.0
MIN_DURATION_S = 1
MAX_DURATION_S = 8
FALLBACK_DURATION_S = 6
INDEX_KEY = "brand/audio/index.json"
MAX_ERR_CHARS = 200

PROMPTS = {
    "CORRECTO": ("Short positive corporate jingle, uplifting modern electronic and soft "
                 "piano, warm and confident, clean mix, instrumental, no vocals"),
    "INCORRECTO": ("Sober alert tone, low synth pulse with two restrained warning beeps, "
                   "serious and calm, minimal, instrumental, no vocals"),
}
NEUTRAL_PROMPT = ("Neutral ambient background, soft sustained pads, subtle and unobtrusive, "
                  "instrumental, no vocals")

log = logging.getLogger(__name__)
_job_lock = threading.Lock()

# post(url, headers, fields, timeout_s) -> (status, body_bytes)
HttpPost = Callable[[str, Dict[str, str], Dict[str, str], float], Tuple[int, bytes]]


class NarrationError(Exception):
    """Fallo de narracion. El mensaje nunca contiene la clave."""


def prompt_for(verdict: Optional[str]) -> str:
    return PROMPTS.get(verdict or "", NEUTRAL_PROMPT)


def audio_key(asset_id: str) -> str:
    return "brand/generated/%s/audio.mp3" % asset_id


def video_audio_key(asset_id: str) -> str:
    return "brand/generated/%s/output_audio.mp4" % asset_id


# --------------------------------------------------------------------------
# HTTP por defecto (urllib, multipart)
# --------------------------------------------------------------------------
def _multipart(fields: Dict[str, str]) -> Tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: List[bytes] = []
    for name, value in fields.items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (boundary, name, value)).encode("utf-8"))
    parts.append(("--%s--\r\n" % boundary).encode("ascii"))
    return b"".join(parts), "multipart/form-data; boundary=%s" % boundary


def default_post(url: str, headers: Dict[str, str], fields: Dict[str, str],
                 timeout_s: float) -> Tuple[int, bytes]:
    body, ctype = _multipart(fields)
    hdrs = dict(headers)
    hdrs["Content-Type"] = ctype
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 - URL fija https
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


# --------------------------------------------------------------------------
# Stable Audio
# --------------------------------------------------------------------------
def _safe(text: str, key: Optional[str]) -> str:
    text = secrets_mod.redact(text)
    if key:
        text = text.replace(key, secrets_mod.REDACTED)
    return text[:MAX_ERR_CHARS]


def generate_audio(prompt: str, duration_s: int, api_key: str,
                   post: Optional[HttpPost] = None,
                   timeout_s: float = HTTP_TIMEOUT_S) -> bytes:
    """Devuelve los bytes mp3 generados. Lanza ``NarrationError`` sin revelar la clave."""
    post = post or default_post
    headers = {"Authorization": "Bearer %s" % api_key, "Accept": "audio/*"}
    fields = {
        "prompt": prompt,
        "duration": str(int(duration_s)),
        "model": MODEL,
        "output_format": OUTPUT_FORMAT,
        "steps": str(STEPS),
    }
    try:
        status, body = post(ENDPOINT, headers, fields, timeout_s)
    except Exception as exc:  # noqa: BLE001 - red, timeout, TLS...
        raise NarrationError("Stable Audio: fallo de red (%s)" % type(exc).__name__) from None
    if status != 200:
        detail = _safe(body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else "", api_key)
        raise NarrationError("Stable Audio: HTTP %s %s" % (status, detail))
    if not body:
        raise NarrationError("Stable Audio: respuesta vacia")
    return bytes(body)


# --------------------------------------------------------------------------
# ffmpeg (imageio-ffmpeg)
# --------------------------------------------------------------------------
def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
    except ImportError:
        raise NarrationError("imageio-ffmpeg no esta instalado") from None
    return imageio_ffmpeg.get_ffmpeg_exe()


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def probe_duration(video: Path, exe: Optional[str] = None) -> Optional[float]:
    """Duracion en segundos leyendo la salida de ``ffmpeg -i``; None si no se puede."""
    try:
        proc = subprocess.run([exe or ffmpeg_exe(), "-hide_banner", "-i", str(video)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError, NarrationError):
        return None
    m = _DUR_RE.search(proc.stderr.decode("utf-8", "replace"))
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def target_duration(video_seconds: Optional[float]) -> int:
    if not video_seconds or video_seconds <= 0:
        return FALLBACK_DURATION_S
    return max(MIN_DURATION_S, min(MAX_DURATION_S, int(round(video_seconds))))


def mux(video: Path, audio: Path, out: Path, exe: Optional[str] = None) -> None:
    cmd = [exe or ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy", "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(out)]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NarrationError("ffmpeg: %s" % type(exc).__name__) from None
    if proc.returncode != 0 or not out.is_file():
        raise NarrationError("ffmpeg: fallo al mezclar (codigo %s)" % proc.returncode)


# --------------------------------------------------------------------------
# Orquestacion
# --------------------------------------------------------------------------
def _read_json(s3: Any, key: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(s3.get(key).decode("utf-8"))
    except Exception:  # noqa: BLE001 - ausente o ilegible
        return None
    return data if isinstance(data, dict) else None


def narrate_all(manifest: Dict[str, Any], s3: Any, api_key: str,
                only: Optional[Sequence[str]] = None,
                post: Optional[HttpPost] = None,
                status: Callable[[str], None] = lambda m: None,
                ffmpeg: Optional[str] = None,
                metrics_dir: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Genera cortina + video con audio por cada video con veredicto. Devuelve el indice."""
    secrets_mod.register_secret(api_key)
    index: Dict[str, Dict[str, Any]] = _read_json(s3, INDEX_KEY) or {}
    videos = [a for a in manifest.get("assets", [])
              if a.get("tipo") == "video" and a.get("s3_key")
              and a.get("estado", "GENERADO") == "GENERADO"]
    if only:
        wanted = set(only)
        videos = [a for a in videos if a.get("id") in wanted]
    with _job_lock, tempfile.TemporaryDirectory(prefix="narrate-") as tmp:
        for a in videos:  # secuencial: un trabajo a la vez
            aid = a["id"]
            verdict = _read_json(s3, verdict_s3_key(aid))
            if not verdict:
                status("narrate: %s sin veredicto, se omite" % aid)
                continue
            label = verdict.get("veredicto")
            prompt = prompt_for(label)
            try:
                work = Path(tmp) / aid
                work.mkdir(parents=True, exist_ok=True)
                video = work / "video.mp4"
                video.write_bytes(s3.get(a["s3_key"], asset_id=aid))
                exe = ffmpeg or ffmpeg_exe()
                duration = target_duration(probe_duration(video, exe))
                status("narrate: %s (%s, %ss)" % (aid, label, duration))
                mp3 = generate_audio(prompt, duration, api_key, post)
                metrics_mod.record_model(s3, metrics_dir, MODEL, metrics_mod.SVC_AUDIO, calls=1)
                audio_path = work / "audio.mp3"
                audio_path.write_bytes(mp3)
                out = work / "output_audio.mp4"
                mux(video, audio_path, out, exe)
                s3.put(audio_key(aid), mp3, asset_id=aid, content_type="audio/mpeg")
                s3.put(video_audio_key(aid), out.read_bytes(), asset_id=aid, content_type="video/mp4")
            except NarrationError as exc:
                msg = _safe(str(exc), api_key)
                log.error("narrate %s fallo: %s", aid, msg)
                status("narrate: %s fallo: %s" % (aid, msg))
                continue
            index[aid] = {"audio_key": audio_key(aid), "video_audio_key": video_audio_key(aid),
                          "prompt": prompt, "veredicto": label}
        s3.put(INDEX_KEY, (json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
               content_type="application/json")
    return index
