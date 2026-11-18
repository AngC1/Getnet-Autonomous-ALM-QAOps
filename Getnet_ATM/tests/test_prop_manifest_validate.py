# Feature: atm-card-incident-video-simulation, Property 12: Validación manual de etiquetas
"""Property 12. **Validates: Requirements 6.7**"""
import copy

from hypothesis import given, settings, strategies as st

from brand_verifier.manifest import validate_asset
from brand_verifier.models import VALORES_VEREDICTO

labels = st.sampled_from(VALORES_VEREDICTO)
asset = st.fixed_dictionaries({
    "tipo": st.sampled_from(["imagen", "video"]),
    "flujo": st.sampled_from(["product-shot", "image-to-video"]),
    "ajustes": st.dictionaries(st.sampled_from(["width", "height", "frames"]), st.integers(1, 2000)),
    "etiqueta_esperada": labels,
    "etiqueta_validada": st.booleans(),
    "estado": st.sampled_from(["GENERADO", "GENERACION_FALLIDA"]),
    "motivo": st.none(),
    "s3_key": st.none(),
})


@st.composite
def manifests(draw):
    n = draw(st.integers(1, 8))
    assets = []
    for i in range(n):
        a = draw(asset)
        a["id"] = "asset-%d" % i
        assets.append(a)
    return {"assets": assets}, draw(st.integers(0, n - 1))


@settings(max_examples=200)
@given(manifests(), st.one_of(st.none(), labels), st.booleans())
def test_validate_asset_only_changes_target(data, corrected, confirmed):
    manifest, idx = data
    before = copy.deepcopy(manifest)
    target_id = manifest["assets"][idx]["id"]
    validate_asset(manifest, target_id, confirmed, corrected)
    for i, (new, old) in enumerate(zip(manifest["assets"], before["assets"])):
        if i != idx:
            assert new == old
            continue
        assert new["etiqueta_validada"] is True
        expected = corrected if corrected is not None else old["etiqueta_esperada"]
        assert new["etiqueta_esperada"] == expected
        rest_new = {k: v for k, v in new.items() if k not in ("etiqueta_validada", "etiqueta_esperada")}
        rest_old = {k: v for k, v in old.items() if k not in ("etiqueta_validada", "etiqueta_esperada")}
        assert rest_new == rest_old
    assert len(manifest["assets"]) == len(before["assets"])
