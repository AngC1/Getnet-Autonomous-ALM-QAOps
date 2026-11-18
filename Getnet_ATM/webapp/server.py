#!/usr/bin/env python3
"""ATM Sentinel Web: recepción de vídeos de cajero y visor de informes.

Servidor HTTP mínimo (librería estándar + boto3). Todo el estado vive en S3:

    s3://<bucket>/incidents/<id>/
        video/<archivo>.mp4    vídeo recibido
        metadata.json          ID cajero, ubicación, evento, fecha-hora
        status.json            estado actual + historial
        frames/frame_XX.jpg    fotogramas clave enviados al modelo
        report.json            informe de riesgo

Uso:
    python3 webapp/server.py [--port 8090]
Abrir: la URL del proxy del IDE, p. ej. https://<host>/proxy/8090/  (con barra final)
"""
from __future__ import annotations

import argparse
import cgi
import json
import logging
import mimetypes
import os
import re
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics  # noqa: E402

metrics.install()  # antes de crear clientes boto3, para medir todas las llamadas

import atm_sentinel as sentinel  # noqa: E402
from live import LiveSession  # noqa: E402

BUCKET = os.environ.get("ATM_BUCKET", "me-hack-media-385927210791-us-east-1")
PREFIX = "incidents/"
MODEL_IDS = [os.environ.get("ATM_SENTINEL_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")]
N_FRAMES = 6
MAX_UPLOAD = 300 * 1024 * 1024  # 300 MB
URL_TTL = 3600
STATIC = Path(__file__).resolve().parent / "static"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ATM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,50}$")

log = logging.getLogger("atm_web")
s3 = boto3.client("s3", region_name=sentinel.REGION,
                  config=Config(signature_version="s3v4", retries={"max_attempts": 4, "mode": "standard"}))
executor = ThreadPoolExecutor(max_workers=2)
_status_lock = threading.Lock()


# --------------------------------------------------------------------------- S3 helpers
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_json(key: str) -> dict | None:
    try:
        return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def put_json(key: str, data: dict) -> None:
    s3.put_object(Bucket=BUCKET, Key=key, ContentType="application/json",
                  Body=json.dumps(data, ensure_ascii=False, indent=2).encode())


def list_keys(prefix: str) -> list[dict]:
    out, token = [], None
    while True:
        kw = {"Bucket": BUCKET, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kw)
        out += resp.get("Contents", [])
        if not resp.get("IsTruncated"):
            return out
        token = resp["NextContinuationToken"]


def presign(key: str) -> str:
    return s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=URL_TTL)


def set_status(inc_id: str, status: str, **extra) -> None:
    """Escribe status.json con historial. Si falla, se conserva la última versión buena."""
    key = f"{PREFIX}{inc_id}/status.json"
    with _status_lock:
        cur = get_json(key) or {"history": []}
        ts = now_iso()
        cur.update({"status": status, "updated_at": ts, **extra})
        if status != "FALLIDO":
            cur.pop("error", None)
        cur["history"].append({"status": status, "at": ts})
        try:
            put_json(key, cur)
        except ClientError as e:
            log.error("No se pudo escribir status de %s: %s", inc_id, e)


# --------------------------------------------------------------------------- pipeline
def find_video_key(inc_id: str) -> str | None:
    vids = [o["Key"] for o in list_keys(f"{PREFIX}{inc_id}/")
            if o["Key"].lower().endswith((".mp4", ".mov", ".webm", ".m4v"))]
    preferred = [k for k in vids if "/video/" in k]
    return (preferred or vids or [None])[0]


def load_metadata(inc_id: str) -> dict | None:
    meta = get_json(f"{PREFIX}{inc_id}/metadata.json")
    if meta:
        return meta
    rep = get_json(f"{PREFIX}{inc_id}/report.json")  # incidencias creadas desde la CLI
    if rep:
        return {k: rep.get(k) for k in ("atm_id", "location", "tamper_event", "event_timestamp", "client")}
    return None


