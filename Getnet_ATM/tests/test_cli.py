"""Tests de la CLI/orquestador con fakes inyectados (sin AWS ni ComfyUI)."""
import json

import pytest

from brand_verifier import cli, generator, references, verifier
from brand_verifier.models import Evidence, Verdict, VerifyError


def _asset(i, tipo="imagen", esperada="CORRECTO", validada=True, estado="GENERADO"):
    return {"id": i, "tipo": tipo, "flujo": "x", "ajustes": {}, "etiqueta_esperada": esperada,
            "etiqueta_validada": validada, "estado": estado, "motivo": None,
            "s3_key": "brand/generated/%s/output.%s" % (i, "png" if tipo == "imagen" else "mp4")}


def _write_manifest(tmp_path, assets):
    p = tmp_path / "generated" / "manifest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"assets": assets}), encoding="utf-8")
    for a in assets:
        f = tmp_path / a["s3_key"][len("brand/"):]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    return p


@pytest.fixture
def calls(monkeypatch):
    log = []
    monkeypatch.setattr(references, "check_local_refs", lambda d: log.append("refs") or {})
    monkeypatch.setattr(references, "sync_refs_to_s3", lambda s3, bucket=None, directory=None: [])
    monkeypatch.setattr(cli, "_bedrock_client", lambda: object())

    def vimg(data, asset_id, **kw):
        log.append("verify:" + asset_id)
        return Verdict("CORRECTO", 0.9, [Evidence(0, (0.1, 0.1, 0.5, 0.5), "CORRECTO")], "ok")
    monkeypatch.setattr(verifier, "verify_image", vimg)
    monkeypatch.setattr(verifier, "verify_video", lambda p, i, **kw: vimg(b"", i))

    def gen(plan, manifest, s3=None, **kw):
        log.append("gen")
        return manifest
    monkeypatch.setattr(generator, "generate_dataset", gen)
    return log


def _run(tmp_path, *extra):
    return cli.main(["run", "--no-s3", "--out-dir", str(tmp_path), *extra])


def test_missing_manifest_with_skip_generation_runs_no_stage(tmp_path, calls, capsys):
    code = _run(tmp_path, "--skip-generation", "--manifest", str(tmp_path / "nope.json"))
    assert code != 0
    assert calls == []
    assert "[etapa]" not in capsys.readouterr().out
    assert not (tmp_path / "reports" / "report.html").exists()


def test_unreadable_manifest_aborts(tmp_path, calls):
    p = tmp_path / "bad.json"
    p.write_text("{no json", encoding="utf-8")
    assert _run(tmp_path, "--skip-generation", "--manifest", str(p)) != 0
    assert calls == []


def test_stage_order_and_outputs(tmp_path, calls, capsys):
    _write_manifest(tmp_path, [_asset("a1"), _asset("v1", "video"), _asset("bad", estado="GENERACION_FALLIDA")])
    assert _run(tmp_path, "--skip-generation") == 0
    out = capsys.readouterr().out
    pos = [out.index("[etapa] %s: en curso" % s) for s in ("referencias", "verificacion", "informe")]
    assert pos == sorted(pos)
    assert "generacion: omitida" in out
    assert calls[0] == "refs" and "gen" not in calls
    assert sorted(c for c in calls if c.startswith("verify:")) == ["verify:a1", "verify:v1"]
    html = (tmp_path / "reports" / "report.html").read_text(encoding="utf-8")
    assert "a1" in html and "PARCIAL" not in html
    assert json.loads((tmp_path / "verdicts" / "a1.json").read_text())["veredicto"] == "CORRECTO"


def test_generation_runs_before_verification(tmp_path, calls, monkeypatch):
    def gen(plan, manifest, s3=None, **kw):
        calls.append("gen")
        manifest_assets = [_asset("g1")]
        _write_manifest(tmp_path, manifest_assets)
        manifest["assets"] = manifest_assets
        return manifest
    monkeypatch.setattr(generator, "generate_dataset", gen)
    assert _run(tmp_path) == 0
    assert calls.index("gen") < calls.index("verify:g1")


def test_failed_stage_skips_dependents_and_partial_report(tmp_path, calls, monkeypatch, capsys):
    def boom(d):
        raise references.ReferenceCheckError(["falta logo"])
    monkeypatch.setattr(references, "check_local_refs", boom)
    _write_manifest(tmp_path, [_asset("a1")])
    assert _run(tmp_path, "--skip-generation") != 0
    out = capsys.readouterr().out
    assert "referencias: fallida" in out and "verificacion: omitida" in out
    assert not any(c.startswith("verify:") for c in calls)
    html = (tmp_path / "reports" / "report.html").read_text(encoding="utf-8")
    assert "INFORME PARCIAL" in html and "referencias" in html


def test_generation_failure_skips_verification(tmp_path, calls, monkeypatch):
    def gen(*a, **k):
        raise RuntimeError("comfy caido")
    monkeypatch.setattr(generator, "generate_dataset", gen)
    assert _run(tmp_path) != 0
    assert not any(c.startswith("verify:") for c in calls)
    assert "INFORME PARCIAL" in (tmp_path / "reports" / "report.html").read_text(encoding="utf-8")


def test_verify_error_becomes_failed_row(tmp_path, calls, monkeypatch):
    monkeypatch.setattr(verifier, "verify_image", lambda d, i, **kw: VerifyError(i, "nope"))
    _write_manifest(tmp_path, [_asset("a1")])
    assert _run(tmp_path, "--skip-generation") == 0
    assert "a1" in (tmp_path / "reports" / "report.html").read_text(encoding="utf-8")


def test_only_filters_assets(tmp_path, calls):
    _write_manifest(tmp_path, [_asset("a1"), _asset("a2")])
    assert _run(tmp_path, "--skip-generation", "--only", "a2") == 0
    assert [c for c in calls if c.startswith("verify:")] == ["verify:a2"]


def test_validate_subcommand(tmp_path):
    p = _write_manifest(tmp_path, [_asset("a1", validada=False)])
    assert cli.main(["validate", "a1", "--label", "INCORRECTO", "--no-s3", "--manifest", str(p)]) == 0
    a = json.loads(p.read_text())["assets"][0]
    assert a["etiqueta_validada"] is True and a["etiqueta_esperada"] == "INCORRECTO"
    assert cli.main(["validate", "zz", "--no-s3", "--manifest", str(p)]) != 0


def test_incident_subcommand_invalid_file(tmp_path):
    assert cli.main(["incident", str(tmp_path / "x.json"), "--no-s3", "--out-dir", str(tmp_path)]) != 0
