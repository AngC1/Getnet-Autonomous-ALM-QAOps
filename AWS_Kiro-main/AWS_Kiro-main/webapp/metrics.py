"""Métricas de consumo y recursos para el dashboard de ATM Sentinel.

Fuentes:
- Bedrock (esta app, tiempo real): hooks de botocore en cada llamada Converse
  -> tokens de entrada/salida, latencia, errores y coste estimado por modelo.
- S3 (esta app): nº de operaciones por tipo, también por hooks de botocore.
- CloudWatch AWS/Bedrock (toda la cuenta, ~1-2 min de retraso): invocaciones, tokens, latencia.
- ComfyUI (GPU del equipo): /system_stats y /queue con el token del agente (nunca se expone).
- Servidor: CPU, memoria y disco leyendo /proc (sin dependencias).

`install()` debe llamarse ANTES de crear cualquier cliente boto3.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import urllib.request
from collections import Counter, deque
from datetime import datetime, timedelta, timezone

import boto3

# USD por 1M tokens (entrada, salida). Perfil geográfico US = global + 10 %.
# Fuente: guía de precios de Bedrock de CloudForecast (oct. 2026). Es una estimación;
# la factura real está en Cost Explorer (los modelos de Anthropic se facturan vía Marketplace).
PRICES = {
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.10, 5.50),
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": (3.30, 16.50),
}
LABELS = {
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": ("Claude Haiku 4.5", "Detector en directo"),
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": ("Claude Sonnet 4.5", "Informe de riesgo"),
}
BUCKET_S = 15
WINDOW_S = 15 * 60


def cost_of(model: str, tin: int, tout: int) -> float | None:
    p = PRICES.get(model)
    return None if p is None else (tin * p[0] + tout * p[1]) / 1e6


def label(model: str) -> dict:
    name, role = LABELS.get(model, (model, "Otro"))
    return {"name": name, "role": role}


# --------------------------------------------------------------------------- medidor
class Meter:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.time()
        self.calls: deque = deque(maxlen=5000)
        self.s3_ops: Counter = Counter()
        self.s3_errors = 0

    def bedrock(self, model: str, tin: int, tout: int, latency_ms: float, ok: bool, error: str | None):
        with self.lock:
            self.calls.append({"ts": time.time(), "model": model, "in": tin, "out": tout,
                               "latency_ms": latency_ms, "ok": ok, "error": error,
                               "cost": cost_of(model, tin, tout) or 0.0})

    def s3(self, op: str, ok: bool):
        with self.lock:
            self.s3_ops[op] += 1
            if not ok:
                self.s3_errors += 1

    def snapshot(self) -> dict:
        now = time.time()
        with self.lock:
            calls = list(self.calls)
            s3_ops = dict(self.s3_ops)
            s3_err = self.s3_errors
        per_model: dict[str, dict] = {}
        for c in calls:
            m = per_model.setdefault(c["model"], {"model": c["model"], **label(c["model"]), "calls": 0, "errors": 0,
                                                  "in": 0, "out": 0, "cost": 0.0, "_lat": []})
            m["calls"] += 1
            m["errors"] += 0 if c["ok"] else 1
            m["in"] += c["in"]
            m["out"] += c["out"]
            m["cost"] += c["cost"]
            if c["ok"]:
                m["_lat"].append(c["latency_ms"])
        for m in per_model.values():
            lat = sorted(m.pop("_lat"))
            m["latency_avg_ms"] = round(sum(lat) / len(lat)) if lat else None
            m["latency_p95_ms"] = round(lat[min(len(lat) - 1, int(len(lat) * 0.95))]) if lat else None
            m["price_in"], m["price_out"] = PRICES.get(m["model"], (None, None))

        # Serie temporal: últimos 15 min en cubos de 15 s
        n = WINDOW_S // BUCKET_S
        start = (int(now) // BUCKET_S - n + 1) * BUCKET_S
        series = [{"t": start + i * BUCKET_S, "models": {}} for i in range(n)]
        for c in calls:
            i = (int(c["ts"]) - start) // BUCKET_S
            if 0 <= i < n:
                b = series[i]["models"].setdefault(c["model"], {"calls": 0, "tokens": 0, "cost": 0.0, "lat": []})
                b["calls"] += 1
                b["tokens"] += c["in"] + c["out"]
                b["cost"] += c["cost"]
                b["lat"].append(c["latency_ms"])
        for b in series:
            for v in b["models"].values():
                v["latency_avg_ms"] = round(sum(v["lat"]) / len(v["lat"]))
                del v["lat"]

        last_min = [c for c in calls if c["ts"] > now - 60]
        return {
            "since": self.started,
            "uptime_s": round(now - self.started),
            "totals": {
                "calls": len(calls), "errors": sum(not c["ok"] for c in calls),
                "in": sum(c["in"] for c in calls), "out": sum(c["out"] for c in calls),
                "cost": round(sum(c["cost"] for c in calls), 6),
                "calls_last_min": len(last_min),
                "tokens_last_min": sum(c["in"] + c["out"] for c in last_min),
                "cost_last_min": round(sum(c["cost"] for c in last_min), 6),
            },
            "models": sorted(per_model.values(), key=lambda m: -m["cost"]),
            "series": series,
            "bucket_s": BUCKET_S,
            "recent": [dict(c, **label(c["model"])) for c in calls[-25:]][::-1],
            "s3_ops": s3_ops, "s3_errors": s3_err,
        }


meter = Meter()


def install() -> None:
    """Registra hooks de botocore en la sesión por defecto (afecta a los clientes creados después)."""
    session = boto3._get_default_session()._session

    def before(params, context, **_):
        context["atm_model"] = params.get("modelId")
        context["atm_t0"] = time.perf_counter()

    def after(http_response, parsed, context, **_):
        if "atm_t0" not in context:
            return
        ok = http_response.status_code < 400
        usage = parsed.get("usage", {}) if ok else {}
        latency = parsed.get("metrics", {}).get("latencyMs") if ok else None
        meter.bedrock(context.get("atm_model") or "?", usage.get("inputTokens", 0), usage.get("outputTokens", 0),
                      latency or (time.perf_counter() - context["atm_t0"]) * 1000, ok,
                      None if ok else parsed.get("Error", {}).get("Code"))

    def after_error(context, exception, **_):
        if "atm_t0" in context:
            meter.bedrock(context.get("atm_model") or "?", 0, 0, (time.perf_counter() - context["atm_t0"]) * 1000,
                          False, type(exception).__name__)

    def s3_after(http_response, model, **_):
        meter.s3(model.name, http_response.status_code < 400)

    session.register("provide-client-params.bedrock-runtime.Converse", before)
    session.register("after-call.bedrock-runtime.Converse", after)
    session.register("after-call-error.bedrock-runtime.Converse", after_error)
    session.register("after-call.s3", s3_after)


# --------------------------------------------------------------------------- caché simple
class Cached:
    def __init__(self, ttl: float, fn):
        self.ttl, self.fn, self.t, self.v, self.lock = ttl, fn, 0.0, None, threading.Lock()

    def get(self):
        with self.lock:
            if time.time() - self.t > self.ttl:
                try:
                    self.v = {"ok": True, "data": self.fn(), "fetched_at": time.time()}
                except Exception as e:  # noqa: BLE001 - se muestra en el dashboard
                    self.v = {"ok": False, "error": str(e)[:200], "fetched_at": time.time()}
                self.t = time.time()
            return self.v


# --------------------------------------------------------------------------- servidor
_cpu_prev = None


def host_stats() -> dict:
    global _cpu_prev
    with open("/proc/stat") as f:
        vals = list(map(int, f.readline().split()[1:]))
    idle, total = vals[3] + vals[4], sum(vals)
    cpu = None
    if _cpu_prev:
        dt, di = total - _cpu_prev[1], idle - _cpu_prev[0]
        cpu = round(100 * (1 - di / dt), 1) if dt else 0.0
    _cpu_prev = (idle, total)
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":")
            mem[k] = int(v.split()[0]) * 1024
    proc = {}
    with open("/proc/self/status") as f:
        for line in f:
            k, _, v = line.partition(":")
            proc[k] = v.strip()
    du = shutil.disk_usage("/tmp")
    return {
        "cpu_pct": cpu, "cores": os.cpu_count(), "load": os.getloadavg(),
        "mem_total": mem["MemTotal"], "mem_used": mem["MemTotal"] - mem["MemAvailable"],
        "proc_rss": int(proc.get("VmRSS", "0 kB").split()[0]) * 1024, "proc_threads": int(proc.get("Threads", 0)),
        "tmp_total": du.total, "tmp_used": du.used,
    }


# --------------------------------------------------------------------------- ComfyUI
_comfy_conn: tuple[str, str] | None = None


def _comfy() -> tuple[str, str]:
    global _comfy_conn
    if _comfy_conn is None:
        url = os.environ.get("COMFY_URL")
        token = os.environ.get("COMFY_AGENT_TOKEN")
        if not (url and token):
            cfn = boto3.client("cloudformation", region_name="us-east-2")
            outs = {o["OutputKey"]: o["OutputValue"] for s in cfn.describe_stacks()["Stacks"] for o in s.get("Outputs", [])}
            url = url or outs["AgentUrl"]
            token = token or boto3.client("secretsmanager", region_name="us-east-2").get_secret_value(
                SecretId=outs["AgentTokenSecret"])["SecretString"]
        _comfy_conn = (url.rstrip("/"), token)
    return _comfy_conn


def comfy_stats() -> dict:
    url, token = _comfy()

    def get(path):
        req = urllib.request.Request(f"{url}{path}", headers={"Authorization": f"Bearer {token}"})
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=4) as r:
            return json.loads(r.read()), (time.perf_counter() - t0) * 1000

    stats, ping = get("/system_stats")
    queue, _ = get("/queue")
    sysd = stats.get("system", {})
    return {
        "devices": [{"name": d.get("name"), "vram_total": d.get("vram_total"), "vram_free": d.get("vram_free")}
                    for d in stats.get("devices", [])],
        "ram_total": sysd.get("ram_total"), "ram_free": sysd.get("ram_free"),
        "version": sysd.get("comfyui_version"),
        "queue_running": len(queue.get("queue_running", [])), "queue_pending": len(queue.get("queue_pending", [])),
        "ping_ms": round(ping),
    }


# --------------------------------------------------------------------------- CloudWatch
CW_METRICS = [("Invocations", "Sum"), ("InputTokenCount", "Sum"), ("OutputTokenCount", "Sum"),
              ("InvocationLatency", "Average"), ("InvocationThrottles", "Sum"),
              ("InvocationClientErrors", "Sum"), ("InvocationServerErrors", "Sum")]


def cloudwatch_stats(minutes: int = 60) -> dict:
    cw = boto3.client("cloudwatch", region_name="us-east-1")
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(minutes=minutes)
    queries, index = [], {}
    for mi, model in enumerate(PRICES):
        for ki, (metric, stat) in enumerate(CW_METRICS):
            qid = f"m{mi}_{ki}"
            index[qid] = (model, metric)
            queries.append({"Id": qid, "ReturnData": True, "MetricStat": {
                "Metric": {"Namespace": "AWS/Bedrock", "MetricName": metric,
                           "Dimensions": [{"Name": "ModelId", "Value": model}]},
                "Period": 60, "Stat": stat}})
    res = cw.get_metric_data(MetricDataQueries=queries, StartTime=start, EndTime=end)["MetricDataResults"]
    out: dict[str, dict] = {m: {"model": m, **label(m), "per_min": {}} for m in PRICES}
    for r in res:
        model, metric = index[r["Id"]]
        pts = dict(zip((t.isoformat() for t in r["Timestamps"]), r["Values"]))
        o = out[model]
        if metric == "InvocationLatency":
            o["latency_avg_ms"] = round(sum(pts.values()) / len(pts)) if pts else None
        else:
            o[metric] = int(sum(pts.values()))
        if metric == "Invocations":
            o["per_min"] = pts
    for o in out.values():
        o["cost"] = cost_of(o["model"], o.get("InputTokenCount", 0), o.get("OutputTokenCount", 0))
        # serie por minuto, ordenada y con huecos a cero
        o["per_min"] = [o["per_min"].get((start + timedelta(minutes=i)).isoformat(), 0) for i in range(minutes)]
    return {"minutes": minutes, "start": start.isoformat(), "end": end.isoformat(), "models": list(out.values())}