def process_incident(inc_id: str) -> None:
    try:
        meta = load_metadata(inc_id)
        video_key = find_video_key(inc_id)
        if not meta or not video_key:
            raise ValueError("Faltan metadatos o vídeo para esta incidencia")

        set_status(inc_id, "EXTRAYENDO_FOTOGRAMAS")
        with tempfile.TemporaryDirectory() as tmp:
            local = os.path.join(tmp, os.path.basename(video_key))
            s3.download_file(BUCKET, video_key, local)
            frames = sentinel.extract_key_frames(local, N_FRAMES)

        for old in list_keys(f"{PREFIX}{inc_id}/frames/"):
            s3.delete_object(Bucket=BUCKET, Key=old["Key"])
        for i, f in enumerate(frames, 1):
            f["s3_key"] = f"{PREFIX}{inc_id}/frames/frame_{i:02d}_{f['time_s']:.2f}s.jpg"
            s3.put_object(Bucket=BUCKET, Key=f["s3_key"], Body=f["jpeg"], ContentType="image/jpeg")

        set_status(inc_id, "ANALIZANDO", frames=len(frames), model_id=MODEL_IDS[0])
        analysis, model_used = sentinel.analyze(sentinel.bedrock_client(), MODEL_IDS, meta, frames)
        report = sentinel.assemble_report(meta, analysis, model_used, f"s3://{BUCKET}/{video_key}", frames)
        report["incident_id"] = inc_id
        put_json(f"{PREFIX}{inc_id}/report.json", report)
        set_status(inc_id, "COMPLETADO", risk_level=report["risk_level"], threat_type=report["threat_type"])
        log.info("Incidencia %s completada: %s / %s", inc_id, report["risk_level"], report["threat_type"])
    except Exception as e:  # cualquier fallo queda visible en la interfaz
        log.exception("Fallo procesando %s", inc_id)
        set_status(inc_id, "FALLIDO", error=str(e)[:500])


# --------------------------------------------------------------------------- vistas
def incident_summary(inc_id: str) -> dict:
    status = get_json(f"{PREFIX}{inc_id}/status.json") or {}
    meta = load_metadata(inc_id) or {}
    rep = get_json(f"{PREFIX}{inc_id}/report.json") if status.get("status", "COMPLETADO") == "COMPLETADO" else None
    return {
        "id": inc_id,
        "status": status.get("status") or ("COMPLETADO" if rep else "RECIBIDO"),
        "updated_at": status.get("updated_at") or (rep or {}).get("analysis", {}).get("generated_at"),
        "atm_id": meta.get("atm_id"),
        "location": meta.get("location"),
        "risk_level": (rep or {}).get("risk_level") or status.get("risk_level"),
        "threat_type": (rep or {}).get("threat_type") or status.get("threat_type"),
    }


def list_incidents() -> list[dict]:
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX, Delimiter="/")
    ids = [p["Prefix"][len(PREFIX):-1] for p in resp.get("CommonPrefixes", [])]
    items = [incident_summary(i) for i in ids if ID_RE.match(i)]
    return sorted(items, key=lambda x: x.get("updated_at") or "", reverse=True)


def incident_detail(inc_id: str) -> dict | None:
    objects = list_keys(f"{PREFIX}{inc_id}/")
    if not objects:
        return None
    report = get_json(f"{PREFIX}{inc_id}/report.json")
    status = get_json(f"{PREFIX}{inc_id}/status.json") or {
        "status": "COMPLETADO" if report else "RECIBIDO", "history": []}
    video_key = find_video_key(inc_id)

    by_key = {f.get("s3_key"): f for f in (report or {}).get("analysis", {}).get("frames_analyzed", [])}
    frames = []
    for o in sorted(objects, key=lambda o: o["Key"]):
        if "/frames/" in o["Key"] and o["Key"].endswith(".jpg"):
            m = re.search(r"_(\d+(?:\.\d+)?)s\.jpg$", o["Key"])
            info = by_key.get(o["Key"], {})
            frames.append({"key": o["Key"], "url": presign(o["Key"]),
                           "time_s": info.get("time_s", float(m.group(1)) if m else None),
                           "index": info.get("index")})
    return {
        "id": inc_id,
        "status": status,
        "metadata": load_metadata(inc_id),
        "report": report,
        "video": {"key": video_key, "uri": f"s3://{BUCKET}/{video_key}", "url": presign(video_key)} if video_key else None,
        "frames": frames,
        "objects": [{"key": o["Key"], "size": o["Size"], "uri": f"s3://{BUCKET}/{o['Key']}",
                     "last_modified": o["LastModified"].isoformat(timespec="seconds")} for o in objects],
    }


