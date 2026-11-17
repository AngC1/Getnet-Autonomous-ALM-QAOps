"""Subcomando register y merge del informe con --only (sin AWS, sin red)."""
import io
import json
import re

import pytest

from brand_verifier import cli, core, register, verifier
from brand_verifier.models import Verdict, Evidence
from brand_verifier.s3io import S3IO

from .conftest import png_bytes


class FakeS3Client:
    def __init__(self):
        self.objects = {}
        self.puts = []

    def put_object(self, Bucket, Key, Body, **kw):
        self.objects[Key] = Body
        self.puts.append((Key, kw.get("ContentType")))

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            e = Exception("nf")
            e.response = {"Error": {"Code": "NoSuchKey"}}
            raise e
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            e = Exception("nf")
            e.response = {"Error": {"Code": "404"}}
            raise e
        return {}


@pytest.fixture
def fake_s3(monkeypatch):
    client = FakeS3Client()
    s3 = S3IO(client=client, bucket="b", sleep=lambda s: None)
    monkeypatch.setattr(cli, "_make_s3", lambda no_s3, out_dir: s3)
    return client


def _run(tmp_path, f, label="CORRECTO", *extra):
    return cli.main(["register", "--file", str(f), "--label", label, "--out-dir", str(tmp_path / "brand"),
                     *extra])


def _mp4_header():
    return b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32


def test_sniff_by_content_not_name():
    assert register.sniff(png_bytes()[:16]) == ("imagen", ".png")
    assert register.sniff(b"\xff\xd8\xff\xe0" + b"0" * 12) == ("imagen", ".jpg")
    assert register.sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ("imagen", ".webp")
    assert register.sniff(b"\x00\x00\x00\x14ftypqt  " + b"0" * 4) == ("video", ".mov")
    assert register.sniff(_mp4_header()[:16]) == ("video", ".mp4")
    assert register.sniff(b"\x1a\x45\xdf\xa3" + b"0" * 12) == ("video", ".webm")
    assert register.sniff(b"GIF89a" + b"0" * 10) is None
    assert register.sniff(b"MZ\x90\x00" + b"0" * 12) is None


def test_register_image_uploads_and_records(tmp_path, fake_s3, capsys):
    f = tmp_path / "evil name; rm -rf.exe"  # el nombre se ignora; manda el contenido
    f.write_bytes(png_bytes())
    assert _run(tmp_path, f, "INCORRECTO") == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert re.fullmatch(r"up-imagen-[0-9a-f]{8}", out["id"])
    assert out["tipo"] == "imagen"
    assert out["s3_key"] == "brand/generated/%s/output.png" % out["id"]
    assert (out["s3_key"], "image/png") in fake_s3.puts
    manifest = json.loads(fake_s3.objects["brand/generated/manifest.json"])
    rec = [a for a in manifest["assets"] if a["id"] == out["id"]][0]
    assert rec["flujo"] == "upload" and rec["etiqueta_esperada"] == "INCORRECTO"
    assert rec["etiqueta_validada"] is False and rec["estado"] == "GENERADO"


def test_register_explicit_id_and_merge_keeps_others(tmp_path, fake_s3, capsys):
    f = tmp_path / "a.png"
    f.write_bytes(png_bytes())
    assert _run(tmp_path, f, "SIN_LOGO", "--id", "mi_activo-1") == 0
    assert _run(tmp_path, f, "AMBIGUO", "--id", "otro") == 0
    ids = [a["id"] for a in json.loads(fake_s3.objects["brand/generated/manifest.json"])["assets"]]
    assert ids == ["mi_activo-1", "otro"]


@pytest.mark.parametrize("bad_id", ["../x", "a b", "x" * 65, "a/b"])
def test_register_rejects_bad_id(tmp_path, fake_s3, bad_id, capsys):
    f = tmp_path / "a.png"
    f.write_bytes(png_bytes())
    assert _run(tmp_path, f, "CORRECTO", "--id", bad_id) == 1
    assert fake_s3.puts == []


