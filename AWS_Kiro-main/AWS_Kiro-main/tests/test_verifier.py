from __future__ import annotations

import json

import pytest

from brand_verifier import verifier
from brand_verifier.models import Verdict, VerifyError

from .conftest import FakeBedrock, make_refs, png_bytes, verdict_response


class FakeS3:
    def __init__(self):
        self.puts = {}

    def put(self, key, data, asset_id=None, content_type=None):
        self.puts[key] = data


@pytest.fixture
def refs(tmp_path):
    return make_refs(tmp_path / "brand")


def test_request_has_sample_and_both_logos(refs):
    client = FakeBedrock()
    res = verifier.verify_image(png_bytes(), "a1", client=client, ref_dir=refs)
    assert isinstance(res, Verdict)
    req = client.requests[0]
    content = req["messages"][0]["content"]
    images = [c["image"] for c in content if "image" in c]
    assert len(images) == 3
    texts = " ".join(c.get("text", "") for c in content)
    assert "CORRECTA" in texts and "INCORRECTA" in texts and "MUESTRA" in texts
    assert images[0]["format"] == "webp" and images[1]["format"] == "webp"
    assert images[2]["source"]["bytes"] == png_bytes()
    assert "ayesa" in req["system"][0]["text"].lower()


def test_model_id_from_env(refs, monkeypatch):
    monkeypatch.setenv("BRAND_MODEL_ID", "my-model")
    client = FakeBedrock()
    verifier.verify_image(png_bytes(), "a1", client=client, ref_dir=refs)
    assert client.requests[0]["modelId"] == "my-model"


def test_one_failure_retries(refs):
    client = FakeBedrock([RuntimeError("boom")], default=verdict_response("CORRECTO"))
    res = verifier.verify_image(png_bytes(), "a1", client=client, ref_dir=refs)
    assert isinstance(res, Verdict) and res.veredicto == "CORRECTO"
    assert len(client.requests) == 2


def test_two_failures_error(refs):
    client = FakeBedrock([RuntimeError("x"), verdict_response(text="no json")],
                         default=verdict_response(text="no json"))
    s3 = FakeS3()
    res = verifier.verify_image(png_bytes(), "a1", client=client, ref_dir=refs, s3=s3)
    assert isinstance(res, VerifyError)
    assert not hasattr(res, "veredicto")
    assert len(client.requests) == 2
    assert s3.puts == {}


def test_invalid_schema_is_failure(refs):
    bad = verdict_response(text=json.dumps({"veredicto": "CORRECTO", "confianza": 2}))
    client = FakeBedrock([bad, bad])
    assert isinstance(verifier.verify_image(png_bytes(), "a1", client=client, ref_dir=refs), VerifyError)


def test_valid_verdict_saved_to_s3(refs):
    s3 = FakeS3()
    res = verifier.verify_image(png_bytes(), "a1", client=FakeBedrock(), ref_dir=refs, s3=s3)
    assert json.loads(s3.puts["brand/verdicts/a1.json"])["veredicto"] == res.veredicto


def test_invalid_asset_id(refs):
    client = FakeBedrock()
    assert isinstance(verifier.verify_image(png_bytes(), "../x", client=client, ref_dir=refs), VerifyError)
    assert client.requests == []


def test_fenced_json_accepted(refs):
    text = "```json\n" + json.dumps(json.loads(
        verdict_response("SIN_LOGO")["output"]["message"]["content"][0]["text"])) + "\n```"
    res = verifier.verify_image(png_bytes(), "a1", client=FakeBedrock([verdict_response(text=text)]),
                                ref_dir=refs)
    assert res.veredicto == "SIN_LOGO"


def test_video_unreadable_is_error(refs, tmp_path):
    def bad(path):
        raise ValueError("corrupto")

    client = FakeBedrock()
    res = verifier.verify_video(tmp_path / "x.mp4", "v1", client=client, extractor=bad, ref_dir=refs)
    assert isinstance(res, VerifyError)
    assert client.requests == []


def test_video_missing_file_default_extractor(refs, tmp_path):
    res = verifier.verify_video(tmp_path / "nope.mp4", "v1", client=FakeBedrock(), ref_dir=refs)
    assert isinstance(res, VerifyError)


def test_video_aggregates_and_timestamps(refs, tmp_path):
    frames = [(0, png_bytes()), (1, png_bytes()), (2, png_bytes())]
    client = FakeBedrock([verdict_response("CORRECTO"), verdict_response("INCORRECTO"),
                          verdict_response("CORRECTO")])
    s3 = FakeS3()
    res = verifier.verify_video(tmp_path / "v.mp4", "v1", client=client, ref_dir=refs, s3=s3,
                                extractor=lambda p: frames)
    assert res.veredicto == "INCORRECTO"
    assert [e.timestamp_s for e in res.evidencias if e.logo_detectado == "INCORRECTO"] == [1]
    assert any(e.timestamp_s == 0 for e in res.evidencias)
    assert "brand/verdicts/v1.json" in s3.puts
    assert len(client.requests) == 3


def test_video_frame_failure_is_error(refs, tmp_path):
    client = FakeBedrock(default=RuntimeError("x"))
    res = verifier.verify_video(tmp_path / "v.mp4", "v1", client=client, ref_dir=refs,
                                extractor=lambda p: [(0, png_bytes())])
    assert isinstance(res, VerifyError)


def test_pegasus_does_not_alter_verdict(refs, tmp_path):
    frames = [(0, png_bytes()), (1, png_bytes())]
    kw = dict(ref_dir=refs, extractor=lambda p: frames)
    base = verifier.verify_video(tmp_path / "v.mp4", "v1", client=FakeBedrock(default=verdict_response("CORRECTO")), **kw)
    extras = {}
    with_p = verifier.verify_video(tmp_path / "v.mp4", "v1", client=FakeBedrock(default=verdict_response("CORRECTO")),
                                   pegasus=lambda p, i: {"resumen": "INCORRECTO"}, extras=extras, **kw)
    assert with_p == base
    assert extras["complementario"] == {"resumen": "INCORRECTO"}
    boom = verifier.verify_video(tmp_path / "v.mp4", "v1", client=FakeBedrock(default=verdict_response("CORRECTO")),
                                 pegasus=lambda p, i: 1 / 0, **kw)
    assert boom == base


def test_cv2_extractor_real_video(refs, tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    path = str(tmp_path / "v.avi")
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 5, (64, 64))
    for _ in range(15):
        w.write(np.zeros((64, 64, 3), dtype="uint8"))
    w.release()
    frames = verifier.extract_frames_cv2(path)
    assert [t for t, _ in frames] == [0, 1, 2]
