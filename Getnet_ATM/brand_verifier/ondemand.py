"""Subcomando ``generate``: crea UN activo nuevo en ComfyUI y, con ``--verify``, lo verifica.

    python3 -m brand_verifier generate --logo {CORRECTO,INCORRECTO,SIN_LOGO} --tipo {imagen,video}
        [--escena PRESET] [--prompt TEXTO] [--verify] [--no-s3]

- Genera con ``generator.generate_dataset([spec], manifiesto_de_S3, s3, ...)``: sube a
  ``brand/generated/<id>/``, registra en el manifiesto (merge, ``etiqueta_validada=false``) y
  escribe las metricas de ComfyUI.
- ``--verify`` reutiliza ``cli.cmd_run`` (equivale a ``run --skip-generation --only <id>``,
  informe con merge).
- Al final imprime ``RESULT {"id", "tipo", "s3_key", "estado"}``.
- Salida: 0 ok, 1 entrada invalida, 2 generacion fallida, 3 verificacion fallida.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets as _secrets
import shutil
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from brand_verifier import generator, incident, manifest as manifest_mod
from brand_verifier.models import Verdict, verdict_s3_key

EXIT_OK, EXIT_INVALID, EXIT_GENERATION, EXIT_VERIFY = 0, 1, 2, 3
LOGOS = ("CORRECTO", "INCORRECTO", "SIN_LOGO")
TIPOS = ("imagen", "video")
PROMPT_MAX = 300
DEFAULT_SCENE = "taza"
_CONTROL_CATEGORIES = ("Cc", "Cf", "Zl", "Zp")

_ATM_DESC = {
    "descripcion": (
        "Cajero generico empotrado en la fachada de un edificio, sin tarjetas a la vista; la "
        "pantalla muestra solo el logotipo de la marca."
    )
}
_ATM_NO_LOGO = (
    "Cajero automatico de calle por la noche, plano medio realista, pantalla encendida en blanco, "
    "sin personas identificables, sin tarjetas, sin texto legible y sin numeros"
)

# id -> (escena sin logo, donde va el logo). Sin personas, tarjetas ni marcas o bancos reales.
SCENES: Dict[str, Tuple[str, str]] = {
    "atm": (incident.scene_prompt(_ATM_DESC), "shown on the ATM screen"),
    "oficina": ("A modern corporate reception area with a clean front desk and a large feature "
                "wall, bright interior, no people", "mounted on the wall as large clean signage"),
    "valla": ("A large roadside advertising billboard on a sunny urban street, realistic photo, "
              "no people", "printed large on the billboard"),
    "taza": ("Professional product photo of a white ceramic coffee mug on a wooden desk, soft "
             "daylight", "clearly printed on the mug"),
    "camiseta": ("A plain white cotton t-shirt laid flat on a light wooden table, studio "
                 "lighting, no people", "printed large on the chest"),
    "movil": ("A modern smartphone lying on an office desk with the screen on, realistic product "
              "photo, no people, no hands", "displayed full screen on the phone"),
}


class InvalidInput(ValueError):
    """Argumentos no validos (mensaje apto para el usuario)."""


def _say(msg: str) -> None:
    print(msg, flush=True)


def validate_prompt(text: Any) -> str:
    """Prompt personalizado limpio o InvalidInput: sin caracteres de control y max. 300."""
    if not isinstance(text, str):
        raise InvalidInput("prompt: debe ser texto")
    if any(unicodedata.category(c) in _CONTROL_CATEGORIES for c in text):
        raise InvalidInput("prompt: no admite caracteres de control")
    clean = text.strip()
    if not clean:
        raise InvalidInput("prompt: no puede estar vacio")
    if len(clean) > PROMPT_MAX:
        raise InvalidInput("prompt: maximo %d caracteres" % PROMPT_MAX)
    return clean


def check_args(logo: Any, tipo: Any, escena: Any = None, prompt: Any = None
               ) -> Tuple[str, str, Optional[str], Optional[str]]:
    if logo not in LOGOS:
        raise InvalidInput("logo: debe ser uno de %s" % ", ".join(LOGOS))
    if tipo not in TIPOS:
        raise InvalidInput("tipo: debe ser uno de %s" % ", ".join(TIPOS))
    if escena is not None and escena not in SCENES:
        raise InvalidInput("escena: debe ser una de %s" % ", ".join(SCENES))
    clean = validate_prompt(prompt) if prompt is not None else None
    return logo, tipo, (None if clean is not None else (escena or DEFAULT_SCENE)), clean


def build_prompt(logo: str, tipo: str, escena: Optional[str] = None,
                 prompt: Optional[str] = None) -> str:
    """Escena (preset o personalizada) + instruccion de logo / sin logo (+ movimiento en video)."""
    if prompt is not None:
        scene, where = prompt, "clearly visible"
    else:
        key = escena or DEFAULT_SCENE
        scene, where = SCENES[key]
        if logo == "SIN_LOGO" and key == "atm":
            scene = _ATM_NO_LOGO
    scene = scene.strip().rstrip(" .")
    if logo == "SIN_LOGO":
        text = "%s, %s." % (scene, generator.NO_LOGO_INSTRUCTION)
    else:
        text = "%s, %s." % (scene, generator.logo_instruction(where))
    if tipo == "video":
        text += generator.MOTION
    return text


def make_id(tipo: str) -> str:
    return "gen-%s-%s" % (tipo, _secrets.token_hex(4))


def load_manifest(path: str, s3: Any) -> Dict[str, Any]:
    """Manifiesto de S3 (fuente comun del equipo); si no se puede, la copia local; si no, uno nuevo."""
    try:
        data = json.loads(s3.get(manifest_mod.MANIFEST_KEY).decode("utf-8"))
        if isinstance(data, dict) and isinstance(data.get("assets"), list):
            return data
    except Exception:  # noqa: BLE001 - sin manifiesto remoto: se usa el local
        pass
    try:
        return manifest_mod.load(path, None)
    except (OSError, ValueError):
        return manifest_mod.new_manifest()


def _generate(spec: generator.AssetSpec, args: Any, manifest_path: str,
              result: Dict[str, Any]) -> int:
    from brand_verifier import cli  # evita importacion circular

    out_dir = args.out_dir
    _say("[fase] generacion: en curso (%s, %s, %s)" % (spec.id, spec.tipo, spec.etiqueta_esperada))
    t0 = time.monotonic()
    try:
        s3 = cli._make_s3(args.no_s3, out_dir)
    except Exception as exc:  # noqa: BLE001 - boto3 ausente / sin credenciales
        _say("[fase] generacion: fallida (cliente S3: %s)" % type(exc).__name__)
        return EXIT_GENERATION
    manifest = load_manifest(manifest_path, s3)
    workdir = Path(out_dir) / "generated" / (".work-%s" % spec.id)
    try:
        workdir.mkdir(parents=True, exist_ok=True)
        manifest = generator.generate_dataset(
            [spec], manifest, s3, manifest_path=manifest_path, workdir=workdir, status=_say,
            metrics_dir=out_dir)
    except Exception as exc:  # noqa: BLE001 - secretos/AgentUrl ausentes, E/S...
        _say("[fase] generacion: fallida (%s)" % generator._reason(exc))
        return EXIT_GENERATION
    finally:
        shutil.rmtree(str(workdir), ignore_errors=True)
    rec = manifest_mod.find_asset(manifest, spec.id) or {}
    result["estado"] = rec.get("estado") or "GENERACION_FALLIDA"
    result["s3_key"] = rec.get("s3_key")
    secs = time.monotonic() - t0
    if result["estado"] != "GENERADO":
        _say("[fase] generacion: fallida (%s)" % (rec.get("motivo") or "sin motivo"))
        return EXIT_GENERATION
    _say("[fase] generacion: completada (%.1f s) -> %s" % (secs, result["s3_key"]))
    return EXIT_OK


def _verify(asset_id: str, args: Any, manifest_path: str) -> int:
    from brand_verifier import cli  # evita importacion circular

    _say("[fase] verificacion: en curso (%s)" % asset_id)
    t0 = time.monotonic()
    ns = argparse.Namespace(manifest=manifest_path, skip_generation=True, limit=None, only=asset_id,
                            refs_dir=args.refs_dir, out_dir=args.out_dir, no_s3=args.no_s3,
                            pegasus=False)
    try:
        rc = cli.cmd_run(ns)
    except Exception as exc:  # noqa: BLE001
        _say("[fase] verificacion: fallida (%s)" % type(exc).__name__)
        return EXIT_VERIFY
    secs = time.monotonic() - t0
    verdict: Optional[Verdict] = None
    try:
        path = cli._local_path(args.out_dir, verdict_s3_key(asset_id))
        verdict = Verdict.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 - sin veredicto: la verificacion fallo
        verdict = None
    if rc != 0 or verdict is None:
        _say("[fase] verificacion: fallida (%.1f s)" % secs)
        return EXIT_VERIFY
    _say("[fase] verificacion: completada (%.1f s) -> %s, confianza %.2f"
         % (secs, verdict.veredicto, verdict.confianza))
    return EXIT_OK


def cmd_generate(args: Any) -> int:
    try:
        logo, tipo, escena, prompt = check_args(
            getattr(args, "logo", None), getattr(args, "tipo", None),
            getattr(args, "escena", None), getattr(args, "prompt", None))
    except InvalidInput as exc:
        print("generate: %s" % exc, file=sys.stderr)
        return EXIT_INVALID
    asset_id = make_id(tipo)
    spec = generator.AssetSpec(asset_id, tipo, logo, build_prompt(logo, tipo, escena, prompt))
    manifest_path = args.manifest or os.path.join(args.out_dir, "generated", "manifest.json")
    result: Dict[str, Any] = {"id": asset_id, "tipo": tipo, "s3_key": None,
                              "estado": "GENERACION_FALLIDA"}
    code = EXIT_GENERATION
    try:
        code = _generate(spec, args, manifest_path, result)
        if code == EXIT_OK and getattr(args, "verify", False):
            code = _verify(asset_id, args, manifest_path)
    finally:
        _say("RESULT " + json.dumps(result, ensure_ascii=False))
    return code
