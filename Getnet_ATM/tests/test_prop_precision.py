"""Property 13: Precision_Global solo sobre activos validados.

**Validates: Requirements 6.8, 9.4**
"""
from hypothesis import given, settings

from brand_verifier.report import compute_precision
from tests._report_strategies import rows_st


# Feature: atm-card-incident-video-simulation, Property 13: Precision_Global solo sobre activos validados
@settings(max_examples=200)
@given(rows_st())
def test_precision_only_validated(rows):
    val = [r for r in rows if r["validada"]]
    expected = 0.0 if not val else 100.0 * sum(r["detectada"] == r["esperada"] for r in val) / len(val)
    assert abs(compute_precision(rows) - expected) < 1e-9
    # Las no validadas no influyen
    assert compute_precision(rows) == compute_precision(val)
    assert 0.0 <= compute_precision(rows) <= 100.0
