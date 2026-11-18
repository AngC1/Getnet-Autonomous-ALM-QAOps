# Feature: atm-card-incident-video-simulation, Property 7: Validez del identificador de activo
"""Property 7. **Validates: Requirements 4.6**"""
import string

import pytest
from hypothesis import given, settings, strategies as st

from brand_verifier.models import is_valid_asset_id, verdict_s3_key

ALLOWED = set(string.ascii_letters + string.digits + "-_")


def oracle(s: str) -> bool:
    return 1 <= len(s) <= 64 and all(c in ALLOWED for c in s)


valid_ids = st.text(alphabet=sorted(ALLOWED), min_size=1, max_size=64)
arbitrary = st.one_of(
    st.text(max_size=100),
    st.text(alphabet=sorted(ALLOWED) + ["\n", " ", "/", ".", "é", "ñ", "日", "٣"], max_size=70),
    valid_ids.map(lambda s: s + "\n"),
    st.text(alphabet=sorted(ALLOWED), min_size=65, max_size=200),
)


@settings(max_examples=200)
@given(arbitrary)
def test_acceptance_iff_oracle(s):
    assert is_valid_asset_id(s) == oracle(s)


@settings(max_examples=200)
@given(arbitrary)
def test_verdict_key_or_error(s):
    if oracle(s):
        assert verdict_s3_key(s) == "brand/verdicts/%s.json" % s
    else:
        with pytest.raises(ValueError):
            verdict_s3_key(s)


@settings(max_examples=100)
@given(valid_ids)
def test_valid_ids_accepted(s):
    assert is_valid_asset_id(s)


@pytest.mark.parametrize("s", ["", "abc\n", "\nabc", "a b", "ñandú", "日本", "٣٤", "a" * 65, "a/b", "a.b", "../x"])
def test_known_invalid(s):
    assert not is_valid_asset_id(s)
    with pytest.raises(ValueError):
        verdict_s3_key(s)


@pytest.mark.parametrize("s", ["a", "A-_9", "a" * 64])
def test_known_valid(s):
    assert is_valid_asset_id(s)
    assert verdict_s3_key(s) == "brand/verdicts/%s.json" % s
