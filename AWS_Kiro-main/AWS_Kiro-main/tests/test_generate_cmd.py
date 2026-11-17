"""Tests del subcomando ``generate`` con fakes (sin AWS ni ComfyUI)."""
import json
import re

import pytest

from brand_verifier import cli, generator, manifest as mf, ondemand
from brand_verifier.models import Evidence, Verdict, verdict_to_json

ID_RE = re.compile(r"^gen-(imagen|video)-[0-9a-f]{8}$")


def _result(out):
    lines = [l for l in out.splitlines() if l.startswith("RESULT ")]
    assert len(lines) == 1
    return json.loads(lines[0][len("RESULT "):])


@pytest.fixture
def fake_gen(monkeypatch):
    """generate_dataset falso: registra el activo (o lo marca fallido) y guarda el manifiesto."""
    seen = {"fail": False}

    def gen(plan, manifest, s3=None, **kw):
        spec = plan[0]
        seen["spec"], seen["manifest_in"] = spec, json.loads(json.dumps(manifest))
        seen["kw"] = kw
        if seen["fail"]:
            mf.register_asset(manifest, spec.id, spec.tipo, spec.flujo, {}, spec.etiqueta_esperada,
                              estado="GENERACION_FALLIDA", motivo="GenerationError: timeout")
        else:
            key = "brand/generated/%s/output.%s" % (spec.id, "png" if spec.tipo == "imagen" else "mp4")
            s3.put(key, b"x")
            mf.register_asset(manifest, spec.id, spec.tipo, spec.flujo, {"prompt": spec.prompt},
                              spec.etiqueta_esperada, s3_key=key)
        mf.save(manifest, kw["manifest_path"], s3)
        return manifest

    monkeypatch.setattr(generator, "generate_dataset", gen)
    return seen


def _gen(tmp_path, *extra):
    return cli.main(["generate", "--no-s3", "--out-dir", str(tmp_path), *extra])


def test_prompts_logo_sin_logo_y_video():
    for escena in ondemand.SCENES:
        p = ondemand.build_prompt("INCORRECTO", "imagen", escena)
        assert "with the attached company logo" in p
        assert "no logo" not in p
        q = ondemand.build_prompt("SIN_LOGO", "imagen", escena)
        assert "no logo, no text, no lettering anywhere" in q
        assert "attached company logo" not in q and "logotipo" not in q
        v = ondemand.build_prompt("CORRECTO", "video", escena)
        assert "the logo stays perfectly static, sharp and fully legible" in v.lower()
    atm = ondemand.build_prompt("CORRECTO", "imagen", "atm")
    assert atm.startswith("Cajero automatico de calle por la noche, plano medio realista")
    assert "tarjeta retenida" not in atm
    custom = ondemand.build_prompt("CORRECTO", "imagen", None, "Un autobus urbano")
    assert custom.startswith("Un autobus urbano, with the attached company logo")


def test_validacion_del_prompt():
    assert ondemand.validate_prompt("  hola  ") == "hola"
    assert ondemand.validate_prompt("x" * 300) == "x" * 300
    for bad in ("x" * 301, "a\nb", "a\x00b", "a\u202eb", "   ", 5):
        with pytest.raises(ondemand.InvalidInput):
            ondemand.validate_prompt(bad)


@pytest.mark.parametrize("extra", [
    ["--logo", "OTRO", "--tipo", "imagen"],
    ["--logo", "CORRECTO", "--tipo", "gif"],
    ["--logo", "CORRECTO", "--tipo", "imagen", "--escena", "luna"],
    ["--logo", "CORRECTO", "--tipo", "imagen", "--prompt", "x" * 301],
    ["--logo", "CORRECTO", "--tipo", "imagen", "--prompt", "a\tb"],
    ["--tipo", "imagen"],
    ["--logo", "CORRECTO", "--tipo", "imagen", "--desconocida"],
])
def test_entrada_invalida_sale_con_1_sin_generar(tmp_path, fake_gen, extra):
    assert _gen(tmp_path, *extra) == 1
    assert "spec" not in fake_gen


