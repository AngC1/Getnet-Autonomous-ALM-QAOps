"""Property 17: validacion de Incidencia."""
from datetime import datetime, timedelta, timezone

from hypothesis import given, settings, strategies as st

from brand_verifier.incident import validate_incident

_ATM_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"

descripcion_ok = st.text(min_size=1, max_size=2000)
atm_ok = st.text(alphabet=_ATM_CHARS, min_size=1, max_size=50)
ubicacion_ok = st.text(min_size=1, max_size=200)
fecha_ok = st.builds(
    lambda dt, off: dt.replace(tzinfo=timezone(timedelta(minutes=off))).isoformat(),
    st.datetimes(min_value=datetime(1971, 1, 1), max_value=datetime(2100, 1, 1)),
    st.integers(min_value=-14 * 60, max_value=14 * 60),
)

valid_incident = st.fixed_dictionaries(
    {"descripcion": descripcion_ok, "atm_id": atm_ok,
     "ubicacion": ubicacion_ok, "fecha_hora": fecha_ok}
)

bad_values = {
    "descripcion": st.one_of(st.just(""), st.text(min_size=2001, max_size=2100),
                             st.none(), st.integers()),
    "atm_id": st.one_of(st.just(""), st.text(alphabet=_ATM_CHARS, min_size=51, max_size=60),
                        st.text(min_size=1, max_size=10).filter(
                            lambda s: any(c not in _ATM_CHARS for c in s)),
                        st.none(), st.integers()),
    "ubicacion": st.one_of(st.just(""), st.text(min_size=201, max_size=260),
                           st.none(), st.integers()),
    "fecha_hora": st.one_of(
        # ISO valida pero sin zona horaria
        st.datetimes(min_value=datetime(1971, 1, 1), max_value=datetime(2100, 1, 1))
        .map(lambda d: d.isoformat()),
        st.text(max_size=30).filter(lambda s: "T" not in s),
        st.none(), st.integers(),
    ),
}


# Feature: atm-card-incident-video-simulation, Property 17: validate_incident devuelve vacio si y solo si todos los campos cumplen sus limites y la fecha es ISO 8601 con zona; si no, nombra cada campo invalido
@settings(max_examples=200, deadline=None)
@given(valid_incident)
def test_valid_incident_has_no_errors(obj):
    assert validate_incident(obj) == []


# Feature: atm-card-incident-video-simulation, Property 17: validate_incident devuelve vacio si y solo si todos los campos cumplen sus limites y la fecha es ISO 8601 con zona; si no, nombra cada campo invalido
@settings(max_examples=200, deadline=None)
@given(data=st.data(), base=valid_incident,
       fields=st.sets(st.sampled_from(sorted(bad_values)), min_size=1))
def test_invalid_fields_are_each_named(data, base, fields):
    obj = dict(base)
    for f in fields:
        obj[f] = data.draw(bad_values[f])
    errs = validate_incident(obj)
    assert {e.split(":")[0] for e in errs} == fields
    assert len(errs) == len(fields)


# Feature: atm-card-incident-video-simulation, Property 17: campos ausentes y entradas no-objeto se rechazan
@settings(max_examples=100, deadline=None)
@given(base=valid_incident, missing=st.sampled_from(["descripcion", "atm_id", "ubicacion", "fecha_hora"]))
def test_missing_field_is_named(base, missing):
    obj = {k: v for k, v in base.items() if k != missing}
    assert [e.split(":")[0] for e in validate_incident(obj)] == [missing]


# Feature: atm-card-incident-video-simulation, Property 17: entradas no-objeto se rechazan
@settings(max_examples=100, deadline=None)
@given(st.one_of(st.none(), st.integers(), st.text(), st.lists(st.integers())))
def test_non_object_rejected(obj):
    assert validate_incident(obj) != []
