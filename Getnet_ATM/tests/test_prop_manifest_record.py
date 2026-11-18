# Feature: atm-card-incident-video-simulation, Property 11: Registro nuevo en el Manifiesto
"""Property 11. **Validates: Requirements 6.6**

Se ejecuta ``generate_dataset`` con un cliente ComfyUI y S3 falsos; el token es un
valor ficticio generado por hypothesis.
"""
import json
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings, strategies as st

from brand_verifier import generator as gen
from brand_verifier import manifest as mf

ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-_"


class _Client:
    def __init__(self):
        self.real = gen.load_comfy_client()

    def apply_overrides(self, graph, inputs, overrides):
        return self.real.apply_overrides(graph, inputs, overrides)

    def upload_image(self, base_url, path, token=None):
        return "up-" + Path(path).name

    def run_workflow(self, base_url, api_graph, timeout_s=1800, out_dir=Path("."), poll_s=2.0,
                     token=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        video = any(v["class_type"] == "SaveVideo" for v in api_graph.values())
        f = out_dir / ("o." + ("mp4" if video else "png"))
        f.write_bytes(b"x")
        return [f]


class _S3:
    def put(self, key, data, asset_id=None, content_type=None):
        pass


specs = st.builds(
    gen.AssetSpec,
    id=st.text(alphabet=ID_ALPHABET, min_size=1, max_size=40),
    tipo=st.sampled_from(["imagen", "video"]),
    etiqueta_esperada=st.sampled_from(["CORRECTO", "INCORRECTO", "SIN_LOGO"]),
    prompt=st.text(alphabet="abc def.", min_size=1, max_size=60),
)
tokens = st.text(alphabet="ABCDEFGHJKLMNPQRSTUVWXYZ", min_size=24, max_size=40).map(lambda s: "TOK." + s)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(specs, tokens)
def test_new_record_is_unvalidated_and_secret_free(spec, token):
    with tempfile.TemporaryDirectory() as tmp:
        assets = Path(tmp) / "brand"
        assets.mkdir()
        (assets / "logo-ayesa-boletin.webp").write_bytes(b"w")
        (assets / "logo-vector_ayesa.webp").write_bytes(b"w")
        old_dir = gen.ASSETS_DIR
        gen.ASSETS_DIR = assets
        try:
            manifest = mf.new_manifest()
            gen.generate_dataset(
                [spec], manifest, _S3(), base_url="http://comfy.invalid", token=token,
                client=_Client(), workdir=Path(tmp) / "w", status=lambda s: None,
                probe_fn=lambda u, t: None, interrupt_fn=lambda u, t: None,
                concat_fn=lambda paths, out: (Path(out).write_bytes(b"m"), Path(out))[1])
        finally:
            gen.ASSETS_DIR = old_dir
    assert len(manifest["assets"]) == 1
    rec = manifest["assets"][0]
    assert rec["id"] == spec.id
    assert rec["tipo"] == spec.tipo
    assert rec["flujo"] == spec.flujo
    assert rec["etiqueta_esperada"] == spec.etiqueta_esperada
    assert rec["etiqueta_validada"] is False
    assert rec["estado"] == "GENERADO"
    assert isinstance(rec["ajustes"], dict) and rec["ajustes"]
    assert token not in json.dumps(manifest)
    assert "Bearer" not in json.dumps(manifest)
