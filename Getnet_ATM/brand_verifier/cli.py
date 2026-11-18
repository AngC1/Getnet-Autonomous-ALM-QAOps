"""CLI y orquestador: ``python3 -m brand_verifier {run,validate,incident}``.

Etapas de ``run``: referencias -> generacion -> verificacion -> informe.
Cada etapa imprime su nombre y estado (en curso / completada / fallida / omitida).
Una etapa fallida omite las dependientes, genera un informe parcial y devuelve
un codigo distinto de cero.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from brand_verifier import generator, incident, manifest as manifest_mod, metrics, references, report, verifier
from brand_verifier.models import VALORES_VEREDICTO, Verdict, VerifyError, verdict_s3_key, verdict_to_json
from brand_verifier.s3io import S3IO, S3OperationFailed

STAGES = ("referencias", "generacion", "verificacion", "informe")
ST_RUNNING = "en curso"
ST_DONE = "completada"
ST_FAILED = "fallida"
ST_SKIPPED = "omitida"
POOL_SIZE = 4
DEFAULT_OUT_DIR = "brand"
KEY_PREFIX = "brand/"
REPORT_NAME = "report"


# --------------------------------------------------------------------------
# S3 local (modo --no-s3)
# --------------------------------------------------------------------------
class LocalS3:
    """Sustituto de ``S3IO`` que guarda en disco bajo ``root`` (la clave pierde el prefijo ``brand/``)."""

    bucket = "local"

    def __init__(self, root: str):
        self.root = Path(root)
        self.pending: List[Any] = []

    def _path(self, key: str) -> Path:
        rel = key[len(KEY_PREFIX):] if key.startswith(KEY_PREFIX) else key
        return self.root / rel

    def put(self, key: str, data: Any, asset_id: Optional[str] = None,
            content_type: Optional[str] = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            shutil.copyfile(data, str(path))
        else:
            path.write_bytes(bytes(data))

    def get(self, key: str, asset_id: Optional[str] = None) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str, asset_id: Optional[str] = None) -> bool:
        return self._path(key).is_file()


def _make_s3(no_s3: bool, out_dir: str) -> Any:
    return LocalS3(out_dir) if no_s3 else S3IO()


def _bedrock_client() -> Any:
    return verifier._default_client()


def _pegasus_hook(path: Any, asset_id: str) -> Any:
    """Analisis complementario (opcional). Aun sin integracion con Pegasus: no aporta datos."""
    return {"disponible": False}


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _say(msg: str) -> None:
    print(msg, flush=True)


def _stage(name: str, state: str, extra: str = "") -> None:
    _say("[etapa] %s: %s%s" % (name, state, (" (%s)" % extra) if extra else ""))


def _local_path(out_dir: str, key: str) -> Path:
    rel = key[len(KEY_PREFIX):] if key.startswith(KEY_PREFIX) else key
    return Path(out_dir) / rel


def _resolve_asset(asset: Dict[str, Any], out_dir: str, s3: Any, tmp_dir: Path) -> Path:
    """Ruta local del activo; lo descarga de S3 a ``tmp_dir`` si no existe localmente."""
    key = asset.get("s3_key")
    if not key:
        raise FileNotFoundError("el activo no tiene s3_key")
    local = _local_path(out_dir, key)
    if local.is_file():
        return local
    if s3 is None:
        raise FileNotFoundError("activo no encontrado en local: %s" % local)
    dest = tmp_dir / str(asset["id"]) / Path(key).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(s3.get(key, asset_id=asset["id"]))
    return dest


def _write_local_verdict(out_dir: str, asset_id: str, verdict: Verdict) -> None:
    path = _local_path(out_dir, verdict_s3_key(asset_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(verdict_to_json(verdict), encoding="utf-8")


def _make_row(asset: Dict[str, Any], result: Any, elapsed: float, sample: Optional[bytes]) -> Dict[str, Any]:
    """Fila del informe (formato de design.md, 'Resultado de verificacion')."""
    row: Dict[str, Any] = {
        "id": asset.get("id"),
        "tipo": asset.get("tipo"),
        "esperada": asset.get("etiqueta_esperada"),
        "detectada": None,
        "confianza": None,
        "evidencia": None,
        "duracion_s": round(elapsed, 3),
        "validada": asset.get("etiqueta_validada") is True,
    }
    if isinstance(result, Verdict):
        row["detectada"] = result.veredicto
        row["confianza"] = result.confianza
        if result.evidencias:
            e = result.evidencias[0]
            ev: Dict[str, Any] = {"frame_s": e.timestamp_s, "bbox": list(e.bbox)}
            if sample is not None and asset.get("tipo") == "imagen":
                ev["image_bytes"] = sample
            row["evidencia"] = ev
    else:
        row["motivo"] = getattr(result, "motivo", str(result))
    row["resultado"] = "aprobado" if report.is_match(row) else "fallido"
    return row


def _verify_one(asset: Dict[str, Any], out_dir: str, s3: Any, tmp_dir: Path, client: Any,
                ref_dir: str, pegasus: bool,
                collector: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    t0 = time.monotonic()
    stats = metrics.UsageStats(str(asset.get("id")), str(asset.get("tipo")), verifier._model_id())
    result: Any
    sample: Optional[bytes] = None
    try:
        path = _resolve_asset(asset, out_dir, s3, tmp_dir)
        if asset.get("tipo") == "imagen":
            sample = path.read_bytes()
            result = verifier.verify_image(sample, asset["id"], client=client, s3=s3, ref_dir=ref_dir,
                                           stats=stats)
        else:
            kwargs: Dict[str, Any] = {"client": client, "s3": s3, "ref_dir": ref_dir, "stats": stats}
            if pegasus:
                kwargs["pegasus"] = _pegasus_hook
            result = verifier.verify_video(path, asset["id"], **kwargs)
    except (OSError, S3OperationFailed, KeyError, ValueError) as exc:
        result = VerifyError(asset.get("id"), "%s: %s" % (type(exc).__name__, exc))
    elapsed = time.monotonic() - t0
    if isinstance(result, Verdict):
        try:
            _write_local_verdict(out_dir, asset["id"], result)
        except OSError as exc:
            print("aviso: no se pudo escribir el veredicto local de %s (%s)" % (asset["id"], type(exc).__name__),
                  file=sys.stderr)
    try:
        data = metrics.write_asset(s3, out_dir, stats,
                                   result.veredicto if isinstance(result, Verdict) else None)
        if collector is not None:
            collector.append(data)
        if data.get("calls"):
            metrics.record_model(s3, out_dir, data["model_id"], metrics.SVC_VISION, calls=data["calls"],
                                 input_tokens=data["input_tokens"], output_tokens=data["output_tokens"])
    except Exception as exc:  # noqa: BLE001 - metricas best-effort
        print("aviso: metricas de %s no escritas (%s)" % (asset.get("id"), type(exc).__name__),
              file=sys.stderr)
    return _make_row(asset, result, elapsed, sample)


def _merge_previous_rows(manifest: Optional[Dict[str, Any]], rows: List[Dict[str, Any]],
                         s3: Any) -> List[Dict[str, Any]]:
    """Con --only/--limit el informe no pierde el resto: completa con los veredictos ya guardados.

    Devuelve las filas en el orden del manifiesto; las nuevas sustituyen a las anteriores.
    """
    fresh = {r["id"]: r for r in rows}
    merged: List[Dict[str, Any]] = []
    for asset in (manifest or {}).get("assets", []):
        if asset.get("estado", "GENERADO") != "GENERADO":
            continue
        aid = asset.get("id")
        if aid in fresh:
            merged.append(fresh[aid])
            continue
        try:
            if not s3.exists(verdict_s3_key(aid), asset_id=aid):  # exists no reintenta en 404
                continue
            verdict = Verdict.from_dict(json.loads(s3.get(verdict_s3_key(aid), asset_id=aid).decode("utf-8")))
        except Exception:  # noqa: BLE001 - sin veredicto previo: no aparece
            continue
        merged.append(_make_row(asset, verdict, 0.0, None))
    return merged


def _emit_report(rows: Sequence[Dict[str, Any]], s3: Any, out_dir: str,
                 failed_stage: Optional[str] = None, reason: Optional[str] = None) -> None:
    """Renderiza el informe y lo guarda: copia local y S3."""
    stats = report.build_stats(rows, failed_stage, reason)
    html_text = report.render_report(rows, stats)
    local = Path(out_dir) / "reports" / (REPORT_NAME + ".html")
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(html_text, encoding="utf-8")
    if s3 is not None:
        report.save_report(s3, html_text, REPORT_NAME)


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
class _Timeline:
    """Tiempos por etapa para run.json."""
    def __init__(self) -> None:
        self.stages: List[Dict[str, Any]] = []
        self._t0: Dict[str, float] = {}
    def begin(self, name: str) -> None:
        self._t0[name] = time.monotonic()
    def end(self, name: str, status: str) -> None:
        secs = time.monotonic() - self._t0.pop(name, time.monotonic())
        self.stages.append({"name": name, "status": status, "seconds": round(secs, 3)})
def cmd_run(args: argparse.Namespace) -> int:
    started = metrics.now_iso()
    run_t0 = time.monotonic()
    tl = _Timeline()
    collected: List[Dict[str, Any]] = []
    rc = _cmd_run(args, tl, collected)
    try:
        s3 = _make_s3(args.no_s3, args.out_dir)
        in_t = sum(m["input_tokens"] for m in collected)
        out_t = sum(m["output_tokens"] for m in collected)
        run = {
            "run_id": uuid.uuid4().hex[:12], "started_at": started, "finished_at": metrics.now_iso(),
            "region": metrics.REGION, "model_id": verifier._model_id(),
            "assets_verified": len(collected), "input_tokens": in_t, "output_tokens": out_t,
            "total_tokens": in_t + out_t, "duration_s": round(time.monotonic() - run_t0, 3),
            "stages": tl.stages,
        }
        metrics.write_run(s3, args.out_dir, run)
    except Exception as exc:  # noqa: BLE001 - las metricas nunca cambian el codigo de salida
        print("aviso: metricas de ejecucion no escritas (%s)" % type(exc).__name__, file=sys.stderr)
    return rc
def _cmd_run(args: argparse.Namespace, tl: "_Timeline", collected: List[Dict[str, Any]]) -> int:
    out_dir = args.out_dir
    manifest_path = args.manifest or os.path.join(out_dir, "generated", "manifest.json")
    try:
        s3 = _make_s3(args.no_s3, out_dir)
    except Exception as exc:  # noqa: BLE001 - boto3 ausente / sin credenciales
        print("run: no se pudo crear el cliente S3 (%s)" % type(exc).__name__, file=sys.stderr)
        return 1

    # Manifiesto ilegible con --skip-generation: abortar antes de cualquier etapa.
    manifest: Optional[Dict[str, Any]] = None
    if args.skip_generation:
        try:
            manifest = manifest_mod.load(manifest_path, s3)
        except (OSError, ValueError, S3OperationFailed) as exc:
            print("run: manifiesto ilegible o ausente: %s" % exc, file=sys.stderr)
            return 1

    def mark(name: str, state: str, extra: str = "") -> None:
        _stage(name, state, extra)
        if state == ST_RUNNING:
            tl.begin(name)
        else:
            tl.end(name, state)
    rows: List[Dict[str, Any]] = []
    failed: Optional[str] = None
    reason: Optional[str] = None

    def fail(stage: str, why: str) -> None:
        nonlocal failed, reason
        failed, reason = stage, why
        mark(stage, ST_FAILED, why)

    # 1. referencias
    mark("referencias", ST_RUNNING)
    try:
        references.check_local_refs(args.refs_dir)
        references.sync_refs_to_s3(s3, directory=args.refs_dir)
        mark("referencias", ST_DONE)
    except references.ReferenceCheckError as exc:
        fail("referencias", "; ".join(exc.problems) if getattr(exc, "problems", None) else str(exc))
    except (OSError, ValueError, S3OperationFailed) as exc:
        fail("referencias", "%s: %s" % (type(exc).__name__, exc))

    # 2. generacion
    if failed:
        mark("generacion", ST_SKIPPED)
    elif args.skip_generation:
        mark("generacion", ST_SKIPPED, "--skip-generation")
    else:
        mark("generacion", ST_RUNNING)
        try:
            try:
                manifest = manifest_mod.load(manifest_path, s3)
            except (OSError, ValueError, S3OperationFailed):
                manifest = manifest_mod.new_manifest()
            only = [x.strip() for x in args.only.split(",") if x.strip()] if args.only else None
            workdir = Path(out_dir) / "generated" / ".work"
            workdir.mkdir(parents=True, exist_ok=True)
            manifest = generator.generate_dataset(
                generator.default_plan(), manifest, s3, limit=args.limit, only=only,
                manifest_path=manifest_path, workdir=workdir, status=_say,
                metrics_dir=out_dir)
            shutil.rmtree(str(workdir), ignore_errors=True)
            mark("generacion", ST_DONE)
        except Exception as exc:  # noqa: BLE001 - cualquier fallo de la etapa
            fail("generacion", "%s: %s" % (type(exc).__name__, exc))

    # 3. verificacion
    if failed:
        mark("verificacion", ST_SKIPPED)
    else:
        mark("verificacion", ST_RUNNING)
        tmp_dir = Path(tempfile.mkdtemp(prefix="brand-verify-"))
        try:
            assets = [a for a in (manifest or {}).get("assets", [])
                      if a.get("estado", "GENERADO") == "GENERADO"]
            if args.only:
                wanted = {x.strip() for x in args.only.split(",") if x.strip()}
                assets = [a for a in assets if a.get("id") in wanted]
            if args.limit is not None:
                assets = assets[: max(0, args.limit)]
            client = _bedrock_client()
            with ThreadPoolExecutor(max_workers=POOL_SIZE) as pool:
                futures = [pool.submit(_verify_one, a, out_dir, s3, tmp_dir, client,
                                       args.refs_dir, args.pegasus, collected) for a in assets]
                rows = [f.result() for f in futures]
            mark("verificacion", ST_DONE, "%d activos" % len(rows))
            if args.only or args.limit is not None:
                rows = _merge_previous_rows(manifest, rows, s3)
        except Exception as exc:  # noqa: BLE001
            fail("verificacion", "%s: %s" % (type(exc).__name__, exc))
        finally:
            shutil.rmtree(str(tmp_dir), ignore_errors=True)

    # 4. informe (siempre; parcial si hubo fallo)
    mark("informe", ST_RUNNING)
    try:
        _emit_report(rows, s3, args.out_dir, failed, reason)
        mark("informe", ST_DONE, "parcial" if failed else "")
    except (OSError, ValueError, S3OperationFailed) as exc:
        mark("informe", ST_FAILED, "%s: %s" % (type(exc).__name__, exc))
        return 1
    return 1 if failed else 0


# --------------------------------------------------------------------------
# validate / incident
# --------------------------------------------------------------------------
def cmd_register(args: argparse.Namespace) -> int:
    from brand_verifier import register  # import perezoso

    return register.cmd_register(args)


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        args.s3 = None if args.no_s3 else _make_s3(False, DEFAULT_OUT_DIR)
    except Exception as exc:  # noqa: BLE001
        print("validate: no se pudo crear el cliente S3 (%s)" % type(exc).__name__, file=sys.stderr)
        return 1
    return manifest_mod.cmd_validate(args)


def cmd_incident(args: argparse.Namespace) -> int:
    try:
        obj = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("incident: archivo ilegible (%s)" % type(exc).__name__, file=sys.stderr)
        return 1
    try:
        s3 = _make_s3(args.no_s3, args.out_dir)
    except Exception as exc:  # noqa: BLE001
        print("incident: no se pudo crear el cliente S3 (%s)" % type(exc).__name__, file=sys.stderr)
        return 1
    try:
        result = incident.process_incident(obj, s3, metrics_dir=args.out_dir)
    except S3OperationFailed as exc:
        print("incident: %s" % exc, file=sys.stderr)
        return 1
    if not result.ok:
        print("incident: incidencia invalida: %s" % "; ".join(result.errores), file=sys.stderr)
        return 1
    print("incident: %s %s" % (result.id, result.estado))
    return 0 if result.estado == incident.ESTADO_TRIAJE_OK else 1


def cmd_narrate(args: argparse.Namespace) -> int:
    from brand_verifier import narration, secrets as secrets_mod  # import perezoso

    try:
        s3 = _make_s3(args.no_s3, args.out_dir)
    except Exception as exc:  # noqa: BLE001
        print("narrate: no se pudo crear el cliente S3 (%s)" % type(exc).__name__, file=sys.stderr)
        return 1
    path = args.manifest or os.path.join(args.out_dir, "generated", "manifest.json")
    try:
        manifest = manifest_mod.load(path, s3)
    except (OSError, ValueError, S3OperationFailed) as exc:
        print("narrate: manifiesto ilegible o ausente: %s" % exc, file=sys.stderr)
        return 1
    try:
        api_key = secrets_mod.get_optional(narration.SECRET_NAME)
    except secrets_mod.SecretNotFound as exc:
        print("narrate: falta el secreto %s" % exc.name, file=sys.stderr)
        return 1
    only = [x.strip() for x in args.only.split(",") if x.strip()] if args.only else None
    try:
        index = narration.narrate_all(manifest, s3, api_key, only=only, status=_say,
                                      metrics_dir=args.out_dir)
    except (narration.NarrationError, S3OperationFailed, OSError) as exc:
        print("narrate: %s" % secrets_mod.redact(str(exc)), file=sys.stderr)
        return 1
    _say("narrate: %d videos con audio" % len(index))
    return 0


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="brand_verifier")
    sub = p.add_subparsers(dest="command")

    r = sub.add_parser("run", help="referencias -> generacion -> verificacion -> informe")
    r.add_argument("--manifest", default=None, help="ruta del manifiesto (def. <out-dir>/generated/manifest.json)")
    r.add_argument("--skip-generation", action="store_true", help="usar activos ya generados")
    r.add_argument("--limit", type=int, default=None, help="procesar solo los N primeros activos")
    r.add_argument("--only", default=None, help="ids separados por comas")
    r.add_argument("--refs-dir", default=references.DEFAULT_DIR)
    r.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    r.add_argument("--no-s3", action="store_true", help="trabajar solo en local")
    r.add_argument("--pegasus", action="store_true", help="analisis complementario de video")
    r.set_defaults(func=cmd_run)

    v = sub.add_parser("validate", help="validar la etiqueta de un activo")
    v.add_argument("id")
    v.add_argument("--label", default=None)
    v.add_argument("--manifest", default=None)
    v.add_argument("--no-s3", action="store_true")
    v.set_defaults(func=cmd_validate)

    i = sub.add_parser("incident", help="procesar una incidencia (JSON)")
    i.add_argument("file")
    i.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    i.add_argument("--no-s3", action="store_true")
    i.set_defaults(func=cmd_incident)

    g = sub.add_parser("register", help="registrar un activo subido (imagen o video)")
    g.add_argument("--file", required=True, help="ruta local del archivo")
    g.add_argument("--label", required=True, choices=list(VALORES_VEREDICTO),
                    help="etiqueta esperada")
    g.add_argument("--id", default=None, help="id del activo (por defecto se genera)")
    g.add_argument("--manifest", default=None)
    g.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    g.add_argument("--no-s3", action="store_true", help="trabajar solo en local")
    g.set_defaults(func=cmd_register)

    n = sub.add_parser("narrate", help="cortina sonora (Stable Audio) para cada video")
    n.add_argument("--only", default=None, help="ids separados por comas")
    n.add_argument("--manifest", default=None)
    n.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    n.add_argument("--no-s3", action="store_true", help="trabajar solo en local")
    n.set_defaults(func=cmd_narrate)

    gen = sub.add_parser("generate", help="generar un activo nuevo en ComfyUI (y verificarlo)")
    gen.add_argument("--logo", required=True, choices=["CORRECTO", "INCORRECTO", "SIN_LOGO"])
    gen.add_argument("--tipo", required=True, choices=["imagen", "video"])
    gen.add_argument("--escena", default=None, choices=["atm", "oficina", "valla", "taza", "camiseta", "movil"],
                     help="escena predefinida (por defecto taza)")
    gen.add_argument("--prompt", default=None, help="escena personalizada (max. 300 caracteres)")
    gen.add_argument("--verify", action="store_true", help="verificar con Amazon Bedrock al terminar")
    gen.add_argument("--manifest", default=None)
    gen.add_argument("--refs-dir", default=references.DEFAULT_DIR)
    gen.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    gen.add_argument("--no-s3", action="store_true", help="trabajar solo en local")
    gen.set_defaults(func=cmd_generate)
    return p


def cmd_generate(args: argparse.Namespace) -> int:
    from brand_verifier import ondemand  # import perezoso

    return ondemand.cmd_generate(args)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = int(exc.code) if isinstance(exc.code, int) else 2
        given = list(sys.argv[1:] if argv is None else argv)
        if code != 0 and given[:1] == ["generate"]:
            return 1  # generate: 1 = entrada invalida (2 y 3 son fallos de generacion/verificacion)
        return code
    if not getattr(args, "func", None):
        parser.print_usage(sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
