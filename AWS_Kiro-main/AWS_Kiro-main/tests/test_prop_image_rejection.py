# Feature: atm-card-incident-video-simulation, Property 9: Rechazo de imágenes no soportadas
"""Property 9. **Validates: Requirements 2.7**"""
from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings, strategies as st

from brand_verifier.core import MAX_IMAGE_BYTES, is_supported_image
from brand_verifier.models import VerifyError, Verdict
from brand_verifier.verifier import verify_image

from .conftest import FakeBedrock, make_refs, png_bytes

REFS = make_refs(Path(tempfile.mkdtemp()) / "brand")
BASES = {f: png_bytes(fmt=f) for f in ("PNG", "JPEG", "WEBP", "GIF", "BMP", "TIFF")}
SUPPORTED = {"PNG", "JPEG", "WEBP"}


@settings(max_examples=100, deadline=None)
@given(st.sampled_from(sorted(BASES)), st.sampled_from([-1, 0, 1]), st.booleans())
def test_rejection(fmt, delta, at_limit):
    base = BASES[fmt]
    # Relleno final: Pillow sigue abriendo la imagen; el tamano queda en el limite +/- 1.
    target = (MAX_IMAGE_BYTES + delta) if at_limit else len(base)
    data = base + b"\0" * max(0, target - len(base))
    client = FakeBedrock()
    res = verify_image(data, "asset-1", client=client, ref_dir=REFS)
    accepted = fmt in SUPPORTED and len(data) <= MAX_IMAGE_BYTES
    assert is_supported_image(fmt, len(data)) == accepted
    if accepted:
        assert isinstance(res, Verdict)
        assert len(client.requests) == 1
    else:
        assert isinstance(res, VerifyError)
        assert client.requests == []


@settings(max_examples=100)
@given(st.binary(max_size=200))
def test_garbage_never_invokes_bedrock(data):
    client = FakeBedrock()
    res = verify_image(data, "asset-1", client=client, ref_dir=REFS)
    assert isinstance(res, VerifyError)
    assert client.requests == []
