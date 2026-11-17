"""Property 6: ida y vuelta del Veredicto.

**Validates: Requirements 4.7**
"""
from hypothesis import given, settings, strategies as st

from brand_verifier.models import (
    Evidence,
    Verdict,
    validate_verdict,
    verdict_from_json,
    verdict_to_json,
)

_unit = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=200,
)


@st.composite
def _bboxes(draw):
    a = draw(_unit)
    b = draw(_unit)
    lo, hi = min(a, b), max(a, b)
    if lo == hi:  # exige min < max
        if hi < 1.0:
            hi = min(1.0, hi + 0.01) if hi + 0.01 > hi else 1.0
        else:
            lo = max(0.0, lo - 0.01)
    c = draw(_unit)
    d = draw(_unit)
    lo2, hi2 = min(c, d), max(c, d)
    if lo2 == hi2:
        if hi2 < 1.0:
            hi2 = min(1.0, hi2 + 0.01)
        else:
            lo2 = max(0.0, lo2 - 0.01)
    return (lo, lo2, hi, hi2)


_logo = st.sampled_from(["CORRECTO", "INCORRECTO"])
_timestamp = st.one_of(
    st.integers(min_value=0, max_value=3600),
    st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
)
_confidence = st.one_of(st.integers(min_value=0, max_value=1), _unit)


@st.composite
def _evidences(draw, min_size=0, max_size=4):
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    return [
        Evidence(draw(_timestamp), draw(_bboxes()), draw(_logo)) for _ in range(n)
    ]


@st.composite
def valid_verdicts(draw):
    valor = draw(st.sampled_from(["CORRECTO", "INCORRECTO", "SIN_LOGO", "AMBIGUO"]))
    rec = draw(_text)
    if valor == "INCORRECTO":
        rec = "Sustituir por Ayesa Digital. " + rec[:400]
        evs = draw(_evidences(min_size=1))
    elif valor == "CORRECTO":
        evs = draw(_evidences(min_size=1))
    elif valor == "SIN_LOGO":
        evs = []
    else:
        evs = draw(_evidences())
    return Verdict(valor, draw(_confidence), evs, rec)


# Feature: atm-card-incident-video-simulation, Property 6: Ida y vuelta del Veredicto
@settings(max_examples=200, deadline=None)
@given(valid_verdicts())
def test_verdict_roundtrip(v):
    assert validate_verdict(v) == []

    s = verdict_to_json(v)
    v2 = verdict_from_json(s)

    assert v2 == v
    assert verdict_to_json(v2) == s