def validate_new(fields: dict) -> tuple[dict, list[str]]:
    errs = []
    atm_id = (fields.get("atm_id") or "").strip()
    location = (fields.get("location") or "").strip()
    event = (fields.get("event") or "").strip()
    ts = (fields.get("timestamp") or "").strip() or now_iso()
    if not ATM_ID_RE.match(atm_id):
        errs.append("atm_id: obligatorio, 1-50 caracteres alfanuméricos, '-' o '_'")
    if not 1 <= len(location) <= 200:
        errs.append("location: obligatoria, 1-200 caracteres")
    if not 1 <= len(event) <= 2000:
        errs.append("event: obligatorio, 1-2000 caracteres")
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            errs.append("timestamp: debe incluir zona horaria")
        elif parsed > datetime.now(timezone.utc) + timedelta(minutes=5):
            errs.append("timestamp: no puede estar en el futuro")
    except ValueError:
        errs.append("timestamp: formato ISO 8601 inválido")
    return sentinel.build_meta(atm_id, location, event, ts), errs


# --------------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "ATMSentinel/1.0"

    def log_message(self, fmt, *args):  # sin query strings (pueden contener firmas)
        log.info("%s %s", self.command, urlparse(self.path).path)

    def _json(self, code: int, data) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, name: str) -> None:
        path = (STATIC / name).resolve()
        if STATIC not in path.parents or not path.is_file():
            return self._json(404, {"error": "No encontrado"})
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(path.name)[0] or "text/plain") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/api/incidents":
                return self._json(200, list_incidents())
            if path == "/api/live":
                return self._json(200, live_state())
            if path == "/api/metrics":
                return self._json(200, metrics_state())
            if path in ("/dashboard", "/dashboard.html"):
                return self._static("dashboard.html")
            m = re.fullmatch(r"/api/incidents/([^/]+)", path)
            if m and ID_RE.match(m.group(1)):
                d = incident_detail(m.group(1))
                return self._json(200, d) if d else self._json(404, {"error": "Incidencia no encontrada"})
            self._json(404, {"error": "No encontrado"})
        except Exception as e:
            log.exception("GET %s", path)
            self._json(500, {"error": str(e)[:300]})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/incidents":
                return self._create()
            if path == "/api/live/start":
                q = parse_qs(urlparse(self.path).query)
                speed = min(max(float(q.get("speed", ["1"])[0]), 0.5), 8.0)
                try:
                    live_session.start(speed=speed)
                except RuntimeError as e:
                    return self._json(409, {"error": str(e)})
                return self._json(200, live_state())
            if path == "/api/live/stop":
                live_session.stop()
                return self._json(200, live_state())
            m = re.fullmatch(r"/api/incidents/([^/]+)/analyze", path)
            if m and ID_RE.match(m.group(1)):
                inc_id = m.group(1)
                if not list_keys(f"{PREFIX}{inc_id}/"):
                    return self._json(404, {"error": "Incidencia no encontrada"})
                set_status(inc_id, "EN_COLA")
                executor.submit(process_incident, inc_id)
                return self._json(202, {"id": inc_id, "status": "EN_COLA"})
            self._json(404, {"error": "No encontrado"})
        except Exception as e:
            log.exception("POST %s", path)
            self._json(500, {"error": str(e)[:300]})

    def _create(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._json(400, {"error": "Petición vacía"})
        if length > MAX_UPLOAD:
            return self._json(413, {"error": f"El vídeo supera {MAX_UPLOAD // (1024 * 1024)} MB"})
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={
            "REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": str(length)})
        fields = {k: form.getfirst(k) for k in ("atm_id", "location", "event", "timestamp")}
        meta, errs = validate_new(fields)
        video = form["video"] if "video" in form else None
        if video is None or not getattr(video, "filename", None):
            errs.append("video: obligatorio")
        if errs:
            return self._json(400, {"error": "Datos inválidos", "details": errs})

        try:
            meta["source"] = "Subida manual"
            inc_id, key = create_incident(meta, video.file, video.filename)
        except ClientError as e:
            return self._json(502, {"error": f"No se pudo registrar el vídeo en S3: {e}"})
        self._json(201, {"id": inc_id, "status": "RECIBIDO", "video_uri": f"s3://{BUCKET}/{key}"})


def create_incident(meta: dict, fileobj, filename: str) -> tuple[str, str]:
    """Guarda vídeo + metadatos en S3, marca RECIBIDO y lanza el análisis en segundo plano."""
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(filename))[:100] or "video.mp4"
    inc_id = f"{meta['atm_id']}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"[:64]
    key = f"{PREFIX}{inc_id}/video/{safe_name}"
    s3.upload_fileobj(fileobj, BUCKET, key, ExtraArgs={
        "ContentType": mimetypes.guess_type(safe_name)[0] or "video/mp4"})
    meta.update({"received_at": now_iso(), "original_filename": filename, "video_key": key})
    put_json(f"{PREFIX}{inc_id}/metadata.json", meta)
    set_status(inc_id, "RECIBIDO")
    executor.submit(process_incident, inc_id)
    return inc_id, key


