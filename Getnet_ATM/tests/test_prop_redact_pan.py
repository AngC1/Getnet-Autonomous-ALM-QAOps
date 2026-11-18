"""Property 18: redaccion de numeros de tarjeta."""
import re

from hypothesis import given, settings, strategies as st

from brand_verifier.incident import redact_pan

# Texto sin digitos para separar las secuencias (evita fusionarlas).
_filler = st.text(alphabet=st.characters(blacklist_categories=("Cs", "Nd", "No", "Nl"),
                                         blacklist_characters="0123456789"),
                  max_size=15)


def _group(digits, seps):
    out = []
    for i, d in enumerate(digits):
        out.append(d)
        if i < len(digits) - 1:
            out.append(seps[i])
    return "".join(out)


@st.composite
def pan(draw):
    n = draw(st.integers(min_value=13, max_value=19))
    digits = draw(st.text(alphabet="0123456789", min_size=n, max_size=n))
    seps = draw(st.lists(st.sampled_from(["", "", " ", "-"]), min_size=n, max_size=n))
    return digits, _group(digits, seps)


def _expected(digits, raw):
    keep_from = len(digits) - 4
    out, seen = [], 0
    for c in raw:
        if c.isdigit():
            out.append(c if seen >= keep_from else "*")
            seen += 1
        else:
            out.append(c)
    return "".join(out)


# Feature: atm-card-incident-video-simulation, Property 18: redact_pan deja visibles solo los ultimos 4 digitos de cada secuencia de 13-19 digitos y deja intacto el resto del texto
@settings(max_examples=300, deadline=None)
@given(prefix=_filler, suffix=_filler, p=pan())
def test_single_pan_masked_rest_intact(prefix, suffix, p):
    digits, raw = p
    # separadores no digitos entre texto y PAN para no fusionar secuencias
    text = prefix + " " + raw + " " + suffix
    result = redact_pan(text)
    assert result == prefix + " " + _expected(digits, raw) + " " + suffix
    assert len(result) == len(text)


# Feature: atm-card-incident-video-simulation, Property 18: varias secuencias en un mismo texto se redactan de forma independiente
@settings(max_examples=150, deadline=None)
@given(a=pan(), b=pan(), mid=_filler)
def test_multiple_pans(a, b, mid):
    text = "%s | %s | %s" % (a[1], mid, b[1])
    expected = "%s | %s | %s" % (_expected(*a), mid, _expected(*b))
    assert redact_pan(text) == expected


# Feature: atm-card-incident-video-simulation, Property 18: tras la redaccion no quedan mas de 4 digitos por secuencia y el texto sin digitos no cambia
@settings(max_examples=150, deadline=None)
@given(p=pan())
def test_at_most_four_digits_visible(p):
    out = redact_pan(p[1])
    assert len(re.findall(r"\d", out)) == 4
    assert re.findall(r"\d", out) == list(p[0][-4:])


# Feature: atm-card-incident-video-simulation, Property 18: texto sin secuencias largas queda intacto
@settings(max_examples=150, deadline=None)
@given(st.text(alphabet="abc xyz.,0123456789", max_size=60).filter(
    lambda s: not re.search(r"\d(?:[ -]?\d){12}", s)))
def test_short_digit_runs_unchanged(text):
    assert redact_pan(text) == text
