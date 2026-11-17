# Feature: atm-card-incident-video-simulation, Property 1: Agregación de vídeo por reglas de prioridad
"""Property 1. **Validates: Requirements 3.2, 3.3, 3.4, 3.5**"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from brand_verifier.core import aggregate_frames
from brand_verifier.models import VALORES_VEREDICTO

values = st.lists(st.sampled_from(VALORES_VEREDICTO), min_size=1, max_size=60)


@settings(max_examples=200)
@given(values)
def test_priority(vals):
    got = aggregate_frames(vals)
    if "INCORRECTO" in vals:
        assert got == "INCORRECTO"
    elif "AMBIGUO" in vals:
        assert got == "AMBIGUO"
    elif "CORRECTO" in vals:
        assert got == "CORRECTO"
    else:
        assert all(v == "SIN_LOGO" for v in vals)
        assert got == "SIN_LOGO"
