"""Tests unitarios del Gestor_Secretos (brand_verifier/secrets.py).

Usan clientes falsos y valores ficticios generados en cada test; nunca valores reales.
Requisitos: 5.6, 10.1, 10.2, 10.4.
"""
import threading
import time
import uuid

import pytest

from brand_verifier import secrets as sec


def fake_value(prefix: str = "val") -> str:
    return "%s-%s" % (prefix, uuid.uuid4().hex)


class FakeCfn:
    def __init__(self, outputs=None, error=None, block=None):
        self.outputs = outputs or {}
        self.error = error
        self.block = block
        self.calls = 0

    def describe_stacks(self, **kwargs):
        self.calls += 1
        if self.block is not None:
            self.block.wait(10)
        if self.error:
            raise self.error
        outs = [{"OutputKey": k, "OutputValue": v} for k, v in self.outputs.items()]
        return {"Stacks": [{"Outputs": outs}]}


class FakeSm:
    def __init__(self, secrets=None, error=None):
        self.secrets = secrets or {}
        self.error = error
        self.requested = []

    def get_secret_value(self, SecretId):
        self.requested.append(SecretId)
        if self.error:
            raise self.error
        return {"SecretString": self.secrets.get(SecretId)}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for var in (sec.ENV_AGENT_URL, sec.ENV_AGENT_TOKEN):
        monkeypatch.delenv(var, raising=False)
    sec.set_clients()
    sec.clear_registered_secrets()
    yield
    sec.set_clients()
    sec.clear_registered_secrets()


# ---------------------------------------------------------------- orden de fuentes
def test_agent_url_prefers_cloudformation_over_env(monkeypatch):
    cfn_val, env_val = fake_value("cfn"), fake_value("env")
    monkeypatch.setenv(sec.ENV_AGENT_URL, env_val)
    sec.set_clients(cloudformation=FakeCfn({sec.AGENT_URL_OUTPUT: cfn_val}), secretsmanager=FakeSm())
    assert sec.get_agent_url() == cfn_val


def test_agent_url_falls_back_to_env_when_cfn_fails(monkeypatch):
    env_val = fake_value("env")
    monkeypatch.setenv(sec.ENV_AGENT_URL, env_val)
    sec.set_clients(cloudformation=FakeCfn(error=RuntimeError("boom")), secretsmanager=FakeSm())
    assert sec.get_agent_url() == env_val


def test_agent_url_falls_back_to_env_when_output_missing(monkeypatch):
    env_val = fake_value("env")
    monkeypatch.setenv(sec.ENV_AGENT_URL, env_val)
    sec.set_clients(cloudformation=FakeCfn({}), secretsmanager=FakeSm())
    assert sec.get_agent_url() == env_val


def test_agent_token_prefers_secrets_manager_over_env(monkeypatch):
    secret_id, token, env_val = fake_value("id"), fake_value("tok"), fake_value("env")
    monkeypatch.setenv(sec.ENV_AGENT_TOKEN, env_val)
    sm = FakeSm({secret_id: token})
    sec.set_clients(cloudformation=FakeCfn({sec.AGENT_TOKEN_SECRET_OUTPUT: secret_id}), secretsmanager=sm)
    assert sec.get_agent_token() == token
    assert sm.requested == [secret_id]


def test_agent_token_falls_back_to_env_when_secrets_manager_fails(monkeypatch):
    secret_id, env_val = fake_value("id"), fake_value("env")
    monkeypatch.setenv(sec.ENV_AGENT_TOKEN, env_val)
    sec.set_clients(
        cloudformation=FakeCfn({sec.AGENT_TOKEN_SECRET_OUTPUT: secret_id}),
        secretsmanager=FakeSm(error=RuntimeError("denied")),
    )
    assert sec.get_agent_token() == env_val


def test_agent_token_falls_back_to_env_when_cfn_fails(monkeypatch):
    env_val = fake_value("env")
    monkeypatch.setenv(sec.ENV_AGENT_TOKEN, env_val)
    sec.set_clients(cloudformation=FakeCfn(error=RuntimeError("x")), secretsmanager=FakeSm())
    assert sec.get_agent_token() == env_val


def test_resolved_value_is_registered_for_redaction():
    val = fake_value("cfn")
    sec.set_clients(cloudformation=FakeCfn({sec.AGENT_URL_OUTPUT: val}), secretsmanager=FakeSm())
    sec.get_agent_url()
    assert val not in sec.redact("valor=%s" % val)