def test_genera_registra_e_imprime_result(tmp_path, fake_gen, capsys):
    assert _gen(tmp_path, "--logo", "INCORRECTO", "--tipo", "imagen", "--escena", "atm") == 0
    res = _result(capsys.readouterr().out)
    assert ID_RE.match(res["id"]) and res["id"].startswith("gen-imagen-")
    assert res["tipo"] == "imagen" and res["estado"] == "GENERADO"
    assert res["s3_key"] == "brand/generated/%s/output.png" % res["id"]
    spec = fake_gen["spec"]
    assert spec.etiqueta_esperada == "INCORRECTO" and spec.flujo == "product-shot"
    assert "with the attached company logo" in spec.prompt
    assert generator.select_input_logo(spec).name == "logo-vector_ayesa.webp"
    saved = json.loads((tmp_path / "generated" / "manifest.json").read_text(encoding="utf-8"))
    rec = mf.find_asset(saved, res["id"])
    assert rec["etiqueta_esperada"] == "INCORRECTO" and rec["etiqueta_validada"] is False


def test_merge_con_el_manifiesto_existente(tmp_path, fake_gen, capsys):
    p = tmp_path / "generated" / "manifest.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"assets": [{"id": "img-previo", "tipo": "imagen", "estado": "GENERADO"}]}))
    assert _gen(tmp_path, "--logo", "SIN_LOGO", "--tipo", "video") == 0
    res = _result(capsys.readouterr().out)
    assert res["id"].startswith("gen-video-")
    assert generator.select_input_logo(fake_gen["spec"]) is None
    assert "no logo, no text, no lettering anywhere" in fake_gen["spec"].prompt
    ids = [a["id"] for a in json.loads(p.read_text())["assets"]]
    assert ids == ["img-previo", res["id"]]


def test_generacion_fallida_sale_con_2(tmp_path, fake_gen, capsys, monkeypatch):
    fake_gen["fail"] = True
    called = []
    monkeypatch.setattr(cli, "cmd_run", lambda ns: called.append(ns) or 0)
    assert _gen(tmp_path, "--logo", "CORRECTO", "--tipo", "imagen", "--verify") == 2
    out = capsys.readouterr().out
    assert _result(out)["estado"] == "GENERACION_FALLIDA"
    assert "[fase] generacion: fallida" in out
    assert called == []  # no se verifica lo que no se genero


def test_verify_reutiliza_run_only(tmp_path, fake_gen, capsys, monkeypatch):
    seen = []

    def fake_run(ns):
        seen.append(ns)
        v = Verdict("CORRECTO", 0.93, [Evidence(0, (0.1, 0.1, 0.5, 0.5), "CORRECTO")], "ok")
        path = tmp_path / "verdicts" / ("%s.json" % ns.only)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(verdict_to_json(v), encoding="utf-8")
        return 0

    monkeypatch.setattr(cli, "cmd_run", fake_run)
    assert _gen(tmp_path, "--logo", "CORRECTO", "--tipo", "imagen", "--escena", "oficina", "--verify") == 0
    out = capsys.readouterr().out
    res = _result(out)
    assert seen[0].only == res["id"] and seen[0].skip_generation is True and seen[0].no_s3 is True
    assert "[fase] verificacion: completada" in out and "CORRECTO, confianza 0.93" in out
    assert out.strip().splitlines()[-1].startswith("RESULT ")


def test_verificacion_fallida_sale_con_3(tmp_path, fake_gen, capsys, monkeypatch):
    monkeypatch.setattr(cli, "cmd_run", lambda ns: 1)
    assert _gen(tmp_path, "--logo", "CORRECTO", "--tipo", "imagen", "--verify") == 3
    assert _result(capsys.readouterr().out)["estado"] == "GENERADO"


def test_generate_dataset_real_con_cliente_falso(tmp_path, monkeypatch, capsys):
    """Integracion: generate_dataset real con ComfyUI falso; el logo subido es el de la marca."""
    from tests.test_generator import FakeClient, FAKE_TOKEN

    client = FakeClient()
    real = generator.generate_dataset

    def gen(plan, manifest, s3=None, **kw):
        return real(plan, manifest, s3, base_url="http://comfy.invalid", token=FAKE_TOKEN, client=client,
                    probe_fn=lambda u, t: None, **kw)

    monkeypatch.setattr(generator, "generate_dataset", gen)
    assert _gen(tmp_path, "--logo", "CORRECTO", "--tipo", "imagen", "--escena", "valla") == 0
    res = _result(capsys.readouterr().out)
    assert res["estado"] == "GENERADO"
    assert (tmp_path / "generated" / res["id"] / "output.png").is_file()
    assert client.uploads == ["logo-ayesa-boletin.webp"]
