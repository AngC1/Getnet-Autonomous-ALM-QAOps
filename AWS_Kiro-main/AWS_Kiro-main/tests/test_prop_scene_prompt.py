"""Property 19: el prompt de escena nunca contiene secuencias de 13+ digitos."""
import re

from hypothesis import given, settings, strategies as st

from brand_verifier.incident import scene_prompt

_LONG_RUN = re.compile(r"\d{13,}")
# Secuencias de 13+ digitos, aunque esten agrupadas con espacios o guiones.
_GROUPED_RUN = re.compile(r"\d(?:[ -]?\d){12,}")

_digits = st.text(alphabet="0123456789", min_size=13, max_size=25)
_grouped = st.lists(st.text(alphabet="0123456789", min_size=1, max_size=6),
                    min_size=3, max_size=8).map(lambda xs: " ".join(xs))
_dashed = st.lists(st.text(alphabet="0123456789", min_size=1, max_size=6),
                   min_size=3, max_size=8).map(lambda xs: "-".join(xs))
_text = st.text(max_size=300)

description = st.one_of(
    _text,
    st.builds(lambda a, d, b: "%s %s %s" % (a, d, b), _text, _digits, _text),
    st.builds(lambda a, d, b: "%s %s %s" % (a, d, b), _text, _grouped, _text),
    st.builds(lambda a, d, b: "%s %s %s" % (a, d, b), _text, _dashed, _text),
)


# Feature: atm-card-incident-video-simulation, Property 19: el prompt de escena producido no contiene secuencias de 13 o mas digitos
@settings(max_examples=300, deadline=None)
@given(description)
def test_scene_prompt_has_no_long_digit_runs(desc):
    prompt = scene_prompt({"descripcion": desc})
    assert not _LONG_RUN.search(prompt)
    assert not _GROUPED_RUN.search(prompt)


# Feature: atm-card-incident-video-simulation, Property 19: el prompt no contiene el PAN original
@settings(max_examples=150, deadline=None)
@given(digits=st.text(alphabet="0123456789", min_size=13, max_size=19))
def test_scene_prompt_drops_pan(digits):
    prompt = scene_prompt({"descripcion": "Tarjeta %s retenida" % digits})
    assert digits not in prompt


# Feature: atm-card-incident-video-simulation, Property 19: entradas no validas producen un prompt base sin fallar
@settings(max_examples=100, deadline=None)
@given(st.one_of(st.none(), st.integers(), st.text(), st.just({"descripcion": None})))
def test_scene_prompt_robust(inc):
    assert isinstance(scene_prompt(inc), str)
