# Feature: atm-card-incident-video-simulation, Property 10: Entrada de generación según etiqueta
"""Property 10. **Validates: Requirements 6.3**"""
from pathlib import Path

from hypothesis import given, settings, strategies as st

from brand_verifier.generator import ASSETS_DIR, AssetSpec, default_plan, select_input_logo
from brand_verifier.models import VALORES_VEREDICTO

EXPECTED = {
    "CORRECTO": "logo-ayesa-boletin.webp",
    "INCORRECTO": "logo-vector_ayesa.webp",
}

specs = st.builds(
    AssetSpec,
    id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=64),
    tipo=st.sampled_from(["imagen", "video"]),
    etiqueta_esperada=st.sampled_from(["CORRECTO", "INCORRECTO", "SIN_LOGO"]),
    prompt=st.text(max_size=200),
    variant=st.sampled_from(["simple", "atm", "mixed"]),
)


@settings(max_examples=200)
@given(specs)
def test_input_logo_is_only_expected_brand_reference(spec):
    logo = select_input_logo(spec)
    if spec.etiqueta_esperada == "SIN_LOGO":
        assert logo is None
    else:
        assert isinstance(logo, Path)
        assert logo.name == EXPECTED[spec.etiqueta_esperada]
        assert logo.parent == ASSETS_DIR


def test_default_plan_follows_property():
    for spec in default_plan():
        logo = select_input_logo(spec)
        assert (logo is None) == (spec.etiqueta_esperada not in EXPECTED)
        assert spec.etiqueta_esperada in VALORES_VEREDICTO
