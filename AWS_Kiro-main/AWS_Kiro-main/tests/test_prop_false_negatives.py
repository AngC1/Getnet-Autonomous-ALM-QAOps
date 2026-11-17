"""Property 15: Falsos negativos separados.

**Validates: Requirements 9.6**
"""
import html
import re

from hypothesis import given, settings

from brand_verifier.report import render_report
from tests._report_strategies import rows_st, section


# Feature: atm-card-incident-video-simulation, Property 15: Falsos negativos separados
@settings(max_examples=200)
@given(rows_st())
def test_false_negative_section(rows):
    out = render_report(rows, {})
    got = [html.unescape(i) for i in re.findall(r'<tr data-id="([^"]*)"', section(out, "falsos-negativos"))]
    exp = [r["id"] for r in rows if r["esperada"] == "INCORRECTO" and r["detectada"] == "CORRECTO"]
    assert got == exp
