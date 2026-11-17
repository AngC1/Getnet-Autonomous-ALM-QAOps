"""Estrategias hypothesis compartidas para los tests del informe."""
from hypothesis import strategies as st

VALORES = ["CORRECTO", "INCORRECTO", "SIN_LOGO", "AMBIGUO"]
_unit = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


@st.composite
def rows_st(draw, unique_ids=True, max_size=12):
    n = draw(st.integers(0, max_size))
    rows = []
    for i in range(n):
        esperada = draw(st.sampled_from(VALORES))
        detectada = draw(st.sampled_from(VALORES))
        rows.append({
            "id": "a%d-%s" % (i, draw(st.text(alphabet="abcXYZ<>&\"'_-", max_size=6))),
            "tipo": draw(st.sampled_from(["imagen", "video"])),
            "esperada": esperada,
            "detectada": detectada,
            "resultado": "aprobado" if esperada == detectada else "fallido",
            "confianza": draw(_unit),
            "evidencia": {"frame_s": draw(st.integers(0, 60)), "bbox": [0.1, 0.1, 0.5, 0.5]},
            "duracion_s": draw(st.one_of(st.none(), st.floats(0, 100, allow_nan=False))),
            "validada": draw(st.booleans()),
        })
    return rows


def section(html_text, sid):
    start = html_text.index('<section id="%s"' % sid)
    return html_text[start:html_text.index("</section>", start)]