def test_register_rejects_unknown_type_and_bad_label(tmp_path, fake_s3, capsys):
    f = tmp_path / "a.png"
    f.write_bytes(b"GIF89a" + b"0" * 100)
    assert _run(tmp_path, f) == 1
    assert "no permitido" in capsys.readouterr().err
    f.write_bytes(png_bytes())
    assert cli.main(["register", "--file", str(f), "--label", "FOO"]) == 2
    assert fake_s3.puts == []


def test_register_rejects_big_image(tmp_path, fake_s3, capsys):
    f = tmp_path / "big.png"
    f.write_bytes(png_bytes() + b"\0" * (core.MAX_IMAGE_BYTES + 1))
    assert _run(tmp_path, f) == 1
    assert "5 MB" in capsys.readouterr().err and fake_s3.puts == []


def test_register_video_limits(tmp_path, fake_s3, monkeypatch, capsys):
    f = tmp_path / "v.mp4"
    f.write_bytes(_mp4_header())
    monkeypatch.setattr(register, "video_duration", lambda p: 61.0)
    assert _run(tmp_path, f) == 1
    assert "60 s" in capsys.readouterr().err
    monkeypatch.setattr(register, "MAX_VIDEO_BYTES", 10)
    assert _run(tmp_path, f) == 1
    assert "200 MB" in capsys.readouterr().err and fake_s3.puts == []


def test_register_video_h264_no_transcode(tmp_path, fake_s3, monkeypatch, capsys):
    f = tmp_path / "v.mp4"
    f.write_bytes(_mp4_header())
    monkeypatch.setattr(register, "video_duration", lambda p: 5.0)
    monkeypatch.setattr(register, "_ffmpeg", lambda: "ff")
    monkeypatch.setattr(register, "video_codec", lambda ff, p: "h264")
    monkeypatch.setattr(register, "transcode_h264", lambda *a: pytest.fail("no debe transcodificar"))
    assert _run(tmp_path, f) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["tipo"] == "video" and out["s3_key"].endswith("/output.mp4")
    assert (out["s3_key"], "video/mp4") in fake_s3.puts


def test_register_video_transcodes_non_h264(tmp_path, fake_s3, monkeypatch, capsys):
    f = tmp_path / "v.webm"
    f.write_bytes(b"\x1a\x45\xdf\xa3" + b"0" * 40)
    seen = {}

    def fake_transcode(ff, src, dst):
        open(dst, "wb").write(b"H264DATA")
        seen["dst"] = dst

    monkeypatch.setattr(register, "video_duration", lambda p: 5.0)
    monkeypatch.setattr(register, "_ffmpeg", lambda: "ff")
    monkeypatch.setattr(register, "video_codec", lambda ff, p: "vp9")
    monkeypatch.setattr(register, "transcode_h264", fake_transcode)
    assert _run(tmp_path, f) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["s3_key"].endswith("/output.mp4")
    assert fake_s3.objects[out["s3_key"]] == b"H264DATA"
    assert (out["s3_key"], "video/mp4") in fake_s3.puts


def test_run_only_merges_previous_rows(tmp_path):
    """--only no pierde del informe los activos ya verificados (merge con veredictos guardados)."""
    from brand_verifier.models import verdict_to_json

    def asset(i):
        return {"id": i, "tipo": "imagen", "etiqueta_esperada": "CORRECTO", "etiqueta_validada": False,
                "estado": "GENERADO", "s3_key": "brand/generated/%s/output.png" % i}

    s3 = cli.LocalS3(str(tmp_path))
    old = Verdict("CORRECTO", 0.9, [Evidence(0, (0.1, 0.1, 0.5, 0.5), "CORRECTO")], "ok")
    (tmp_path / "verdicts").mkdir()
    (tmp_path / "verdicts" / "a.json").write_text(verdict_to_json(old))
    manifest = {"assets": [asset("a"), asset("b")]}
    new = {"id": "b", "tipo": "imagen", "esperada": "CORRECTO", "detectada": "INCORRECTO", "confianza": 0.7}
    merged = cli._merge_previous_rows(manifest, [new], s3)
    assert [r["id"] for r in merged] == ["a", "b"]
    assert merged[0]["detectada"] == "CORRECTO" and merged[1] is new
