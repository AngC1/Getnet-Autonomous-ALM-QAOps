"""Property 20: ida y vuelta de la Incidencia."""
import json

from hypothesis import given, settings, strategies as st

from brand_verifier.incident import incident_from_json, incident_to_json, validate_incident

_ATM_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"

incident = st.fixed_dictionaries({
    "id": st.uuids().map(str),
    "descripcion": st.text(min_size=1, max_size=2000),
    "atm_id": st.text(alphabet=_ATM_CHARS, min_size=1, max_size=50),
    "ubicacion": st.text(min_size=1, max_size=200),
    "fecha_hora": st.sampled_from([
        "2025-01-01T10:00:00+01:00", "2025-06-30T23:59:59Z",
        "2030-12-31T00:00:00-05:00", "2025-01-01T10:00:00.123456+00:00",
    ]),
})


# Feature: atm-card-incident-video-simulation, Property 20: parsear la serializacion JSON de una Incidencia valida y volver a serializar produce un objeto equivalente
@settings(max_examples=200, deadline=None)
@given(incident)
def test_incident_roundtrip(inc):
    s = incident_to_json(inc)
    parsed = incident_from_json(s)
    assert parsed == inc
    assert incident_to_json(parsed) == s
    assert json.loads(s) == inc
    assert validate_incident(parsed) == []


# Feature: atm-card-incident-video-simulation, Property 20: un JSON que no es objeto se rechaza
@settings(max_examples=100, deadline=None)
@given(st.one_of(st.integers(), st.lists(st.integers()), st.text(), st.none()))
def test_non_object_json_rejected(value):
    try:
        incident_from_json(json.dumps(value))
    except ValueError:
        return
    raise AssertionError("debia rechazar un JSON que no es objeto")
