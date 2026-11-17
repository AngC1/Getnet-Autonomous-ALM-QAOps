# Feature: atm-card-incident-video-simulation, Property 3: Selección de evidencias de vídeo
"""Property 3. **Validates: Requirements 3.6**"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from brand_verifier.core import select_video_evidence
from brand_verifier.models import Evidence, FrameVerdict, VALORES_VEREDICTO

coord = st.integers(0, 98).flatmap(
    lambda a: st.tuples(st.just(a / 100.0), st.integers(a + 1, 100).map(lambda b: b / 100.0)))
bboxes = st.tuples(coord, coord).map(lambda t: (t[0][0], t[1][0], t[0][1], t[1][1]))
logos = st.sampled_from(["CORRECTO", "INCORRECTO"])


@st.composite
def frames(draw):
    n = draw(st.integers(1, 30))
    out = []
    for i in range(n):
        v = draw(st.sampled_from(VALORES_VEREDICTO))
        k = 0 if v == "SIN_LOGO" else draw(st.integers(1, 3))
        evs = [Evidence(i, draw(bboxes), draw(logos)) for _ in range(k)]
        out.append(FrameVerdict(i, v, 0.9, evs))
    return out


@settings(max_examples=200)
@given(frames())
def test_selection(fs):
    sel = select_video_evidence(fs)
    for f in fs:
        if f.veredicto in ("INCORRECTO", "AMBIGUO"):
            for e in f.evidencias:
                assert e in sel
    correct = [f for f in fs if f.veredicto == "CORRECTO"]
    if correct:
        pool = [e for f in correct for e in f.evidencias]
        assert any(e in sel for e in pool)
