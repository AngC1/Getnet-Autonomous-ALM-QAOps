"""Property 21: detección de secretos sin revelarlos.

Todos los valores se generan en tiempo de ejecución; este archivo no contiene
literales con formato de credencial.
"""
import importlib.util
import os
import tempfile

from hypothesis import HealthCheck, given, settings, strategies as st

_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "check_secrets.py")
_spec = importlib.util.spec_from_file_location("check_secrets", _SCRIPT)
scanner_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scanner_mod)
scan_text = scanner_mod.scan_text
main = scanner_mod.main

_UPPER_DIGITS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_ALNUM = _UPPER_DIGITS + "abcdefghijklmnopqrstuvwxyz"


def _tail(alphabet, min_size, max_size):
    return st.text(alphabet=alphabet, min_size=min_size, max_size=max_size)


# Cada estrategia produce (línea, valor) con valor ficticio aleatorio.
_assign_gen = st.builds(
    lambda name, val, q: ('%s = %s%s%s' % (name, q, "V" + val, q), "V" + val),
    st.sampled_from(["password", "passwd", "api_key", "token", "secret_key"]),
    _tail(_ALNUM, 8, 24),
    st.sampled_from(['"', "'", ""]),
)
_aws_line = st.builds(
    lambda t: ("id: " + "AKIA" + t, "AKIA" + t), _tail(_UPPER_DIGITS, 16, 16)
)
_sk_line = st.builds(
    lambda t: ("key: " + "sk-" + t, "sk-" + t), _tail(_ALNUM, 16, 40)
)
_credential_gen = st.one_of(_assign_gen, _aws_line, _sk_line)

_filler_line = st.builds(
    lambda a, n: "linea de relleno %s %d" % (a, n),
    st.sampled_from(["alfa", "beta", "gamma", "delta"]),
    st.integers(min_value=0, max_value=9999),
)


# Feature: atm-card-incident-video-simulation, Property 21: Detección de secretos sin revelarlos
# **Validates: Requirements 10.6**
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    cred=_credential_gen,
    before=st.lists(_filler_line, max_size=8),
    after=st.lists(_filler_line, max_size=8),
)
def test_secret_reported_by_line_without_revealing_value(cred, before, after, capsys):
    line, value = cred
    text = "\n".join(before + [line] + after) + "\n"
    expected_line = len(before) + 1

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "muestra.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

        assert scan_text(text, path) == [(path, expected_line)]

        capsys.readouterr()
        rc = main([path])
        captured = capsys.readouterr()

    output = captured.out + captured.err
    assert rc != 0
    assert "%s:%d" % (path, expected_line) in output
    assert value not in output
