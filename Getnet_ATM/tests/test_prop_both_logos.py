# Feature: atm-card-incident-video-simulation, Property 8: Ambos logos implican INCORRECTO
"""Property 8. **Validates: Requirements 2.6**"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from brand_verifier.core import normalize_model_output
from brand_verifier.models import validate_verdict

coord = st.integers(0, 98).flatmap(
    lambda a: st.tuples(st.just(a / 100.0), st.integers(a + 1, 100).map(lambda b: b / 100.0)))
bbox = st.tuples(coord, coord).map(lambda t: [t[0][0], t[1][0], t[0][1], t[1][1]])
ev = lambda logo: st.builds(lambda b: {"timestamp_s": 0, "bbox": b, "logo_detectado": logo}, bbox)


@st.composite
def raw_outputs(draw):
    ok = draw(st.lists(ev("CORRECTO"), min_size=1, max_size=3))
    bad = draw(st.lists(ev("INCORRECTO"), min_size=1, max_size=3))
    evs = ok + bad
    evs = draw(st.permutations(evs))
    return {
        "veredicto": draw(st.sampled_from(["CORRECTO", "INCORRECTO", "AMBIGUO", "SIN_LOGO"])),
        "confianza": draw(st.floats(0, 1)),
        "evidencias": list(evs),
        "recomendacion": draw(st.text(min_size=1, max_size=100).filter(lambda s: s.strip())),
    }


@settings(max_examples=200)
@given(raw_outputs())
def test_both_logos(raw):
    out = normalize_model_output(raw)
    assert out["veredicto"] == "INCORRECTO"
    logos = [e["logo_detectado"] for e in out["evidencias"]]
    assert "CORRECTO" in logos and "INCORRECTO" in logos
    assert len(out["evidencias"]) == len(raw["evidencias"])
    assert validate_verdict(out) == []
