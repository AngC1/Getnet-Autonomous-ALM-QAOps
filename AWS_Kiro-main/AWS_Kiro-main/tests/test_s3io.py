from __future__ import annotations

import io

import pytest

from brand_verifier.s3io import S3IO, S3OperationFailed


class FakeClient:
    def __init__(self, fail_times=0, not_found=False):
        self.fail_times = fail_times
        self.not_found = not_found
        self.calls = 0
        self.store = {}

    def _maybe_fail(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("boom")

    def put_object(self, Bucket, Key, Body, **kw):
        self._maybe_fail()
        self.store[Key] = Body

    def get_object(self, Bucket, Key):
        self._maybe_fail()
        return {"Body": io.BytesIO(self.store[Key])}

    def head_object(self, Bucket, Key):
        self._maybe_fail()
        if self.not_found or Key not in self.store:
            e = Exception("nf")
            e.response = {"Error": {"Code": "404"}}
            raise e
        return {}


def make(client, notes=None):
    sleeps = []
    notify = (lambda op, a, k: notes.append((op, a, k))) if notes is not None else None
    return S3IO(client, bucket="b", sleep=sleeps.append, notify=notify), sleeps


def test_put_get_exists_ok():
    c = FakeClient()
    s3, sleeps = make(c)
    s3.put("brand/x.json", b"hi", "a1")
    assert s3.get("brand/x.json") == b"hi"
    assert s3.exists("brand/x.json") is True
    assert s3.exists("brand/none.json") is False
    assert sleeps == []


def test_retries_with_1_2_4_then_succeeds():
    c = FakeClient(fail_times=3)
    s3, sleeps = make(c)
    s3.put("brand/x", b"d", "a1")
    assert sleeps == [1, 2, 4]
    assert not s3.pending


def test_failure_marks_notifies_and_keeps_pending():
    c = FakeClient(fail_times=99)
    notes = []
    s3, sleeps = make(c, notes)
    with pytest.raises(S3OperationFailed) as ei:
        s3.put("incidents/i/incident.json", b"data", "inc-1")
    assert sleeps == [1, 2, 4]
    assert ei.value.operation == "put" and ei.value.asset_id == "inc-1"
    assert notes == [("put", "inc-1", "incidents/i/incident.json")]
    assert s3.pending[0].data == b"data"


def test_rejects_other_prefixes():
    s3, _ = make(FakeClient())
    for k in ("other/x", "brand/../x", "/brand/x"):
        with pytest.raises(ValueError):
            s3.put(k, b"d")


# --- Ampliacion 3.3 (sin duplicar los casos anteriores) ---------------------
def test_put_from_local_path_and_content_type(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"payload")
    seen = {}

    class C(FakeClient):
        def put_object(self, Bucket, Key, Body, **kw):
            seen.update(Bucket=Bucket, Key=Key, Body=Body, **kw)

    s3, _ = make(C())
    s3.put("brand/a.bin", str(f), "a1", content_type="image/webp")
    assert seen == {"Bucket": "b", "Key": "brand/a.bin", "Body": b"payload",
                    "ContentType": "image/webp"}


def test_failed_put_from_path_keeps_local_path_pending(tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    s3, _ = make(FakeClient(fail_times=99))
    with pytest.raises(S3OperationFailed):
        s3.put("brand/generated/v.mp4", str(f), "v1")
    assert s3.pending[0].local_path == str(f)
    assert s3.pending[0].data is None


def test_failed_get_and_exists_raise_without_pending():
    notes = []
    s3, sleeps = make(FakeClient(fail_times=99), notes)
    with pytest.raises(S3OperationFailed) as e1:
        s3.get("brand/x", "a1")
    with pytest.raises(S3OperationFailed) as e2:
        s3.exists("brand/x", "a2")
    assert (e1.value.operation, e2.value.operation) == ("get", "exists")
    assert sleeps == [1, 2, 4, 1, 2, 4]
    assert [n[0] for n in notes] == ["get", "exists"]
    assert s3.pending == []


def test_exists_not_found_does_not_retry_or_notify():
    notes = []
    s3, sleeps = make(FakeClient(not_found=True), notes)
    assert s3.exists("brand/none", "a1") is False
    assert sleeps == [] and notes == []


def test_exists_retries_transient_error_then_reports_found():
    c = FakeClient(fail_times=2)
    c.store["brand/k"] = b"1"
    s3, sleeps = make(c)
    assert s3.exists("brand/k") is True
    assert sleeps == [1, 2]


def test_allows_incidents_prefix_and_rejects_non_string_key():
    c = FakeClient()
    s3, _ = make(c)
    s3.put("incidents/i1/incident.json", b"{}")
    assert "incidents/i1/incident.json" in c.store
    with pytest.raises(ValueError):
        s3.get(None)


def test_bucket_from_env_and_explicit_override(monkeypatch):
    monkeypatch.setenv("MEDIA_BUCKET", "env-bucket")
    assert S3IO(FakeClient()).bucket == "env-bucket"
    assert S3IO(FakeClient(), bucket="explicit").bucket == "explicit"
