"""Subcomando ``register``: valida un archivo subido, lo sube a S3 y lo anota en el manifiesto.

El tipo se decide por el CONTENIDO (firma de bytes), nunca por el nombre. Imagenes: PNG/JPEG/WebP
<= 5 MB. Video: MP4/MOV/WebM <= 200 MB y <= 60 s legible con cv2; si no es H.264 se transcodifica
a H.264 (mp4) con imageio-ffmpeg cuando esta disponible.
"""
from __future__ import annotations

import json
import os
import re
import secrets as _secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from brand_verifier import core, manifest as manifest_mod
from brand_verifier.models import VALORES_VEREDICTO, is_valid_asset_id
from brand_verifier.s3io import S3OperationFailed

EXIT_INVALID = 1   # archivo o argumentos no validos (mensaje apto para el usuario)
EXIT_INTERNAL = 3  # fallo de S3, ffmpeg, manifiesto...
MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_VIDEO_SECONDS = core.MAX_VIDEO_SECONDS
GENERATED_PREFIX = "brand/generated/"
FLUJO = "upload"
_IMG_EXT = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}
CONTENT_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
}


class RegisterError(Exception):
    """Archivo no valido (mensaje apto para el usuario, sin rutas internas)."""


def make_id(tipo: str) -> str:
    return "up-%s-%s" % (tipo, _secrets.token_hex(4))


def sniff(head: bytes) -> Optional[Tuple[str, str]]:
    """(tipo, extension) segun la firma de bytes, o None."""
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "imagen", ".png"
    if head[:3] == b"\xff\xd8\xff":
        return "imagen", ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "imagen", ".webp"
    if head[4:8] == b"ftyp":
        return "video", (".mov" if head[8:12] == b"qt  " else ".mp4")
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "video", ".webm"
    return None


def _ffmpeg() -> Optional[str]:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - opcional
        return None


def video_codec(ff: str, path: str) -> Optional[str]:
    out = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    m = re.search(r"Video: (\w+)", out)
    return m.group(1) if m else None


def transcode_h264(ff: str, src: str, dst: str) -> None:
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", src, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-preset", "fast", "-crf", "20", "-movflags", "+faststart", "-c:a", "aac", dst],
                   check=True)


def video_duration(path: str) -> float:
    import cv2  # import perezoso

    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise RegisterError("el video no se puede abrir")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if fps <= 0 or count <= 0:
            raise RegisterError("el video no tiene una duracion legible")
        return count / fps
    finally:
        cap.release()


def validate_file(path: str) -> Tuple[str, str]:
    """Devuelve (tipo, ext) o lanza RegisterError."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            head = fh.read(16)
    except OSError:
        raise RegisterError("archivo ilegible")
    kind = sniff(head)
    if kind is None:
        raise RegisterError("tipo de archivo no permitido (PNG, JPEG, WebP, MP4, MOV o WebM)")
    tipo, ext = kind
    if tipo == "imagen":
        from brand_verifier import verifier

        data = Path(path).read_bytes() if size <= core.MAX_IMAGE_BYTES else b""
        fmt = verifier._detect_format(data) if data else None
        if size > core.MAX_IMAGE_BYTES:
            raise RegisterError("la imagen supera 5 MB")
        if not core.is_supported_image(fmt, size):
            raise RegisterError("imagen no legible o formato no permitido")
        return tipo, _IMG_EXT[fmt.upper()]
    if size > MAX_VIDEO_BYTES:
        raise RegisterError("el video supera 200 MB")
    if video_duration(path) > MAX_VIDEO_SECONDS:
        raise RegisterError("el video supera 60 s")
    return tipo, ext


def cmd_register(args: Any) -> int:
    from brand_verifier import cli  # evita importacion circular

    label = args.label
    if label not in VALORES_VEREDICTO:
        print("register: etiqueta invalida", file=sys.stderr)
        return 1
    asset_id = args.id or None
    if asset_id is not None and not is_valid_asset_id(asset_id):
        print("register: id invalido (A-Z a-z 0-9 _ -, max. 64)", file=sys.stderr)
        return 1
    try:
        tipo, ext = validate_file(args.file)
    except RegisterError as exc:
        print("register: %s" % exc, file=sys.stderr)
        return 1
    asset_id = asset_id or make_id(tipo)

    tmp = tempfile.mkdtemp(prefix="brand-register-")
    try:
        upload_path = args.file
        if tipo == "video":
            ff = _ffmpeg()
            if ff is not None and video_codec(ff, args.file) != "h264":
                print("register: transcodificando a H.264...", flush=True)
                dst = os.path.join(tmp, "out.mp4")
                try:
                    transcode_h264(ff, args.file, dst)
                except (subprocess.CalledProcessError, OSError):
                    print("register: no se pudo transcodificar el video", file=sys.stderr)
                    return EXIT_INTERNAL
                upload_path, ext = dst, ".mp4"
        key = "%s%s/output%s" % (GENERATED_PREFIX, asset_id, ext)
        try:
            s3 = cli._make_s3(args.no_s3, args.out_dir)
        except Exception as exc:  # noqa: BLE001
            print("register: no se pudo crear el cliente S3 (%s)" % type(exc).__name__, file=sys.stderr)
            return EXIT_INTERNAL
        manifest_path = args.manifest or os.path.join(args.out_dir, "generated", "manifest.json")
        try:
            try:
                manifest = manifest_mod.load(manifest_path, s3)
            except (OSError, ValueError, S3OperationFailed):
                manifest = manifest_mod.new_manifest()
            s3.put(key, upload_path, asset_id=asset_id, content_type=CONTENT_TYPES[ext])
            manifest_mod.register_asset(manifest, asset_id, tipo, FLUJO, {}, label, s3_key=key)
            if not manifest_mod.save(manifest, manifest_path, s3):
                print("register: manifiesto guardado en local, subida pendiente", file=sys.stderr)
                return EXIT_INTERNAL
        except S3OperationFailed as exc:
            print("register: %s" % exc, file=sys.stderr)
            return EXIT_INTERNAL
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps({"id": asset_id, "tipo": tipo, "s3_key": key}), flush=True)
    return 0
