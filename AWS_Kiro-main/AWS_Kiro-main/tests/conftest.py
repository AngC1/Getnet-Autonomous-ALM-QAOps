from __future__ import annotations

import io
import json

from PIL import Image


def png_bytes(color=(200, 30, 30), size=(32, 32), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


def make_refs(directory):
    """Genera ambos logos de referencia (WebP) con Pillow en ``directory``."""
    from brand_verifier.references import LOGO_CORRECTO, LOGO_INCORRECTO

    directory.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 40), (0, 0, 255)).save(directory / LOGO_CORRECTO, "WEBP")
    Image.new("RGB", (40, 40), (255, 0, 0)).save(directory / LOGO_INCORRECTO, "WEBP")
    return directory


def verdict_response(veredicto="CORRECTO", text=None):
    if text is None:
        evs = [] if veredicto == "SIN_LOGO" else [
            {"timestamp_s": 0, "bbox": [0.1, 0.1, 0.5, 0.5],
             "logo_detectado": "INCORRECTO" if veredicto == "INCORRECTO" else "CORRECTO"}]
        rec = "Sustituir el logotipo por Ayesa Digital." if veredicto == "INCORRECTO" else "Sin cambios."
        text = json.dumps({"veredicto": veredicto, "confianza": 0.9, "evidencias": evs,
                           "recomendacion": rec})
    return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}}


class FakeBedrock:
    """Cliente bedrock-runtime falso: ``script`` es una lista de respuestas o excepciones."""

    def __init__(self, script=None, default=None):
        self.script = list(script or [])
        self.default = default
        self.requests = []

    def converse(self, **kwargs):
        self.requests.append(kwargs)
        item = self.script.pop(0) if self.script else self.default
        if isinstance(item, BaseException):
            raise item
        return item if item is not None else verdict_response("CORRECTO")
