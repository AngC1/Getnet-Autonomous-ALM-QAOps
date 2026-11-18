"""Tests unitarios del flujo de incidencia (sin llamadas reales a AWS)."""
import json

from brand_verifier.incident import (
    ESTADO_TRIAJE_FALLIDO,
    ESTADO_TRIAJE_OK,
    incident_from_json,
    incident_to_json,
    process_incident,
    redact_pan,
    scene_prompt,
    validate_incident,
)
from brand_verifier.s3io import S3IO

VALID = {
    "descripcion": "La tarjeta 4111 1111 1111 1111 quedo retenida.",
    "atm_id": "ATM-0042",
    "ubicacion": "Calle Mayor 1",
    "fecha_hora": "2025-01-01T10:00:00+01:00",
}
GOOD_TRIAGE = {
    "categoria": "TARJETA_RETENIDA",
    "severidad": "MEDIA",
    "causa_probable": "Fallo del lector",
    "accion_recomendada": "Enviar tecnico",
}


class FakeS3Client:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.objects[Key] = Body


class FakeBedrock:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0

    def converse(self, **kw):
        self.calls += 1
        t = self.texts.pop(0)
        if isinstance(t, Exception):
            raise t
        return {"output": {"message": {"content": [{"text": t}]}}}


def _s3():
    c = FakeS3Client()
    return S3IO(client=c, bucket="b", sleep=lambda s: None), c


def test_validate_ok_and_each_invalid_field():
    assert validate_incident(VALID) == []
    bad = dict(VALID, descripcion="", atm_id="a b", ubicacion="x" * 201, fecha_hora="2025-01-01T10:00:00")
    errs = validate_incident(bad)
    assert [e.split(":")[0] for e in errs] == ["descripcion", "atm_id", "ubicacion", "fecha_hora"]
    assert validate_incident(dict(VALID, fecha_hora="2025-01-01T10:00:00Z")) == []
    assert len(validate_incident({})) == 4


def test_redact_pan_variants():
    assert redact_pan("4111111111111111") == "************1111"
    assert redact_pan("pan 4111-1111-1111-1111 ok") == "pan ****-****-****-1111 ok"
    assert redact_pan("123456789012") == "123456789012"  # 12 digitos: intacto


def test_scene_prompt_is_clean():
    p = scene_prompt({"descripcion": "Sr. Juan Perez del Banco Santander perdio 4111 1111 1111 1111"})
    assert "Juan" not in p and "Santander" not in p and "4111" not in p


def test_roundtrip():
    s = incident_to_json(VALID)
    assert incident_to_json(incident_from_json(s)) == s


def test_process_ok_persists_redacted_and_triage():
    s3, c = _s3()
    r = process_incident(VALID, s3, FakeBedrock([json.dumps(GOOD_TRIAGE)]), model_id="m", id_factory=lambda: "i1")
    assert r.estado == ESTADO_TRIAJE_OK
    stored = json.loads(c.objects["incidents/i1/incident.json"])
    assert "4111 1111" not in stored["descripcion"] and stored["descripcion"].count("1111") == 1
    assert json.loads(c.objects["incidents/i1/triage.json"]) == GOOD_TRIAGE


def test_process_invalid_persists_nothing():
    s3, c = _s3()
    r = process_incident({}, s3, FakeBedrock([]), model_id="m")
    assert not r.ok and r.errores and c.objects == {}


def test_triage_retry_then_success_and_failure():
    s3, c = _s3()
    br = FakeBedrock(["no json", "```json\n%s\n```" % json.dumps(GOOD_TRIAGE)])
    assert process_incident(VALID, s3, br, model_id="m", id_factory=lambda: "i2").estado == ESTADO_TRIAJE_OK
    assert br.calls == 2

    s3, c = _s3()
    br = FakeBedrock([RuntimeError("x"), '{"categoria": "NOPE"}'])
    r = process_incident(VALID, s3, br, model_id="m", id_factory=lambda: "i3")
    assert r.estado == ESTADO_TRIAJE_FALLIDO and br.calls == 2
    assert "incidents/i3/incident.json" in c.objects and "incidents/i3/triage.json" not in c.objects
