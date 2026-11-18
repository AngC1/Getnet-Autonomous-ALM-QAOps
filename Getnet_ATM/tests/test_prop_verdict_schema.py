"""Property 5: Validacion del esquema del Veredicto.

Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.8
"""
# Feature: atm-card-incident-video-simulation, Property 5: Validacion del esquema del Veredicto
import copy

from hypothesis import given, settings, strategies as st

from brand_verifier.models import Verdict, validate_verdict

VALORES = ["CORRECTO", "INCORRECTO", "SIN_LOGO", "AMBIGUO"]
LOGOS = ["CORRECTO", "INCORRECTO"]

# ---------------------------------------------------------------- estrategias
_coord = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


@st.composite
def bboxes(draw):
    a, b = sorted(draw(st.lists(_coord, min_size=2, max_size=2, unique=True)))
    c, d = sorted(draw(st.lists(_coord, min_size=2, max_size=2, unique=True)))
    return [a, c, b, d]


evidences = st.fixed_dictionaries(
    {
        "timestamp_s": st.one_of(
            st.integers(min_value=0, max_value=3600),
            st.floats(min_value=0, max_value=3600, allow_nan=False),
        ),
        "bbox": bboxes(),
        "logo_detectado": st.sampled_from(LOGOS),
    }
)

_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=400
)


@st.composite
def valid_verdicts(draw):
    valor = draw(st.sampled_from(VALORES))
    rec = draw(_text)
    if valor == "INCORRECTO":
        rec = draw(_text) + " Sustituir por Ayesa Digital " + draw(st.text(max_size=20))
        rec = rec[:500]
        if "ayesa digital" not in rec.lower():
            rec = "Ayesa Digital"
        evs = draw(st.lists(evidences, min_size=1, max_size=4))
    elif valor == "CORRECTO":
        evs = draw(st.lists(evidences, min_size=1, max_size=4))
    elif valor == "SIN_LOGO":
        evs = []
    else:
        evs = draw(st.lists(evidences, min_size=0, max_size=4))
    return {
        "veredicto": valor,
        "confianza": draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        "evidencias": evs,
        "recomendacion": rec,
    }


# ------------------------------------------------------------------ propiedades
@settings(max_examples=100)
@given(valid_verdicts())
def test_valid_objects_yield_empty_list(obj):
    assert validate_verdict(obj) == []
    # Tambien acepta la dataclass equivalente.
    assert validate_verdict(Verdict.from_dict(obj)) == []


# Mutaciones invalidas: (prefijo de campo esperado en el error, funcion mutadora)
def _bad_veredicto(o, v):
    o["veredicto"] = v
    return "veredicto"


def _bad_conf(o, v):
    o["confianza"] = v
    return "confianza"


def _bad_rec(o, v):
    o["recomendacion"] = v
    return "recomendacion"


@settings(max_examples=100)
@given(
    valid_verdicts(),
    st.one_of(st.none(), st.integers(), st.booleans(), st.text(max_size=10)).filter(
        lambda x: x not in VALORES
    ),
)
def test_invalid_veredicto_is_named(obj, bad):
    obj = copy.deepcopy(obj)
    _bad_veredicto(obj, bad)
    errs = validate_verdict(obj)
    assert any(e.startswith("veredicto") for e in errs)


@settings(max_examples=100)
@given(
    valid_verdicts(),
    st.one_of(
        st.floats(min_value=1.0001, max_value=1e6),
        st.floats(max_value=-0.0001, min_value=-1e6),
        st.just(float("nan")),
        st.just(float("inf")),
        st.none(),
        st.text(max_size=5),
        st.booleans(),
    ),
)
def test_invalid_confianza_is_named(obj, bad):
    obj = copy.deepcopy(obj)
    _bad_conf(obj, bad)
    errs = validate_verdict(obj)
    assert any(e.startswith("confianza") for e in errs)


@settings(max_examples=100)
@given(
    valid_verdicts(),
    st.one_of(
        st.just(""),
        st.text(min_size=501, max_size=700),
        st.none(),
        st.integers(),
    ),
)
def test_invalid_recomendacion_is_named(obj, bad):
    obj = copy.deepcopy(obj)
    _bad_rec(obj, bad)
    errs = validate_verdict(obj)
    assert any(e.startswith("recomendacion") for e in errs)


_bad_boxes = st.one_of(
    st.just([0.5, 0.1, 0.5, 0.9]),  # x_min == x_max
    st.just([0.1, 0.5, 0.9, 0.5]),  # y_min == y_max
    st.just([0.9, 0.1, 0.1, 0.9]),  # x_min > x_max
    st.just([-0.1, 0.0, 0.5, 0.5]),  # fuera de rango
    st.just([0.0, 0.0, 1.5, 0.5]),
    st.just([0.1, 0.1, 0.5]),  # longitud
    st.just("bbox"),
    st.none(),
)


@settings(max_examples=100)
@given(valid_verdicts().filter(lambda o: len(o["evidencias"]) > 0), _bad_boxes, st.data())
def test_invalid_bbox_is_named(obj, bad, data):
    obj = copy.deepcopy(obj)
    i = data.draw(st.integers(min_value=0, max_value=len(obj["evidencias"]) - 1))
    obj["evidencias"][i]["bbox"] = bad
    errs = validate_verdict(obj)
    assert any(e.startswith("evidencias[%d].bbox" % i) for e in errs)


@settings(max_examples=100)
@given(valid_verdicts().filter(lambda o: o["veredicto"] == "INCORRECTO"))
def test_incorrecto_without_evidence_or_ayesa(obj):
    sin_ev = copy.deepcopy(obj)
    sin_ev["evidencias"] = []
    assert any(e.startswith("evidencias") for e in validate_verdict(sin_ev))

    sin_ayesa = copy.deepcopy(obj)
    sin_ayesa["recomendacion"] = "Cambiar el logotipo"
    assert any(e.startswith("recomendacion") for e in validate_verdict(sin_ayesa))


@settings(max_examples=100)
@given(valid_verdicts().filter(lambda o: o["veredicto"] == "CORRECTO"))
def test_correcto_requires_evidence(obj):
    obj = copy.deepcopy(obj)
    obj["evidencias"] = []
    assert any(e.startswith("evidencias") for e in validate_verdict(obj))


@settings(max_examples=100)
@given(
    valid_verdicts().filter(lambda o: o["veredicto"] == "SIN_LOGO"),
    st.lists(evidences, min_size=1, max_size=3),
)
def test_sin_logo_requires_empty_evidence(obj, evs):
    obj = copy.deepcopy(obj)
    obj["evidencias"] = evs
    assert any(e.startswith("evidencias") for e in validate_verdict(obj))


@settings(max_examples=100)
@given(valid_verdicts(), st.sampled_from(["veredicto", "confianza", "evidencias", "recomendacion"]))
def test_missing_field_is_named(obj, campo):
    obj = copy.deepcopy(obj)
    del obj[campo]
    errs = validate_verdict(obj)
    assert errs and any(e.startswith(campo) for e in errs)


@settings(max_examples=100)
@given(st.one_of(st.none(), st.integers(), st.text(), st.lists(st.integers())))
def test_non_object_is_rejected(obj):
    assert validate_verdict(obj) != []
