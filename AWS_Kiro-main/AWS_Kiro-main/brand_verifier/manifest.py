"""Manifiesto de activos generados (Requirement 6.6, 6.7, 7.2, 7.7).

El Manifiesto es un dict ``{"assets": [...]}``. Cada activo lleva: id, tipo,
flujo, ajustes, etiqueta_esperada, etiqueta_validada, estado, motivo, s3_key.

- ``save`` escribe en local de forma atomica (temporal + rename) y despues sube
  a ``brand/generated/manifest.json``. Si la subida falla, la copia local ya
  escrita se conserva y la copia remota anterior queda intacta.
- Los ``ajustes`` nunca contienen claves que parezcan secretos.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional

from brand_verifier.models import VALORES_VEREDICTO, is_valid_asset_id
from brand_verifier.s3io import S3IO, S3OperationFailed

MANIFEST_KEY = "brand/generated/manifest.json"
DEFAULT_LOCAL_PATH = os.path.join("brand", "generated", "manifest.json")
TIPOS = ("imagen", "video")
ESTADOS = ("GENERADO", "GENERACION_FALLIDA")
SECRET_KEY_HINTS = ("token", "password", "key", "secret", "authorization")

log = logging.getLogger(__name__)

Manifest = Dict[str, Any]


# --------------------------------------------------------------------------
# Utilidades puras
# --------------------------------------------------------------------------
def _looks_secret(name: Any) -> bool:
    low = str(name).lower()
    return any(h in low for h in SECRET_KEY_HINTS)


def filter_settings(ajustes: Any) -> Any:
    """Copia ``ajustes`` sin claves que parezcan secretos (recursivo)."""
    if isinstance(ajustes, dict):
        return {k: filter_settings(v) for k, v in ajustes.items() if not _looks_secret(k)}
    if isinstance(ajustes, (list, tuple)):
        return [filter_settings(v) for v in ajustes]
    return ajustes


def _check_label(label: Any) -> str:
    if not isinstance(label, str) or label not in VALORES_VEREDICTO:
        raise ValueError("etiqueta: debe ser una de %s" % ", ".join(VALORES_VEREDICTO))
    return label


def new_manifest() -> Manifest:
    return {"assets": []}


def find_asset(manifest: Manifest, asset_id: str) -> Optional[Dict[str, Any]]:
    for a in manifest.get("assets", []):
        if a.get("id") == asset_id:
            return a
    return None


# --------------------------------------------------------------------------
# E/S
# --------------------------------------------------------------------------
def load(path: str = DEFAULT_LOCAL_PATH, s3: Optional[S3IO] = None) -> Manifest:
    """Lee el Manifiesto local; si no existe y hay ``s3``, lo descarga de S3.

    Lanza ``FileNotFoundError`` o ``ValueError`` si no existe o no es legible.
    """
    if os.path.isfile(path):
        with open(path, "rb") as fh:
            raw = fh.read()
    elif s3 is not None:
        raw = s3.get(MANIFEST_KEY)
    else:
        raise FileNotFoundError("Manifiesto no encontrado: %s" % path)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("Manifiesto ilegible (%s)" % type(exc).__name__)
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        raise ValueError("Manifiesto ilegible: falta la lista 'assets'")
    return data


def _atomic_write(path: str, data: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(manifest: Manifest, path: str = DEFAULT_LOCAL_PATH, s3: Optional[S3IO] = None) -> bool:
    """Escribe en local de forma atomica y sube a S3 si hay ``s3``.

    Devuelve True si la subida tuvo exito (o no se pidio); False si fallo. En
    ese caso la copia remota anterior se conserva y la local queda pendiente.
    """
    data = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(path, data)
    if s3 is None:
        return True
    try:
        s3.put(MANIFEST_KEY, data, content_type="application/json")
    except S3OperationFailed:
        log.error("Subida del Manifiesto fallida; se conserva la ultima version exitosa en S3")
        return False
    return True


# --------------------------------------------------------------------------
# Operaciones sobre activos
# --------------------------------------------------------------------------
def register_asset(
    manifest: Manifest,
    asset_id: str,
    tipo: str,
    flujo: str,
    ajustes: Optional[Dict[str, Any]],
    etiqueta_esperada: str,
    s3_key: Optional[str] = None,
    estado: str = "GENERADO",
    motivo: Optional[str] = None,
) -> Dict[str, Any]:
    """Anade (o sustituye) un activo con ``etiqueta_validada=false`` y sin secretos."""
    if not is_valid_asset_id(asset_id):
        raise ValueError("id_activo invalido")
    if tipo not in TIPOS:
        raise ValueError("tipo: debe ser uno de %s" % ", ".join(TIPOS))
    if estado not in ESTADOS:
        raise ValueError("estado: debe ser uno de %s" % ", ".join(ESTADOS))
    _check_label(etiqueta_esperada)
    record = {
        "id": asset_id,
        "tipo": tipo,
        "flujo": flujo,
        "ajustes": filter_settings(dict(ajustes or {})),
        "etiqueta_esperada": etiqueta_esperada,
        "etiqueta_validada": False,
        "estado": estado,
        "motivo": motivo,
        "s3_key": s3_key,
    }
    assets: List[Dict[str, Any]] = manifest.setdefault("assets", [])
    for i, a in enumerate(assets):
        if a.get("id") == asset_id:
            assets[i] = record
            break
    else:
        assets.append(record)
    return record


def validate_asset(
    manifest: Manifest,
    asset_id: str,
    confirmed: bool,
    corrected_label: Optional[str] = None,
) -> Dict[str, Any]:
    """Marca el activo como validado; si hay etiqueta corregida, la guarda.

    ``confirmed`` indica que el revisor reviso el activo; en ambos casos queda
    ``etiqueta_validada=true``. Los demas activos no cambian.
    """
    if corrected_label is not None:
        _check_label(corrected_label)
    asset = find_asset(manifest, asset_id)
    if asset is None:
        raise KeyError(asset_id)
    if corrected_label is not None:
        asset["etiqueta_esperada"] = corrected_label
    asset["etiqueta_validada"] = True
    return asset


# --------------------------------------------------------------------------
# CLI reutilizable: brand_verifier validate <id> [--label X]
# --------------------------------------------------------------------------
def cmd_validate(args: Any) -> int:
    """Ejecuta ``validate``. ``args``: id, label (opcional), manifest (opcional), s3 (opcional)."""
    asset_id = getattr(args, "id", None)
    label = getattr(args, "label", None)
    path = getattr(args, "manifest", None) or DEFAULT_LOCAL_PATH
    s3 = getattr(args, "s3", None)
    try:
        manifest = load(path, s3)
        validate_asset(manifest, asset_id, True, label)
    except KeyError:
        print("validate: activo no encontrado: %s" % asset_id, file=sys.stderr)
        return 1
    except (OSError, ValueError, S3OperationFailed) as exc:
        print("validate: %s" % exc, file=sys.stderr)
        return 1
    if not save(manifest, path, s3):
        print("validate: guardado en local, subida a S3 pendiente", file=sys.stderr)
        return 1
    print("validate: %s validado" % asset_id)
    return 0
