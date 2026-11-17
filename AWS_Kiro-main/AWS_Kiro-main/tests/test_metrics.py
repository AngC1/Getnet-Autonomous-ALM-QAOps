"""Metricas (brand/metrics/*) y regresion AMBIGUO en evidencias. Todo con fakes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from brand_verifier import cli, core, generator as gen, incident, manifest as mf
from brand_verifier import metrics, narration, references, verifier
from brand_verifier.models import validate_verdict
from tests.conftest import FakeBedrock, make_refs, png_bytes, verdict_response
from tests.test_generator import FAKE_TOKEN, FakeClient, env, run  # noqa: F401


class MemS3:
    bucket = "mem"

    def __init__(self):
        self.objs = {}

    def put(self, key, data, asset_id=None, content_type=None):
        self.objs[key] = bytes(data) if not isinstance(data, str) else Path(data).read_bytes()

    def get(self, key, asset_id=None):
        return self.objs[key]

    def exists(self, key, asset_id=None):
        return key in self.objs

    def json(self, key):
        return json.loads(self.objs[key].decode("utf-8"))


def with_usage(resp, i=100, o=20, ms=300):
    resp = dict(resp)
    resp["usage"] = {"inputTokens": i, "outputTokens": o, "totalTokens": i + o}
    resp["metrics"] = {"latencyMs": ms}
    return resp


def ambiguous_logo_response(veredicto):
    text = json.dumps({
        "veredicto": veredicto, "confianza": 0.5,
        "evidencias": [{"timestamp_s": 0, "bbox": [0.1, 0.1, 0.5, 0.5], "logo_detectado": "AMBIGUO"}],
        "recomendacion": "Sustituir el logotipo por Ayesa Digital."})
    return verdict_response(text=text)


# ---------------------------------------------------------------- AMBIGUO
def test_normalize_drops_ambiguous_evidence_and_downgrades():
    raw = json.loads(ambiguous_logo_response("INCORRECTO")["output"]["message"]["content"][0]["text"])
    norm = core.normalize_model_output(raw)
    assert norm["evidencias"] == [] and norm["veredicto"] == "AMBIGUO"
    assert validate_verdict(norm) == []


def test_normalize_keeps_valid_evidence_next_to_ambiguous():
    good = {"timestamp_s": 1, "bbox": [0.1, 0.1, 0.5, 0.5], "logo_detectado": "INCORRECTO"}
    bad = dict(good, logo_detectado="AMBIGUO")
    norm = core.normalize_model_output({"veredicto": "INCORRECTO", "confianza": 0.8,
                                        "evidencias": [bad, good], "recomendacion": "Ayesa Digital"})
    assert norm["evidencias"] == [good] and norm["veredicto"] == "INCORRECTO"
    assert validate_verdict(norm) == []


def test_unknown_logo_value_is_still_rejected():
    ev = {"timestamp_s": 0, "bbox": [0.1, 0.1, 0.5, 0.5], "logo_detectado": "otro"}
    norm = core.normalize_model_output({"veredicto": "CORRECTO", "confianza": 0.8,
                                        "evidencias": [ev], "recomendacion": "ok"})
    assert validate_verdict(norm) != []


def test_prompt_restricts_logo_detectado():
    assert "SOLO puede ser CORRECTO o INCORRECTO" in verifier.SYSTEM_PROMPT


@pytest.mark.parametrize("label", ["CORRECTO", "INCORRECTO", "AMBIGUO"])
def test_regression_ambiguous_frame_does_not_fail_video(tmp_path, label):
    refs = make_refs(tmp_path / "refs")
    client = FakeBedrock(default=ambiguous_logo_response(label))
    res = verifier.verify_video("x.mp4", "vid-x", client=client, ref_dir=refs,
                                extractor=lambda p: [(0, png_bytes()), (1, png_bytes())])
    assert not hasattr(res, "motivo")
    assert res.veredicto == "AMBIGUO" and len(client.requests) == 2  # sin reintentos


# ---------------------------------------------------------------- por activo
def test_usage_sums_all_attempts_and_frames(tmp_path):
    refs = make_refs(tmp_path / "refs")
    bad = with_usage(verdict_response(text="no json"), 10, 1, 5)
    ok = with_usage(verdict_response("CORRECTO"), 100, 20, 300)
    client = FakeBedrock(script=[bad, ok, ok])
    st = metrics.UsageStats("vid-1", "video", "m", "us-east-1")
    res = verifier.verify_video("x.mp4", "vid-1", client=client, ref_dir=refs, stats=st,
                                extractor=lambda p: [(0, png_bytes()), (1, png_bytes())])
    assert res.veredicto == "CORRECTO"
    d = st.to_dict(res.veredicto)
    assert (d["calls"], d["frames"]) == (3, 2)
    assert (d["input_tokens"], d["output_tokens"], d["total_tokens"]) == (210, 41, 251)
    assert d["latency_ms"] == 605 and d["veredicto"] == "CORRECTO"


def test_asset_metrics_file_contract():
    s3 = MemS3()
    st = metrics.UsageStats("img-1", "imagen", "model-x")
    st.add_response(with_usage({}, 7, 3, 11))
    metrics.write_asset(s3, None, st, "SIN_LOGO")
    d = s3.json("brand/metrics/img-1.json")
    assert set(d) == {"id", "tipo", "model_id", "region", "calls", "frames", "input_tokens",
                      "output_tokens", "total_tokens", "latency_ms", "started_at", "finished_at",
                      "veredicto"}
    assert d["region"] == "us-east-1" and d["total_tokens"] == 10
    assert d["started_at"].endswith("Z") and d["finished_at"].endswith("Z")


def _setup_run(tmp_path, monkeypatch, assets):
    refs = make_refs(tmp_path / "refs")
    monkeypatch.setattr(references, "check_local_refs", lambda d: {})
    monkeypatch.setattr(references, "sync_refs_to_s3", lambda *a, **k: [])
    (tmp_path / "generated").mkdir(parents=True, exist_ok=True)
    (tmp_path / "generated" / "manifest.json").write_text(json.dumps({"assets": assets}))
    for a in assets:
        f = tmp_path / a["s3_key"][len("brand/"):]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(png_bytes())
    return refs


def _asset(i):
    return {"id": i, "tipo": "imagen", "flujo": "x", "ajustes": {}, "etiqueta_esperada": "CORRECTO",
            "etiqueta_validada": True, "estado": "GENERADO", "motivo": None,
            "s3_key": "brand/generated/%s/output.png" % i}


def test_run_writes_asset_run_and_runs_metrics(tmp_path, monkeypatch):
    refs = _setup_run(tmp_path, monkeypatch, [_asset("img-a"), _asset("img-b")])
    client = FakeBedrock(default=with_usage(verdict_response("CORRECTO"), 100, 20, 50))
    monkeypatch.setattr(cli, "_bedrock_client", lambda: client)
    monkeypatch.setenv("BRAND_MODEL_ID", "model-test")
    args = ["run", "--no-s3", "--skip-generation", "--out-dir", str(tmp_path), "--refs-dir", str(refs)]
    assert cli.main(args) == 0
    a = json.loads((tmp_path / "metrics" / "img-a.json").read_text())
    assert a["total_tokens"] == 120 and a["model_id"] == "model-test" and a["veredicto"] == "CORRECTO"
    run_ = json.loads((tmp_path / "metrics" / "run.json").read_text())
    assert run_["assets_verified"] == 2 and run_["total_tokens"] == 240
    assert run_["region"] == "us-east-1" and run_["model_id"] == "model-test"
    assert [s["name"] for s in run_["stages"]] == ["referencias", "generacion", "verificacion", "informe"]
    assert {s["status"] for s in run_["stages"]} >= {"completada", "omitida"}
    assert all(set(s) == {"name", "status", "seconds"} for s in run_["stages"])
    assert len(json.loads((tmp_path / "metrics" / "runs.json").read_text())) == 1
    mj = json.loads((tmp_path / "metrics" / "models.json").read_text())
    assert mj["model-test"] == {"service": "Amazon Bedrock Converse (visión)", "calls": 2,
                                "input_tokens": 200, "output_tokens": 40}


def test_runs_json_keeps_last_50():
    s3 = MemS3()
    for n in range(55):
        metrics.write_run(s3, None, {"run_id": str(n)})
    runs = s3.json("brand/metrics/runs.json")
    assert len(runs) == 50 and runs[0]["run_id"] == "5" and runs[-1]["run_id"] == "54"
    assert s3.json("brand/metrics/run.json")["run_id"] == "54"


# ---------------------------------------------------------------- ComfyUI
def test_comfyui_metrics_written_and_merged(env):  # noqa: F811
    plan = [gen.AssetSpec("img-a", "imagen", "CORRECTO", "p")]
    s3 = MemS3()
    for _ in range(2):  # segunda ejecucion: merge por (id, step), no duplica
        gen.generate_dataset(plan, mf.new_manifest(), s3, base_url="http://comfy.invalid:8188/x",
                             token=FAKE_TOKEN, client=FakeClient(), workdir=env / "w",
                             status=lambda m: None, probe_fn=lambda u, t: None,
                             interrupt_fn=lambda u, t: None, metrics_dir=str(env / "m"))
    d = s3.json("brand/metrics/comfyui.json")
    assert d["agent_url_host"] == "comfy.invalid" and FAKE_TOKEN not in json.dumps(d)
    assert len(d["jobs"]) == 1
    job = d["jobs"][0]
    assert set(job) == {"id", "step", "workflow", "status", "seconds", "started_at"}
    assert job["id"] == "img-a" and job["status"] == "completed"
    assert (env / "m" / "metrics" / "comfyui.json").is_file()


def test_comfyui_merge_keeps_previous_jobs():
    s3 = MemS3()
    j = lambda i, st: {"id": i, "step": "imagen", "workflow": "w", "status": st, "seconds": 1, "started_at": "t"}
    metrics.merge_comfyui(s3, None, "h", [j("a", "failed"), j("b", "completed")])
    d = metrics.merge_comfyui(s3, None, "h", [j("a", "completed")])
    by = {x["id"]: x["status"] for x in d["jobs"]}
    assert by == {"a": "completed", "b": "completed"}


def test_timeout_job_recorded(env):  # noqa: F811
    plan = [gen.AssetSpec("img-a", "imagen", "CORRECTO", "p")]
    client = FakeClient(timeout_on=lambda g, n: True)
    s3 = MemS3()
    gen.generate_dataset(plan, mf.new_manifest(), s3, base_url="http://h", token=FAKE_TOKEN,
                         client=client, workdir=env / "w", status=lambda m: None,
                         probe_fn=lambda u, t: None, interrupt_fn=lambda u, t: None)
    assert s3.json("brand/metrics/comfyui.json")["jobs"][0]["status"] == "timeout"


# ---------------------------------------------------------------- models.json
def test_triage_usage_accumulates_in_models_json():
    s3 = MemS3()
    triage = json.dumps({"categoria": "x", "prioridad": "alta", "resumen": "r", "accion_sugerida": "a"})
    resp = with_usage(verdict_response(text=triage), 50, 10)
    client = FakeBedrock(default=resp)
    obj = {"descripcion": "tarjeta retenida", "atm_id": "ATM-1", "ubicacion": "Sevilla",
           "fecha_hora": "2025-01-01T10:00:00Z"}
    for _ in range(2):
        r = incident.process_incident(obj, s3, client, model_id="text-model")
        assert r.ok
    m = s3.json("brand/metrics/models.json")["text-model"]
    if r.estado == incident.ESTADO_TRIAJE_OK:
        assert m == {"service": metrics.SVC_TEXT, "calls": 2, "input_tokens": 100, "output_tokens": 20}


def test_stable_audio_call_recorded(monkeypatch):
    metrics_s3 = MemS3()
    monkeypatch.setattr(narration, "generate_audio", lambda *a, **k: b"mp3")
    monkeypatch.setattr(narration, "ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(narration, "probe_duration", lambda v, e=None: 5.0)
    monkeypatch.setattr(narration, "mux", lambda v, a, o, e=None: Path(o).write_bytes(b"mp4"))
    metrics_s3.put("brand/generated/vid-1/output.mp4", b"v")
    metrics_s3.put("brand/verdicts/vid-1.json", b'{"veredicto": "CORRECTO"}')
    man = {"assets": [{"id": "vid-1", "tipo": "video", "s3_key": "brand/generated/vid-1/output.mp4",
                       "estado": "GENERADO"}]}
    narration.narrate_all(man, metrics_s3, "k" * 12)
    m = metrics_s3.json("brand/metrics/models.json")[narration.MODEL]
    assert m["service"] == "Stability AI Stable Audio" and m["calls"] == 1
