"""Comprobador de Activos_Referencia de marca.

- ``check_local_refs(dir)``: existencia, tamano <= 1 MB y WebP legible (Pillow).
- ``sync_refs_to_s3(s3, bucket)``: sube a ``brand/reference/`` solo los ausentes.

Logo_Correcto (Ayesa Digital) es la unica marca valida; Logo_Incorrecto
(Ayesa sin "digital") es solo el contraejemplo de referencia.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

LOGO_CORRECTO = "logo-ayesa-boletin.webp"    # unica marca valida
LOGO_INCORRECTO = "logo-vector_ayesa.webp"   # marca incorrecta
REFERENCE_FILES = (LOGO_CORRECTO, LOGO_INCORRECTO)
VALID_BRAND_FILE = LOGO_CORRECTO
MAX_BYTES = 1024 * 1024  # 1 MB
DEFAULT_DIR = "assets/brand"
S3_PREFIX = "brand/reference/"

log = logging.getLogger(__name__)


class ReferenceCheckError(Exception):
    """Un Activo_Referencia falta o no es valido. Incluye ruta y motivo."""

    def __init__(self, problems: List[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def _check_one(path: Path) -> Optional[str]:
    """Devuelve el motivo del fallo o None si el archivo es valido."""
    if not path.is_file():
        return ("%s: falta el archivo; colocalo en assets/brand/ (%s)"
                % (path, path.name))
    try:
        size = path.stat().st_size
    except OSError as exc:
        return "%s: no se puede leer (%s)" % (path, type(exc).__name__)
    if size > MAX_BYTES:
        return "%s: tamano %d bytes supera el maximo de 1 MB" % (path, size)
    try:
        from PIL import Image
        with Image.open(path) as img:
            if img.format != "WEBP":
                return "%s: no es una imagen WebP (formato %s)" % (path, img.format)
            img.load()  # fuerza la decodificacion completa
    except Exception as exc:  # noqa: BLE001 - cualquier fallo de Pillow = ilegible
        return "%s: no es una imagen WebP legible (%s)" % (path, type(exc).__name__)
    return None


def check_local_refs(directory: Union[str, Path] = DEFAULT_DIR) -> Dict[str, Path]:
    """Valida ambos Activos_Referencia locales.

    Devuelve ``{nombre_archivo: Path}``. Lanza ``ReferenceCheckError`` con todos
    los problemas (ruta y motivo) si alguno falla.
    """
    base = Path(directory)
    problems: List[str] = []
    found: Dict[str, Path] = {}
    for name in REFERENCE_FILES:
        path = base / name
        reason = _check_one(path)
        if reason:
            problems.append(reason)
        else:
            found[name] = path
    if problems:
        raise ReferenceCheckError(problems)
    return found


def sync_refs_to_s3(s3, bucket: Optional[str] = None,
                    directory: Union[str, Path] = DEFAULT_DIR) -> List[str]:
    """Sube a ``brand/reference/`` solo los Activos_Referencia ausentes.

    ``s3`` es un ``S3IO``; ``bucket`` es informativo (S3IO ya conoce su bucket)
    y, si se indica y difiere, se rechaza para no subir al bucket equivocado.
    Valida los archivos locales antes de subir. Devuelve las claves subidas.
    """
    if bucket is not None and getattr(s3, "bucket", bucket) != bucket:
        raise ValueError("El bucket indicado no coincide con el del adaptador S3")
    files = check_local_refs(directory)
    uploaded: List[str] = []
    for name in REFERENCE_FILES:
        key = S3_PREFIX + name
        if s3.exists(key, asset_id=name):
            continue
        s3.put(key, files[name].read_bytes(), asset_id=name, content_type="image/webp")
        log.info("Referencia subida: %s", key)
        uploaded.append(key)
    return uploaded
