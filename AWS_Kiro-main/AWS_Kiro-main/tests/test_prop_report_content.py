"""Property 16: Contenido del informe.

**Validates: Requirements 9.2, 9.3**
"""
import html
import re

from hypothesis import given, settings

from brand_verifier.report import render_report
from tests._report_strategies import rows_st, section


# Feature: atm-card-incident-video-simulation, Property 16: Contenido del informe
@settings(max_examples=200)
@given(rows_st())
def test_report_content(rows):
    out = render_report(rows, {})
    assert "<script" not in out.lower()
    trs = re.findall(r'<tr data-id="[^"]*">(.*?)</tr>', section(out, "resultados"))
    assert len(trs) == len(rows)
    for r, tr in zip(rows, trs):
        cells = [html.unescape(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr)]
        assert cells[0] == r["id"]
        assert cells[1] == r["tipo"]
        assert cells[2] == r["esperada"]
        assert cells[3] == r["detectada"]
        assert cells[4] == ("aprobado" if r["detectada"] == r["esperada"] else "fallido")
        assert cells[5] == "%.2f" % r["confianza"]
        assert "fotograma %ss" % r["evidencia"]["frame_s"] in cells[6]
