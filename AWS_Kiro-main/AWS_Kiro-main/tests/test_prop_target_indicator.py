"""Property 14: Indicador de objetivo.

**Validates: Requirements 9.5**
"""
from hypothesis import given, settings, strategies as st

from brand_verifier.report import render_report


# Feature: atm-card-incident-video-simulation, Property 14: Indicador de objetivo
@settings(max_examples=200)
@given(st.one_of(st.floats(0, 100, allow_nan=False), st.sampled_from([89.99, 90.0, 90.01, 0.0, 100.0])))
def test_target_indicator(p):
    out = render_report([], {"precision": p, "tiempo_medio_s": 0.0})
    if p >= 90:
        assert "OBJETIVO ALCANZADO" in out and "OBJETIVO NO ALCANZADO" not in out
    else:
        assert "OBJETIVO NO ALCANZADO" in out and "OBJETIVO ALCANZADO" not in out
