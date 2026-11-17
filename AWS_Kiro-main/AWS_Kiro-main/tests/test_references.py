"""Tests unitarios del comprobador de referencias (sin AWS real)."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from brand_verifier.references import (
    LOGO_CORRECTO,
    LOGO_INCORRECTO,
    MAX_BYTES,
    S3_PREFIX,
    ReferenceCheckError,
    check_local_refs,
    sync_refs_to_s3,
)
from brand_verifier.s3io import S3IO


def _webp(path, size=(16, 16), color=(10, 120, 200)):
    Image.new("RGB", size, color).save(path, format="WEBP")
    return path


@pytest.fixture
def refs(tmp_path):
    _webp(tmp_path / LOGO_CORRECTO)
    _webp(tmp_path / LOGO_INCORRECTO, color=(200, 20, 20))
    return tmp_path


class FakeClient:
    def __init__(self, existing=()):
        self.store = {k: b"old" for k in existing}
        self.puts = []

    def head_object(self, Bucket, Key):
        if Key not in self.store:
            e = Exception("nf")
            e.response = {"Error": {"Code": "404"}}
            raise e
        return {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.store[Key] = Body
        self.puts.append((Bucket, Key, kw))

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.store[Key])}


def _s3(client, bucket="b"):
    return S3IO(client, bucket=bucket, sleep=lambda s: None)


# --- check_local_refs -------------------------------------------------------
def test_valid_refs_return_both_paths(refs):
    found = check_local_refs(refs)
    assert set(found) == {LOGO_CORRECTO, LOGO_INCORRECTO}
    assert all(p.is_file() for p in found.values())


def test_missing_reference_reports_path_and_reason(refs):
    (refs / LOGO_INCORRECTO).unlink()
    with pytest.raises(ReferenceCheckError) as ei:
        check_local_refs(refs)
    assert len(ei.value.problems) == 1
    assert LOGO_INCORRECTO in ei.value.problems[0]
    assert "falta" in ei.value.problems[0]


def test_all_missing_reports_every_problem(tmp_path):
    with pytest.raises(ReferenceCheckError) as ei:
        check_local_refs(tmp_path)
    assert len(ei.value.problems) == 2


def test_non_webp_png_rejected(refs):
    Image.new("RGB", (8, 8)).save(refs / LOGO_CORRECTO, format="PNG")
    with pytest.raises(ReferenceCheckError) as ei:
        check_local_refs(refs)
    assert LOGO_CORRECTO in str(ei.value) and "WebP" in str(ei.value)


def test_corrupt_file_rejected(refs):
    (refs / LOGO_CORRECTO).write_bytes(b"esto no es una imagen")
    with pytest.raises(ReferenceCheckError) as ei:
        check_local_refs(refs)
    assert "legible" in str(ei.value)


def test_truncated_webp_rejected(refs):
    data = (refs / LOGO_INCORRECTO).read_bytes()
    (refs / LOGO_INCORRECTO).write_bytes(data[: len(data) // 2])
    with pytest.raises(ReferenceCheckError):
        check_local_refs(refs)


def test_over_1mb_rejected_even_if_valid_webp(refs):
    import os

    big = refs / LOGO_CORRECTO
    # WebP sin perdida con ruido: incompresible, supera 1 MB
    Image.frombytes("RGB", (700, 700), os.urandom(700 * 700 * 3)).save(
        big, format="WEBP", lossless=True)
    assert big.stat().st_size > MAX_BYTES
    with pytest.raises(ReferenceCheckError) as ei:
        check_local_refs(refs)
    assert "1 MB" in str(ei.value) and LOGO_CORRECTO in str(ei.value)


def test_exactly_at_limit_is_accepted(refs, monkeypatch):
    size = (refs / LOGO_CORRECTO).stat().st_size
    monkeypatch.setattr("brand_verifier.references.MAX_BYTES", size)
    assert LOGO_CORRECTO in check_local_refs(refs)


# --- sync_refs_to_s3 --------------------------------------------------------
def test_uploads_both_when_absent(refs):
    c = FakeClient()
    uploaded = sync_refs_to_s3(_s3(c), directory=refs)
    assert sorted(uploaded) == sorted([S3_PREFIX + LOGO_CORRECTO, S3_PREFIX + LOGO_INCORRECTO])
    assert c.store[S3_PREFIX + LOGO_CORRECTO] == (refs / LOGO_CORRECTO).read_bytes()
    assert all(kw.get("ContentType") == "image/webp" for _, _, kw in c.puts)


def test_uploads_only_missing(refs):
    c = FakeClient(existing=[S3_PREFIX + LOGO_CORRECTO])
    uploaded = sync_refs_to_s3(_s3(c), directory=refs)
    assert uploaded == [S3_PREFIX + LOGO_INCORRECTO]
    assert c.store[S3_PREFIX + LOGO_CORRECTO] == b"old"  # no se sobrescribe
    assert len(c.puts) == 1


def test_uploads_nothing_when_all_present(refs):
    c = FakeClient(existing=[S3_PREFIX + LOGO_CORRECTO, S3_PREFIX + LOGO_INCORRECTO])
    assert sync_refs_to_s3(_s3(c), directory=refs) == []
    assert c.puts == []


def test_invalid_local_refs_abort_before_any_upload(refs):
    (refs / LOGO_CORRECTO).write_bytes(b"x")
    c = FakeClient()
    with pytest.raises(ReferenceCheckError):
        sync_refs_to_s3(_s3(c), directory=refs)
    assert c.puts == []


def test_bucket_mismatch_rejected_and_match_accepted(refs):
    c = FakeClient()
    with pytest.raises(ValueError):
        sync_refs_to_s3(_s3(c, "real"), bucket="otro", directory=refs)
    assert c.puts == []
    assert len(sync_refs_to_s3(_s3(c, "real"), bucket="real", directory=refs)) == 2
