from __future__ import annotations

import json
import logging

import pytest

from brand_verifier import narration, secrets as secrets_mod

KEY = "sk-SUPERSECRETO-1234567890"  # nosecret: valor ficticio de test


class FakeS3:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.puts = []

    def get(self, key, asset_id=None):
        if key not in self.objects:
            raise KeyError(key)
        return self.objects[key]

    def put(self, key, data, asset_id=None, content_type=None):
        self.objects[key] = data
        self.puts.append(key)


def _manifest(*ids):
    return {"assets": [{"id": i, "tipo": "video", "estado": "GENERADO",
                        "s3_key": "brand/generated/%s/output.mp4" % i} for i in ids]}


def _s3(verdicts):
    objs = {}
    for aid, label in verdicts.items():
        objs["brand/generated/%s/output.mp4" % aid] = b"VIDEO"
        if label:
            objs["brand/verdicts/%s.json" % aid] = json.dumps({"veredicto": label}).encode()
    return FakeS3(objs)


@pytest.fixture(autouse=True)
def _patch_ffmpeg(monkeypatch):
    secrets_mod.clear_registered_secrets()
    monkeypatch.setattr(narration, "ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(narration, "probe_duration", lambda video, exe=None: 2.6)

    def fake_mux(video, audio, out, exe=None):
        out.write_bytes(b"MUXED" + audio.read_bytes())

    monkeypatch.setattr(narration, "mux", fake_mux)
    yield
    secrets_mod.clear_registered_secrets()


def test_prompts_by_verdict():
    assert "jingle" in narration.prompt_for("CORRECTO")
    assert "alert" in narration.prompt_for("INCORRECTO")
    assert narration.prompt_for("SIN_LOGO") == narration.NEUTRAL_PROMPT
    assert narration.prompt_for("AMBIGUO") == narration.NEUTRAL_PROMPT


def test_target_duration():
    assert narration.target_duration(None) == narration.FALLBACK_DURATION_S
    assert narration.target_duration(2.6) == 3
    assert narration.target_duration(0.2) == 1
    assert narration.target_duration(60) == narration.MAX_DURATION_S


def test_generate_audio_request_shape():
    calls = []

    def post(url, headers, fields, timeout):
        calls.append((url, headers, fields, timeout))
        return 200, b"MP3"

    assert narration.generate_audio("hola", 3, KEY, post) == b"MP3"
    url, headers, fields, timeout = calls[0]
    assert url == narration.ENDPOINT
    assert headers["Authorization"] == "Bearer " + KEY
    assert fields["prompt"] == "hola" and fields["duration"] == "3"
    assert fields["output_format"] == "mp3" and fields["model"] == narration.MODEL
    assert timeout > 0


def test_narrate_all_writes_artifacts_and_index():
    s3 = _s3({"v1": "CORRECTO", "v2": "INCORRECTO", "v3": "SIN_LOGO", "v4": None})
    prompts = {}

    def post(url, headers, fields, timeout):
        prompts[fields["prompt"]] = fields["duration"]
        return 200, b"MP3DATA"

    index = narration.narrate_all(_manifest("v1", "v2", "v3", "v4"), s3, KEY, post=post)
    assert set(index) == {"v1", "v2", "v3"}  # v4 sin veredicto
    assert index["v1"]["audio_key"] == "brand/generated/v1/audio.mp3"
    assert index["v1"]["video_audio_key"] == "brand/generated/v1/output_audio.mp4"
    assert index["v2"]["veredicto"] == "INCORRECTO"
    assert index["v3"]["prompt"] == narration.NEUTRAL_PROMPT
    assert s3.objects["brand/generated/v1/audio.mp3"] == b"MP3DATA"
    assert s3.objects["brand/generated/v1/output_audio.mp4"].startswith(b"MUXED")
    assert set(prompts.values()) == {"3"}
    stored = json.loads(s3.objects[narration.INDEX_KEY])
    assert stored == index


def test_only_filter_and_index_merge():
    s3 = _s3({"v1": "CORRECTO", "v2": "CORRECTO"})
    s3.objects[narration.INDEX_KEY] = json.dumps({"old": {"audio_key": "x"}}).encode()
    index = narration.narrate_all(_manifest("v1", "v2"), s3, KEY, only=["v2"],
                                  post=lambda *a: (200, b"A"))
    assert set(index) == {"old", "v2"}


def test_jobs_run_one_at_a_time():
    s3 = _s3({"v1": "CORRECTO", "v2": "CORRECTO"})
    active = {"n": 0, "max": 0}

    def post(*a):
        active["n"] += 1
        active["max"] = max(active["max"], active["n"])
        active["n"] -= 1
        return 200, b"A"

    narration.narrate_all(_manifest("v1", "v2"), s3, KEY, post=post)
    assert active["max"] == 1


def test_failure_skips_asset_and_never_leaks_key(caplog):
    s3 = _s3({"v1": "CORRECTO", "v2": "CORRECTO"})
    n = {"i": 0}
    messages = []

    def post(url, headers, fields, timeout):
        n["i"] += 1
        if n["i"] == 1:  # el servidor devuelve la clave en el cuerpo del error
            return 401, ('{"error":"bad key %s"}' % KEY).encode()
        return 200, b"A"

    with caplog.at_level(logging.DEBUG):
        index = narration.narrate_all(_manifest("v1", "v2"), s3, KEY, post=post, status=messages.append)
    assert set(index) == {"v2"}
    everything = "\n".join(messages) + caplog.text
    assert KEY not in everything
    assert "401" in everything


def test_exceptions_do_not_contain_key():
    def boom(url, headers, fields, timeout):
        raise RuntimeError("connection failed with Bearer " + KEY)

    with pytest.raises(narration.NarrationError) as ei:
        narration.generate_audio("p", 3, KEY, boom)
    assert KEY not in str(ei.value) and KEY not in repr(ei.value)
    assert ei.value.__cause__ is None

    with pytest.raises(narration.NarrationError) as ei2:
        narration.generate_audio("p", 3, KEY, lambda *a: (500, ("oops " + KEY).encode()))
    assert KEY not in str(ei2.value)

    with pytest.raises(narration.NarrationError):
        narration.generate_audio("p", 3, KEY, lambda *a: (200, b""))


def test_secret_env_fallback(monkeypatch):
    class FakeCfn:
        def describe_stacks(self, **kw):
            return {"Stacks": []}

    secrets_mod.set_clients(cloudformation=FakeCfn())
    try:
        monkeypatch.delenv(narration.SECRET_NAME, raising=False)
        monkeypatch.setenv("STABILITY_API_KEY", KEY)
        assert secrets_mod.get_optional(narration.SECRET_NAME) == KEY
    finally:
        secrets_mod.set_clients()


def test_cli_narrate_registered():
    from brand_verifier import cli

    args = cli.build_parser().parse_args(["narrate", "--only", "a,b", "--no-s3"])
    assert args.only == "a,b" and args.no_s3 is True and args.func is cli.cmd_narrate