# ---------------------------------------------------------------- mensaje de error
def test_secret_not_found_contains_only_name(monkeypatch):
    # Ninguna fuente tiene valor; el entorno trae un valor ficticio en otra variable
    leaked = fake_value("other")
    monkeypatch.setenv("UNRELATED_VAR", leaked)
    sec.set_clients(cloudformation=FakeCfn({}), secretsmanager=FakeSm())
    with pytest.raises(sec.SecretNotFound) as exc:
        sec.get_agent_token()
    assert str(exc.value) == sec.AGENT_TOKEN_SECRET_OUTPUT
    assert exc.value.name == sec.AGENT_TOKEN_SECRET_OUTPUT
    assert leaked not in repr(exc.value)


def test_secret_not_found_does_not_include_secret_id_or_value():
    secret_id = fake_value("id")
    sec.set_clients(
        cloudformation=FakeCfn({sec.AGENT_TOKEN_SECRET_OUTPUT: secret_id}),
        secretsmanager=FakeSm({}),  # SecretString None
    )
    with pytest.raises(sec.SecretNotFound) as exc:
        sec.get_agent_token()
    assert secret_id not in str(exc.value) and secret_id not in repr(exc.value)


def test_get_optional_not_found_reports_name_only():
    sec.set_clients(cloudformation=FakeCfn({}), secretsmanager=FakeSm())
    with pytest.raises(sec.SecretNotFound) as exc:
        sec.get_optional("OptionalThing")
    assert str(exc.value) == "OptionalThing"


def test_get_optional_reads_cfn_then_env(monkeypatch):
    env_val = fake_value("env")
    monkeypatch.setenv("OptionalThing", env_val)
    sec.set_clients(cloudformation=FakeCfn({}), secretsmanager=FakeSm())
    assert sec.get_optional("OptionalThing") == env_val
    cfn_val = fake_value("cfn")
    sec.set_clients(cloudformation=FakeCfn({"OptionalThing": cfn_val}), secretsmanager=FakeSm())
    assert sec.get_optional("OptionalThing") == cfn_val


# ---------------------------------------------------------------- valores vacios
@pytest.mark.parametrize("empty", ["", "   ", "\n\t"])
def test_empty_env_value_is_not_found(monkeypatch, empty):
    monkeypatch.setenv(sec.ENV_AGENT_URL, empty)
    sec.set_clients(cloudformation=FakeCfn({}), secretsmanager=FakeSm())
    with pytest.raises(sec.SecretNotFound):
        sec.get_agent_url()


def test_empty_cfn_output_falls_through_to_env(monkeypatch):
    env_val = fake_value("env")
    monkeypatch.setenv(sec.ENV_AGENT_URL, env_val)
    sec.set_clients(cloudformation=FakeCfn({sec.AGENT_URL_OUTPUT: ""}), secretsmanager=FakeSm())
    assert sec.get_agent_url() == env_val


def test_empty_secret_string_is_not_found():
    secret_id = fake_value("id")
    sec.set_clients(
        cloudformation=FakeCfn({sec.AGENT_TOKEN_SECRET_OUTPUT: secret_id}),
        secretsmanager=FakeSm({secret_id: ""}),
    )
    with pytest.raises(sec.SecretNotFound):
        sec.get_agent_token()


def test_empty_values_are_not_registered_for_redaction(monkeypatch):
    monkeypatch.setenv(sec.ENV_AGENT_URL, "  ")
    sec.set_clients(cloudformation=FakeCfn({}), secretsmanager=FakeSm())
    with pytest.raises(sec.SecretNotFound):
        sec.get_agent_url()
    assert sec.redact("texto normal") == "texto normal"


# ---------------------------------------------------------------- timeout total
def test_default_timeout_is_30_seconds():
    assert sec.TIMEOUT_S == 30.0


def test_blocking_client_triggers_timeout_not_found():
    release = threading.Event()
    try:
        sec.set_clients(cloudformation=FakeCfn(block=release), secretsmanager=FakeSm())
        start = time.monotonic()
        with pytest.raises(sec.SecretNotFound) as exc:
            sec.get_agent_url(timeout_s=0.3)
        elapsed = time.monotonic() - start
    finally:
        release.set()
    assert str(exc.value) == sec.AGENT_URL_OUTPUT
    assert elapsed < 3


def test_timeout_is_total_across_sources(monkeypatch):
    """El plazo es global: con la primera fuente bloqueada, el entorno ya no se consulta."""
    release = threading.Event()
    monkeypatch.setenv(sec.ENV_AGENT_URL, fake_value("env"))
    try:
        sec.set_clients(cloudformation=FakeCfn(block=release), secretsmanager=FakeSm())
        with pytest.raises(sec.SecretNotFound):
            sec.get_agent_url(timeout_s=0.2)
    finally:
        release.set()
