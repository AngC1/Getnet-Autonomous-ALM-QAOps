# Feature: atm-card-incident-video-simulation, Property 4: Muestreo a 1 fotograma por segundo
"""Property 4. **Validates: Requirements 3.1**"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from brand_verifier.core import sample_timestamps

durations = st.one_of(st.integers(1, 60), st.floats(1, 60, allow_nan=False))


@settings(max_examples=200)
@given(durations)
def test_sampling(d):
    ts = sample_timestamps(d)
    assert len(ts) >= 1
    assert all(b - a == 1 for a, b in zip(ts, ts[1:]))
    assert ts[0] == 0
    assert all(t <= d for t in ts)
    assert len(ts) == int(d // 1)
