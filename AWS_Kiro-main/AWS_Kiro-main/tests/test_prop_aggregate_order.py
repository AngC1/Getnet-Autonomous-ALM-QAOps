# Feature: atm-card-incident-video-simulation, Property 2: Agregación independiente del orden
"""Property 2. **Validates: Requirements 3.9**"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from brand_verifier.core import aggregate_frames
from brand_verifier.models import VALORES_VEREDICTO

values = st.lists(st.sampled_from(VALORES_VEREDICTO), min_size=1, max_size=60)


@settings(max_examples=200)
@given(values, st.randoms(use_true_random=False))
def test_order_independent(vals, rnd):
    shuffled = list(vals)
    rnd.shuffle(shuffled)
    assert aggregate_frames(shuffled) == aggregate_frames(vals)
    assert aggregate_frames(list(reversed(vals))) == aggregate_frames(vals)
