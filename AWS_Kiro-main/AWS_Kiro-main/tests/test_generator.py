"""Tests unitarios del Generador_ComfyUI con run_workflow falso (sin red ni AWS).

Validates: Requirements 5.4, 5.5, 6.1
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from brand_verifier import generator as gen
from brand_verifier import manifest as mf

FAKE_TOKEN = "tok-" + "x" * 24  # valor ficticio generado en el test


class FakeClient:
    """Sustituye a comfyui/client.py: usa el apply_overrides real, red simulada."""

    def __init__(self, fail_on=None, timeout_on=None):
        self.real = gen.load_comfy_client()
        self.calls = []        # (slug-like, overrides) en orden
        self.uploads = []
        self.active = 0
        self.max_active = 0
        self.fail_on = fail_on or (lambda graph, n: False)
        self.timeout_on = timeout_on or (lambda graph, n: False)
        self.timeouts_seen = []
        self.lock = threading.Lock()

    def apply_overrides(self, graph, inputs, overrides):
        return self.real.apply_overrides(graph, inputs, overrides)

    def upload_image(self, base_url, path, token=None):
        self.uploads.append(Path(path).name)
        return "up-" + Path(path).name

    def run_workflow(self, base_url, api_graph, timeout_s=1800, out_dir=Path("."),
                     poll_s=2.0, token=None):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            n = len(self.calls)
            self.calls.append(api_graph)
            self.timeouts_seen.append(timeout_s)
            assert token == FAKE_TOKEN
            if self.timeout_on(api_graph, n):
                raise TimeoutError("still running")
            if self.fail_on(api_graph, n):
                raise RuntimeError("workflow failed: boom")
            out_dir.mkdir(parents=True, exist_ok=True)
            is_video = any(v["class_type"] == "SaveVideo" for v in api_graph.values())
            f = out_dir / ("out%d.%s" % (n, "mp4" if is_video else "png"))
            f.write_bytes(b"data")
            return [f]
        finally:
            with self.lock:
                self.active -= 1


class FakeS3:
    def __init__(self):
        self.puts = []

    def put(self, key, data, asset_id=None, content_type=None):
        self.puts.append((key, asset_id, content_type))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    assets = tmp_path / "brand"
    assets.mkdir()
    for name in ("logo-ayesa-boletin.webp", "logo-vector_ayesa.webp"):
        (assets / name).write_bytes(b"webp")
    monkeypatch.setattr(gen, "ASSETS_DIR", assets)
    return tmp_path


def run(plan, env, client, **kw):
    statuses, interrupts, probes, concats = [], [], [], []

    def concat(paths, out):
        concats.append([Path(p).name for p in paths])
        Path(out).write_bytes(b"mixed")
        return Path(out)

    manifest = mf.new_manifest()
    s3 = FakeS3()
    gen.generate_dataset(
        plan, manifest, s3, base_url="http://comfy.invalid", token=FAKE_TOKEN, client=client,
        workdir=env / "work", status=statuses.append,
        probe_fn=lambda u, t: probes.append(u),
        interrupt_fn=lambda u, t: interrupts.append(u),
        concat_fn=concat, **kw)
    return manifest, s3, statuses, interrupts, probes, concats


def test_default_plan_counts_and_ids():
    plan = gen.default_plan()
    assert len(plan) >= 12
    count = lambda tipo, lab: sum(1 for s in plan if s.tipo == tipo and s.etiqueta_esperada == lab)
    assert (count("imagen", "CORRECTO"), count("imagen", "INCORRECTO"), count("imagen", "SIN_LOGO")) == (3, 3, 1)
    assert (count("video", "CORRECTO"), count("video", "INCORRECTO"), count("video", "SIN_LOGO")) == (2, 2, 1)
    assert len({s.id for s in plan}) == len(plan)
    assert any(s.variant == "atm" for s in plan)
    mixed = [s for s in plan if s.variant == "mixed"]
    assert len(mixed) == 1 and mixed[0].etiqueta_esperada == "INCORRECTO"
    assert mixed[0].segments == ("INCORRECTO", "CORRECTO")


def test_atm_prompt_has_no_digits_or_banks():
    atm = next(s for s in gen.default_plan() if s.variant == "atm")
    assert not any(c.isdigit() for c in atm.prompt)
    assert "banco" not in atm.prompt.lower() and "bank" not in atm.prompt.lower()


def test_video_overrides_use_minimum_settings_for_3_to_10_seconds():
    over = gen.video_overrides()
    assert (over["width"], over["height"]) == (832, 480)
    seconds = over["frames"] / 16.0
    assert 3 <= seconds <= 10 and (over["frames"] - 1) % 4 == 0


def test_timeout_marks_failure_interrupts_and_continues(env):
    plan = [gen.AssetSpec("img-a", "imagen", "CORRECTO", "p"),
            gen.AssetSpec("img-b", "imagen", "SIN_LOGO", "p")]
    client = FakeClient(timeout_on=lambda g, n: n == 0)
    manifest, s3, statuses, interrupts, _, _ = run(plan, env, client)
    a, b = manifest["assets"]
    assert a["estado"] == "GENERACION_FALLIDA" and "timeout" in a["motivo"]
    assert b["estado"] == "GENERADO" and b["s3_key"] == "brand/generated/img-b/output.png"
    assert interrupts == ["http://comfy.invalid"]       # cancelacion /interrupt
    assert len(client.calls) == 2                       # sin reintentos
    assert set(client.timeouts_seen) == {900}
    assert [p[0] for p in s3.puts if "/metrics/" not in p[0]] == ["brand/generated/img-b/output.png"]
    assert FAKE_TOKEN not in json.dumps(manifest)
    assert any("img-a: fallido" in s for s in statuses)


def test_generic_failure_not_retried_and_continues(env):
    plan = [gen.AssetSpec("img-a", "imagen", "CORRECTO", "p"),
            gen.AssetSpec("img-b", "imagen", "INCORRECTO", "p")]
    client = FakeClient(fail_on=lambda g, n: n == 0)
    manifest, _, _, interrupts, _, _ = run(plan, env, client)
    assert [a["estado"] for a in manifest["assets"]] == ["GENERACION_FALLIDA", "GENERADO"]
    assert interrupts == []
    assert len(client.calls) == 2


def test_probe_failure_marks_failed_and_continues(env):
    plan = [gen.AssetSpec("img-a", "imagen", "SIN_LOGO", "p"),
            gen.AssetSpec("img-b", "imagen", "SIN_LOGO", "p")]
    client = FakeClient()
    manifest = mf.new_manifest()
    n = {"i": 0}

    def probe(u, t):
        n["i"] += 1
        if n["i"] == 1:
            raise gen.GenerationError("AgentUrl no responde en 10s")

    gen.generate_dataset(plan, manifest, None, base_url="http://x.invalid", token=FAKE_TOKEN,
                         client=client, workdir=env / "w", status=lambda s: None, probe_fn=probe)
    assert [a["estado"] for a in manifest["assets"]] == ["GENERACION_FALLIDA", "GENERADO"]
    assert len(client.calls) == 1


def test_sequential_execution_single_job_in_flight(env):
    client = FakeClient()
    run(gen.default_plan(), env, client)
    assert client.max_active == 1
    assert len(client.calls) > 12


def test_status_sequence_and_limit_only(env):
    plan = gen.default_plan()
    _, _, statuses, _, _, _ = run(plan, env, FakeClient(), only=["img-correcto-02", "img-sinlogo-01"],
                                  limit=1)
    ids = {s.split(":")[0] for s in statuses}
    assert ids == {"img-correcto-02"}
    for state in ("en cola", "en curso", "completado"):
        assert any(s.endswith(state) for s in statuses)


def test_logo_is_uploaded_only_for_expected_brand(env):
    client = FakeClient()
    plan = [gen.AssetSpec("i1", "imagen", "CORRECTO", "p"),
            gen.AssetSpec("i2", "imagen", "INCORRECTO", "p"),
            gen.AssetSpec("i3", "imagen", "SIN_LOGO", "p")]
    run(plan, env, client)
    assert client.uploads == ["logo-ayesa-boletin.webp", "logo-vector_ayesa.webp"]


def test_video_is_still_then_clip_and_mixed_is_concatenated(env):
    client = FakeClient()
    plan = [gen.AssetSpec("vid-mixto", "video", "INCORRECTO", "p", variant="mixed",
                          segments=("INCORRECTO", "CORRECTO"))]
    manifest, s3, _, _, _, concats = run(plan, env, client)
    classes = [{v["class_type"] for v in g.values()} & {"SaveImage", "SaveVideo"} for g in client.calls]
    assert classes == [{"SaveImage"}, {"SaveVideo"}] * 2
    assert client.uploads[0] == "logo-vector_ayesa.webp"
    assert "logo-ayesa-boletin.webp" in client.uploads
    assert len(concats) == 1 and len(concats[0]) == 2
    asset = manifest["assets"][0]
    assert asset["estado"] == "GENERADO" and asset["flujo"] == "image-to-video"
    assert asset["etiqueta_validada"] is False
    assert s3.puts[0][0] == "brand/generated/vid-mixto/output.mp4"


def test_no_nova_reel_anywhere():
    import ast
    tree = ast.parse(Path(gen.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert "boto3" not in imported and "botocore" not in imported
    src = Path(gen.__file__).read_text(encoding="utf-8").lower()
    for forbidden in ("bedrock-runtime", "invoke_model", "start_async_invoke", "amazon.nova-reel"):
        assert forbidden not in src
    flows = {s.flujo for s in gen.default_plan()}
    assert flows <= {"product-shot", "image-to-video"}
    assert (gen.WORKFLOWS_DIR / "product-shot.json").is_file()
    assert (gen.WORKFLOWS_DIR / "image-to-video.json").is_file()


def test_concat_videos_opencv_fallback(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    from brand_verifier import generator as g
    monkeypatch.setattr(g.shutil, "which", lambda name: None)

    def mk(name, size, color, n=5):
        p = tmp_path / name
        w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, size)
        for _ in range(n):
            w.write(np.full((size[1], size[0], 3), color, dtype=np.uint8))
        w.release()
        return p

    a, b = mk("a.mp4", (64, 48), 50), mk("b.mp4", (32, 24), 200, 3)
    out = g.concat_videos([a, b], tmp_path / "out.mp4")
    cap = cv2.VideoCapture(str(out))
    assert (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))) == (64, 48)
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 8
    cap.release()
