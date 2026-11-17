"""Generador_ComfyUI (Requirement 5 y 6).

Genera el conjunto de datos de prueba SOLO con ComfyUI (``comfyui/client.py``
contra ``AgentUrl``); nunca con Nova Reel ni otro modelo de video de Bedrock.

Como se invoca ComfyUI de verdad (ver ``comfyui/README.md`` y ``catalog.json``):

- Imagen con logotipo: flujo ``product-shot`` con ``product_photo=<nombre subido
  con upload_image>`` y ``use_product_photo=True`` (el logo entra como imagen de
  referencia de FLUX.2) mas un ``prompt``. Sin logo: ``use_product_photo=False``.
- Video: flujo ``image-to-video`` (Wan2.2 14B) cuya entrada ``image`` es la imagen
  generada antes (se vuelve a subir con ``upload_image``). Por eso cada video son
  dos trabajos secuenciales: imagen fija -> clip.
- Los flujos API viven en ``comfyui/workflows/<slug>.json`` y los ajustes
  (node_id/input_name) en ``comfyui/catalog.json``.

Un solo trabajo a la vez, timeout de 900 s, sin reintentos; un fallo registra
``GENERACION_FALLIDA`` y se continua con el siguiente activo.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from brand_verifier import manifest as manifest_mod
from brand_verifier import metrics as metrics_mod
from brand_verifier import secrets as secrets_mod
from brand_verifier.incident import scene_prompt
from brand_verifier.references import LOGO_CORRECTO, LOGO_INCORRECTO
from brand_verifier.s3io import S3OperationFailed

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "assets" / "brand"
COMFY_DIR = REPO_ROOT / "comfyui"
CATALOG_PATH = COMFY_DIR / "catalog.json"
WORKFLOWS_DIR = COMFY_DIR / "workflows"

PROBE_TIMEOUT_S = 10
JOB_TIMEOUT_S = 900
INTERRUPT_TIMEOUT_S = 10
VIDEO_FRAMES = 65  # 4n+1; a 16 fps son ~4 s (rango exigido: 3-10 s)
# 320x192 (smoke) deja 'digital' ilegible; 832x480 (multiplos de 16) lo conserva sin disparar el tiempo.
VIDEO_WIDTH, VIDEO_HEIGHT = 832, 480
GENERATED_PREFIX = "brand/generated/"

FLUJO_IMAGEN = "product-shot"
FLUJO_VIDEO = "image-to-video"

# Estados de consola
ST_QUEUED = "en cola"
ST_RUNNING = "en curso"
ST_DONE = "completado"
ST_FAILED = "fallido"

CONTENT_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
}
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".mkv", ".gif")

log = logging.getLogger(__name__)

_job_lock = threading.Lock()  # garantiza un unico trabajo ComfyUI en vuelo


class GenerationError(Exception):
    """Fallo de un trabajo de generacion; el mensaje es el motivo (sin secretos)."""


# --------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class AssetSpec:
    id: str
    tipo: str                      # "imagen" | "video"
    etiqueta_esperada: str         # CORRECTO | INCORRECTO | SIN_LOGO
    prompt: str
    variant: str = "simple"        # "simple" | "atm" | "mixed"
    segments: Tuple[str, ...] = ()  # solo "mixed": etiquetas de cada clip, en orden

    @property
    def flujo(self) -> str:
        return FLUJO_IMAGEN if self.tipo == "imagen" else FLUJO_VIDEO


_LOGO_SCENES = {
    "CORRECTO": [
        "Professional product photo of a white ceramic coffee mug on a wooden desk, with the "
        "attached company logo clearly printed on the mug, soft daylight, sharp and legible logo",
        "A modern office reception wall with the attached company logo mounted as large clean "
        "signage, bright interior, logo centered and fully legible",
        "A blue tote bag lying on a table with the attached company logo printed large on the "
        "front, studio lighting, logo clearly legible",
    ],
    "INCORRECTO": [
        "Professional product photo of a white ceramic coffee mug on a wooden desk, with the "
        "attached company logo clearly printed on the mug, soft daylight, sharp and legible logo",
        "A modern office reception wall with the attached company logo mounted as large clean "
        "signage, bright interior, logo centered and fully legible",
        "A blue tote bag lying on a table with the attached company logo printed large on the "
        "front, studio lighting, logo clearly legible",
    ],
}
_NO_LOGO_SCENE = (
    "Professional product photo of a plain white ceramic coffee mug on a wooden desk, soft "
    "daylight, no logo, no text, no lettering anywhere"
)
_MOTION = (
    " Locked-off static camera, no camera movement, only very subtle ambient motion. The logo "
    "stays perfectly static, sharp and fully legible, including the small word below it; no "
    "morphing, no warping, no flicker, and no new text appears."
)
# Piezas publicas para activos a demanda (subcomando ``generate``). Las frases literales son
# marcadores con los que el Dashboard atribuye trabajos a la app (web/server/comfy-history.js).
LOGO_INSTRUCTION = "with the attached company logo"
NO_LOGO_INSTRUCTION = "no logo, no text, no lettering anywhere"
MOTION = _MOTION


def logo_instruction(where: str = "clearly visible") -> str:
    """Instruccion de logo para el prompt (``where``: donde aparece el logo en la escena)."""
    return "%s %s, sharp and fully legible, exactly as provided" % (LOGO_INSTRUCTION, where)


_ATM_INCIDENT = {
    "descripcion": (
        "Cajero automatico en una calle, de noche. La pantalla del cajero muestra el logotipo "
        "de la marca y un aviso generico de tarjeta retenida."
    )
}


def default_plan() -> List[AssetSpec]:
    """Plan por defecto de 12 activos (7 imagenes + 5 videos)."""
    plan: List[AssetSpec] = []
    for label, slug in (("CORRECTO", "correcto"), ("INCORRECTO", "incorrecto")):
        for i, scene in enumerate(_LOGO_SCENES[label], start=1):
            plan.append(AssetSpec("img-%s-%02d" % (slug, i), "imagen", label, scene))
    plan.append(AssetSpec("img-sinlogo-01", "imagen", "SIN_LOGO", _NO_LOGO_SCENE))

    atm_scene = scene_prompt(_ATM_INCIDENT)
    plan += [
        AssetSpec("vid-correcto-01", "video", "CORRECTO", _LOGO_SCENES["CORRECTO"][0] + _MOTION),
        AssetSpec("vid-correcto-02-atm", "video", "CORRECTO", atm_scene + _MOTION, variant="atm"),
        AssetSpec("vid-incorrecto-01", "video", "INCORRECTO", _LOGO_SCENES["INCORRECTO"][1] + _MOTION),
        AssetSpec("vid-incorrecto-02-mixto", "video", "INCORRECTO",
                  _LOGO_SCENES["CORRECTO"][2] + _MOTION, variant="mixed",
                  segments=("INCORRECTO", "CORRECTO")),
        AssetSpec("vid-sinlogo-01", "video", "SIN_LOGO", _NO_LOGO_SCENE + _MOTION),
    ]
    return plan


def select_input_logo(spec: Any) -> Optional[Path]:
    """Activo_Referencia de la marca esperada; ``None`` para SIN_LOGO (Property 10)."""
    label = spec.etiqueta_esperada
    if label == "CORRECTO":
        return ASSETS_DIR / LOGO_CORRECTO
    if label == "INCORRECTO":
        return ASSETS_DIR / LOGO_INCORRECTO
    return None


# --------------------------------------------------------------------------
# Cliente ComfyUI e infraestructura inyectable
# --------------------------------------------------------------------------
def load_comfy_client() -> Any:
    """Carga ``comfyui/client.py`` por ruta (la carpeta no es un paquete)."""
    spec = importlib.util.spec_from_file_location("comfyui_client", str(COMFY_DIR / "client.py"))
    if spec is None or spec.loader is None:
        raise GenerationError("no se pudo cargar comfyui/client.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_catalog_entry(slug: str, catalog_path: Path = CATALOG_PATH) -> Dict[str, Any]:
    data = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    for entry in data["workflows"]:
        if entry["slug"] == slug:
            return entry
    raise GenerationError("flujo no encontrado en catalog.json: %s" % slug)


def video_overrides(catalog_path: Path = CATALOG_PATH) -> Dict[str, Any]:
    """Ajustes minimos de ``image-to-video`` (smoke_overrides) con frames para 3-10 s."""
    smoke = dict(load_catalog_entry(FLUJO_VIDEO, catalog_path).get("smoke_overrides", {}))
    smoke["width"], smoke["height"] = VIDEO_WIDTH, VIDEO_HEIGHT
    smoke["frames"] = VIDEO_FRAMES  # smoke trae 9 frames (<1 s): insuficiente
    return smoke


def probe(base_url: str, token: str, timeout_s: float = PROBE_TIMEOUT_S) -> None:
    """Sondeo previo de AgentUrl; lanza GenerationError si no responde en 10 s."""
    req = urllib.request.Request(base_url.rstrip("/") + "/system_stats",
                                 headers={"Authorization": "Bearer %s" % token})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s):
            return
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise GenerationError("AgentUrl rechazo la autenticacion (HTTP %d)" % exc.code)
        return  # el servidor respondio
    except Exception as exc:  # noqa: BLE001
        raise GenerationError("AgentUrl no responde en %ds (%s)" % (timeout_s, type(exc).__name__))


def interrupt(base_url: str, token: str, timeout_s: float = INTERRUPT_TIMEOUT_S) -> bool:
    """Cancela el trabajo en curso con ``POST /interrupt`` (defensivo: nunca lanza)."""
    try:
        req = urllib.request.Request(
            base_url.rstrip("/") + "/interrupt", data=b"{}", method="POST",
            headers={"Authorization": "Bearer %s" % token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s):
            return True
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo cancelar el trabajo (/interrupt): %s", type(exc).__name__)
        return False


def _concat_opencv(paths: Sequence[Path], out_path: Path) -> Path:
    """Fallback sin ffmpeg: mp4v con resolucion/fps del primer clip."""
    try:
        import cv2
    except ImportError:
        raise GenerationError("ni ffmpeg ni OpenCV disponibles para concatenar")
    writer = None
    try:
        size = fps = None
        for p in paths:
            cap = cv2.VideoCapture(str(p))
            if not cap.isOpened():
                raise GenerationError("no se pudo abrir el clip %s" % Path(p).name)
            try:
                if writer is None:
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = cap.get(cv2.CAP_PROP_FPS) or 16.0
                    size = (w, h)
                    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"),
                                             fps, size)
                    if not writer.isOpened():
                        raise GenerationError("OpenCV no pudo crear el mp4 de salida")
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    if (frame.shape[1], frame.shape[0]) != size:
                        frame = cv2.resize(frame, size)
                    writer.write(frame)
            finally:
                cap.release()
    finally:
        if writer is not None:
            writer.release()
    if writer is None or not Path(out_path).is_file():
        raise GenerationError("la concatenacion con OpenCV no produjo salida")
    return Path(out_path)


def concat_videos(paths: Sequence[Path], out_path: Path) -> Path:
    """Concatena clips con ffmpeg si existe; si no, fallback con OpenCV."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return _concat_opencv(paths, out_path)
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    for p in paths:
        cmd += ["-i", str(p)]
    n = len(paths)
    graph = "".join("[%d:v:0]scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1[v%d];" % (i, i)
                    for i in range(n))
    graph += "".join("[v%d]" % i for i in range(n)) + "concat=n=%d:v=1:a=0[outv]" % n
    cmd += ["-filter_complex", graph, "-map", "[outv]", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-an", str(out_path)]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    if res.returncode != 0 or not Path(out_path).is_file():
        raise GenerationError("ffmpeg fallo (codigo %d)" % res.returncode)
    return Path(out_path)


@dataclass
class Runtime:
    """Dependencias de E/S de una ejecucion (todas inyectables en tests)."""
    client: Any
    base_url: str
    token: str
    workdir: Path
    status: Callable[[str], None] = print
    probe: Callable[[str, str], None] = probe
    interrupt: Callable[[str, str], Any] = interrupt
    concat: Callable[[Sequence[Path], Path], Path] = concat_videos
    catalog_path: Path = CATALOG_PATH
    workflows_dir: Path = WORKFLOWS_DIR
    timeout_s: int = JOB_TIMEOUT_S
    extra: Dict[str, Any] = field(default_factory=dict)
    jobs: List[Dict[str, Any]] = field(default_factory=list)  # metricas por trabajo ComfyUI


# --------------------------------------------------------------------------
# Trabajos
# --------------------------------------------------------------------------
def _run_flow(rt: Runtime, slug: str, overrides: Dict[str, Any], out_dir: Path,
              label: str, job_id: Optional[str] = None, step: Optional[str] = None) -> Path:
    """Ejecuta UN flujo ComfyUI (un solo trabajo a la vez) y devuelve el fichero resultante."""
    entry = load_catalog_entry(slug, rt.catalog_path)
    graph = json.loads((Path(rt.workflows_dir) / (slug + ".json")).read_text(encoding="utf-8"))
    graph = rt.client.apply_overrides(graph, entry["inputs"], overrides)
    rt.status("%s: %s" % (label, ST_QUEUED))
    job = {"id": job_id or label, "step": step or slug, "workflow": slug,
           "status": "failed", "seconds": 0.0, "started_at": metrics_mod.now_iso()}
    with _job_lock:
        rt.status("%s: %s" % (label, ST_RUNNING))
        t0 = time.monotonic()
        job["started_at"] = metrics_mod.now_iso()
        try:
            files = rt.client.run_workflow(rt.base_url, graph, timeout_s=rt.timeout_s,
                                           out_dir=out_dir, token=rt.token)
            job["status"] = "completed"
        except TimeoutError:
            job["status"] = "timeout"
            rt.interrupt(rt.base_url, rt.token)  # cancelar para liberar la GPU compartida
            raise GenerationError("timeout: el trabajo no finalizo en %ds" % rt.timeout_s)
        finally:
            job["seconds"] = round(time.monotonic() - t0, 3)
            rt.jobs.append(job)
    wanted = IMAGE_EXTS if slug == FLUJO_IMAGEN else VIDEO_EXTS
    for f in files:
        if Path(f).suffix.lower() in wanted:
            return Path(f)
    raise GenerationError("el flujo %s no devolvio ningun fichero %s" % (
        slug, "/".join(wanted)))


def _upload(rt: Runtime, path: Path) -> str:
    if not Path(path).is_file():
        raise GenerationError("fichero de entrada ausente: %s" % Path(path).name)
    return rt.client.upload_image(rt.base_url, Path(path), rt.token)


def _make_still(rt: Runtime, label: str, prompt: str, etiqueta: str, out_dir: Path,
                size: Optional[Tuple[int, int]] = None, job_id: Optional[str] = None,
                step: Optional[str] = None) -> Tuple[Path, Dict[str, Any]]:
    """Imagen fija con product-shot: logo de la marca esperada como entrada (o ninguna)."""
    logo = select_input_logo(_LabelOnly(etiqueta))
    overrides: Dict[str, Any] = {"prompt": prompt, "use_product_photo": logo is not None}
    if logo is not None:
        overrides["product_photo"] = _upload(rt, logo)
    if size is not None:
        overrides["width"], overrides["height"] = size
    return _run_flow(rt, FLUJO_IMAGEN, overrides, out_dir, label, job_id, step), overrides


@dataclass(frozen=True)
class _LabelOnly:
    etiqueta_esperada: str


def _make_clip(rt: Runtime, spec_id: str, prompt: str, etiqueta: str, out_dir: Path,
               vid_over: Dict[str, Any]) -> Tuple[Path, Dict[str, Any]]:
    size = (int(vid_over["width"]), int(vid_over["height"])) if "width" in vid_over else None
    still, still_over = _make_still(rt, "%s [imagen base]" % spec_id, prompt, etiqueta,
                                    out_dir / ("still-%s" % etiqueta.lower()), size,
                                    job_id=spec_id, step="imagen base %s" % etiqueta)
    over = dict(vid_over)
    over["image"] = _upload(rt, still)
    over["prompt"] = prompt
    clip = _run_flow(rt, FLUJO_VIDEO, over, out_dir / ("clip-%s" % etiqueta.lower()),
                     "%s [clip %s]" % (spec_id, etiqueta),
                     job_id=spec_id, step="clip %s" % etiqueta)
    return clip, {"still": {k: v for k, v in still_over.items()}, "video": over}


def run_job(spec: AssetSpec, rt: Runtime) -> Tuple[Path, Dict[str, Any]]:
    """Genera un activo y devuelve (fichero final, ajustes usados). Lanza GenerationError."""
    out_dir = Path(rt.workdir) / spec.id
    out_dir.mkdir(parents=True, exist_ok=True)
    rt.probe(rt.base_url, rt.token)
    if spec.tipo == "imagen":
        path, over = _make_still(rt, spec.id, spec.prompt, spec.etiqueta_esperada, out_dir,
                                 job_id=spec.id, step="imagen")
        return path, over
    vid_over = video_overrides(rt.catalog_path)
    if spec.variant == "mixed":
        clips: List[Path] = []
        used: List[Dict[str, Any]] = []
        for etiqueta in spec.segments:
            clip, over = _make_clip(rt, spec.id, spec.prompt, etiqueta, out_dir, vid_over)
            clips.append(clip)
            used.append(over)
        out = out_dir / "output.mp4"
        path = rt.concat(clips, out)
        return Path(path), {"segmentos": list(spec.segments), "clips": used, "concat": "ffmpeg"}
    clip, over = _make_clip(rt, spec.id, spec.prompt, spec.etiqueta_esperada, out_dir, vid_over)
    return clip, over


def _clean_settings(over: Dict[str, Any]) -> Dict[str, Any]:
    """Ajustes registrables: sin rutas locales ni secretos (manifest.filter_settings filtra claves)."""
    return json.loads(json.dumps(over, default=str))


def _reason(exc: BaseException) -> str:
    text = secrets_mod.redact("%s: %s" % (type(exc).__name__, exc))
    return text[:300]


# --------------------------------------------------------------------------
# Orquestacion del conjunto de datos
# --------------------------------------------------------------------------
def select_specs(plan: Sequence[AssetSpec], limit: Optional[int] = None,
                 only: Optional[Iterable[str]] = None) -> List[AssetSpec]:
    """Subconjunto del plan: ``only`` (ids) y despues ``limit`` (primeros N)."""
    specs = list(plan)
    if only is not None:
        wanted = set(only)
        specs = [s for s in specs if s.id in wanted]
    if limit is not None:
        specs = specs[: max(0, int(limit))]
    return specs


def generate_dataset(
    plan: Sequence[AssetSpec],
    manifest: Dict[str, Any],
    s3: Any = None,
    *,
    limit: Optional[int] = None,
    only: Optional[Iterable[str]] = None,
    manifest_path: Optional[str] = None,
    workdir: Optional[Path] = None,
    base_url: Optional[str] = None,
    token: Optional[str] = None,
    client: Any = None,
    status: Callable[[str], None] = print,
    probe_fn: Optional[Callable[[str, str], None]] = None,
    interrupt_fn: Optional[Callable[[str, str], Any]] = None,
    concat_fn: Optional[Callable[[Sequence[Path], Path], Path]] = None,
    catalog_path: Path = CATALOG_PATH,
    workflows_dir: Path = WORKFLOWS_DIR,
    timeout_s: int = JOB_TIMEOUT_S,
    metrics_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Genera los activos del plan, uno a uno, y los registra en el Manifiesto.

    ``limit``/``only`` permiten generar un subconjunto (modo CLI). Un fallo de un
    activo lo registra como GENERACION_FALLIDA y continua con el siguiente.
    """
    specs = select_specs(plan, limit, only)
    if not specs:
        return manifest
    url = base_url or secrets_mod.get_agent_url()
    tok = token or secrets_mod.get_agent_token()
    secrets_mod.register_secret(tok)
    own_tmp = workdir is None
    work = Path(workdir) if workdir is not None else Path(tempfile.mkdtemp(prefix="brand-gen-"))
    rt = Runtime(
        client=client if client is not None else load_comfy_client(),
        base_url=url, token=tok, workdir=work, status=status,
        probe=probe_fn or probe, interrupt=interrupt_fn or interrupt,
        concat=concat_fn or concat_videos, catalog_path=catalog_path,
        workflows_dir=workflows_dir, timeout_s=timeout_s,
    )
    for spec in specs:
        status("%s: %s" % (spec.id, ST_QUEUED))
        try:
            path, over = run_job(spec, rt)
            key = "%s%s/output%s" % (GENERATED_PREFIX, spec.id, Path(path).suffix.lower())
            if s3 is not None:
                s3.put(key, str(path), asset_id=spec.id,
                       content_type=CONTENT_TYPES.get(Path(path).suffix.lower()))
            manifest_mod.register_asset(
                manifest, spec.id, spec.tipo, spec.flujo, _clean_settings(over),
                spec.etiqueta_esperada, s3_key=key, estado="GENERADO")
            status("%s: %s" % (spec.id, ST_DONE))
        except (GenerationError, S3OperationFailed, OSError, ValueError, RuntimeError,
                KeyError) as exc:
            reason = _reason(exc)
            log.error("Generacion fallida (%s): %s", spec.id, reason)
            manifest_mod.register_asset(
                manifest, spec.id, spec.tipo, spec.flujo, {}, spec.etiqueta_esperada,
                s3_key=None, estado="GENERACION_FALLIDA", motivo=reason)
            status("%s: %s (%s)" % (spec.id, ST_FAILED, reason))
        if manifest_path is not None:
            manifest_mod.save(manifest, manifest_path, s3)
    if rt.jobs:
        try:
            host = urlparse(url).hostname or ""
            metrics_mod.merge_comfyui(s3, metrics_dir, host, rt.jobs)
        except Exception as exc:  # noqa: BLE001 - las metricas nunca rompen la generacion
            log.warning("metricas ComfyUI no escritas (%s)", type(exc).__name__)
    if own_tmp and not os.environ.get("BRAND_KEEP_WORKDIR"):
        shutil.rmtree(str(work), ignore_errors=True)
    return manifest