# --------------------------------------------------------------------------- directo
LIVE_ATM = {"atm_id": "ES_MAD_0482", "location": "Sucursal Principal - Calle Alcalá, Madrid (ejemplo)"}


def on_live_clip(path: Path, det: dict) -> str:
    """El detector en directo entrega aquí el corte de vídeo."""
    def mmss(s: float) -> str:
        return f"{int(s // 60)}:{int(s % 60):02d}"
    event = (f"Detección automática en directo ({det['detector_model']}): {det['observation'].rstrip('. ')}. "
             f"Manipulación detectada en {mmss(det['detected_at_s'])}; corte {mmss(det['clip_start_s'])}"
             f"–{mmss(det['clip_end_s'])} del flujo de la cámara.")
    meta = sentinel.build_meta(LIVE_ATM["atm_id"], LIVE_ATM["location"], event, now_iso())
    meta.update(source="Detección automática en directo", detection=det)
    with open(path, "rb") as fh:
        inc_id, _ = create_incident(meta, fh, path.name)
    log.info("Corte en directo enviado como incidencia %s", inc_id)
    return inc_id


live_session = LiveSession(s3, BUCKET, "live/atm_cam_live.mp4", on_live_clip)


def storage_stats() -> dict:
    out = {}
    for prefix in ("incidents/", "live/"):
        objs = list_keys(prefix)
        out[prefix] = {"objects": len(objs), "bytes": sum(o["Size"] for o in objs),
                       "videos": sum(o["Key"].endswith(".mp4") for o in objs),
                       "frames": sum(o["Key"].endswith(".jpg") for o in objs)}
    return out


def pipeline_stats() -> dict:
    items = list_incidents()
    durations = []
    for i in items[:30]:
        hist = (get_json(f"{PREFIX}{i['id']}/status.json") or {}).get("history", [])
        # Última ejecución: último COMPLETADO y la entrada (RECIBIDO/EN_COLA) más reciente anterior a él
        t_in = t_out = None
        for h in hist:
            if h["status"] in ("RECIBIDO", "EN_COLA"):
                t_in, t_out = h["at"], None
            elif h["status"] == "COMPLETADO" and t_in:
                t_out = h["at"]
        if t_in and t_out and t_out >= t_in:
            durations.append((datetime.fromisoformat(t_out) - datetime.fromisoformat(t_in)).total_seconds())
    return {"total": len(items), "by_status": dict(Counter(i["status"] for i in items)),
            "by_risk": dict(Counter(i["risk_level"] for i in items if i.get("risk_level"))),
            "avg_processing_s": round(sum(durations) / len(durations), 1) if durations else None,
            "last": items[0] if items else None}


_cache = {
    "host": metrics.Cached(1.5, metrics.host_stats),
    "comfy": metrics.Cached(5, metrics.comfy_stats),
    "cloudwatch": metrics.Cached(60, metrics.cloudwatch_stats),
    "storage": metrics.Cached(30, storage_stats),
    "pipeline": metrics.Cached(15, pipeline_stats),
}


def metrics_state() -> dict:
    snap = live_session.snapshot()
    done = [s for s in snap["samples"] if s["status"] != "pending"]
    return {
        "server_now": time.time(),
        "app": metrics.meter.snapshot(),
        "live": {"state": snap["state"], "position_s": snap["position_s"], "duration_s": snap["duration_s"],
                 "samples": len(done), "positives": sum(bool(s.get("positive")) for s in done),
                 "detector_model": snap["detector_model"], "incident_id": snap["incident_id"],
                 "alert": snap["alert"]["state"], "ended": snap["ended"]},
        **{k: c.get() for k, c in _cache.items()},
    }


def live_state() -> dict:
    snap = live_session.snapshot()
    snap["video_url"] = presign("live/atm_cam_live.mp4")
    if snap["incident_id"]:
        st = get_json(f"{PREFIX}{snap['incident_id']}/status.json") or {}
        snap["incident_status"] = st.get("status")
    return snap


def main() -> None:
    ap = argparse.ArgumentParser(description="ATM Sentinel Web")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("botocore").setLevel(logging.WARNING)
    proxy = os.environ.get("VSCODE_PROXY_URI", "").replace("{{port}}", str(args.port))
    log.info("ATM Sentinel Web en http://%s:%d  %s", args.host, args.port, f"(proxy: {proxy})" if proxy else "")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
