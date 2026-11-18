"""Generador del Informe_Demo (Requirement 9) en HTML.

Funciones puras: ``compute_precision``, ``mean_time``, ``false_negatives``,
``build_stats`` y ``render_report``. E/S aislada en ``draw_evidence`` (Pillow),
``presign`` y ``save_report`` (via S3IO). Todo texto dinamico se escapa.

Fila ("Resultado de verificacion")::

    {"id", "tipo", "esperada", "detectada", "resultado": "aprobado|fallido",
     "confianza", "evidencia": {"frame_s", "bbox", "image_bytes"?, "url"?},
     "duracion_s", "validada"}
"""
from __future__ import annotations

import base64
import html
import io
import math
from typing import Any, Dict, List, Optional, Sequence

TARGET_PERCENT = 90.0
PRESIGN_EXPIRES_S = 3600
REPORTS_PREFIX = "brand/reports/"
LABEL_OK = "OBJETIVO ALCANZADO"
LABEL_KO = "OBJETIVO NO ALCANZADO"


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def is_match(row: Dict[str, Any]) -> bool:
    return row.get("detectada") is not None and row.get("detectada") == row.get("esperada")


# --------------------------------------------------------------------------
# Metricas puras
# --------------------------------------------------------------------------
def compute_precision(rows: Sequence[Dict[str, Any]]) -> float:
    """% de filas validadas (validada=true) cuya deteccion coincide con la esperada.

    Ignora las no validadas; 0.0 si no hay ninguna validada.
    """
    validated = [r for r in rows if r.get("validada") is True]
    if not validated:
        return 0.0
    hits = sum(1 for r in validated if is_match(r))
    return hits * 100.0 / len(validated)


def mean_time(rows: Sequence[Dict[str, Any]]) -> float:
    """Tiempo medio de verificacion (s) sobre filas con ``duracion_s`` numerico; 0 si ninguna."""
    vals = [r["duracion_s"] for r in rows if _num(r.get("duracion_s"))]
    return sum(vals) / len(vals) if vals else 0.0


def false_negatives(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Esperada INCORRECTO y detectada CORRECTO."""
    return [r for r in rows if r.get("esperada") == "INCORRECTO" and r.get("detectada") == "CORRECTO"]


def target_label(precision: float) -> str:
    return LABEL_OK if precision >= TARGET_PERCENT else LABEL_KO


def build_stats(rows: Sequence[Dict[str, Any]], failed_stage: Optional[str] = None,
                reason: Optional[str] = None) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "precision": compute_precision(rows),
        "tiempo_medio_s": mean_time(rows),
    }
    if failed_stage:
        stats["etapa_fallida"] = failed_stage
        if reason:
            stats["motivo"] = reason
    return stats


# --------------------------------------------------------------------------
# Evidencia
# --------------------------------------------------------------------------
def draw_evidence(image_bytes: bytes, bbox: Sequence[float]) -> bytes:
    """Dibuja la caja normalizada [x0,y0,x1,y1] sobre la imagen y devuelve PNG."""
    from PIL import Image, ImageDraw

    with Image.open(io.BytesIO(image_bytes)) as im:
        img = im.convert("RGB")
    w, h = img.size
    x0, y0, x1, y1 = bbox
    draw = ImageDraw.Draw(img)
    width = max(2, min(w, h) // 100)
    draw.rectangle([x0 * w, y0 * h, x1 * w, y1 * h], outline=(255, 0, 0), width=width)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def presign(client: Any, bucket: str, key: str) -> str:
    """URL prefirmada de lectura con caducidad de 3600 s."""
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=PRESIGN_EXPIRES_S
    )


def _esc(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _safe_url(url: Any) -> Optional[str]:
    if isinstance(url, str) and url.lower().startswith(("https://", "http://")):
        return url
    return None


def _evidence_ref(ev: Any) -> str:
    if not isinstance(ev, dict):
        return "sin evidencia"
    parts = []
    if "frame_s" in ev:
        parts.append("fotograma %ss" % _esc(ev.get("frame_s")))
    if ev.get("bbox") is not None:
        parts.append("caja %s" % _esc(ev.get("bbox")))
    return ", ".join(parts) or "sin evidencia"


def _evidence_img(ev: Any) -> str:
    if not isinstance(ev, dict):
        return ""
    src = None
    data = ev.get("image_bytes")
    if isinstance(data, (bytes, bytearray)) and data:
        try:
            png = draw_evidence(bytes(data), ev["bbox"]) if ev.get("bbox") else bytes(data)
            src = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        except Exception:  # noqa: BLE001 - imagen ilegible: se cae a la URL si existe
            src = None
    if src is None:
        src = _safe_url(ev.get("url"))
    if src is None:
        return ""
    return '<img class="ev-img" src="%s" alt="Evidencia con la caja del logotipo detectado" loading="lazy">' % _esc(src)


def _fmt_conf(c: Any) -> str:
    return "%.2f" % c if _num(c) else "-"


# Valores conocidos -> clase CSS (cualquier otro texto usa "otro"; nunca se interpola texto libre en class).
_VCLASS = {"CORRECTO": "ok", "INCORRECTO": "bad", "SIN_LOGO": "none", "AMBIGUO": "warn"}
_VLABEL = {"CORRECTO": "Ayesa Digital (correcto)", "INCORRECTO": "Ayesa (incorrecto)",
           "SIN_LOGO": "Sin logo", "AMBIGUO": "Ambiguo"}


def _vclass(v: Any) -> str:
    return _VCLASS.get(v, "otro") if isinstance(v, str) else "otro"


def _conf_style(c: Any) -> str:
    if not _num(c):
        return ""
    return ' style="--c:%d%%"' % round(max(0.0, min(1.0, float(c))) * 100)


def _row_html(r: Dict[str, Any]) -> str:
    ev = r.get("evidencia")
    resultado = "aprobado" if is_match(r) else "fallido"
    esperada, detectada = r.get("esperada"), r.get("detectada")
    return (
        '<tr data-id="%s"><td class="id id-%s">%s</td><td class="tipo">%s</td>'
        '<td class="v v-%s" title="%s">%s</td><td class="v v-%s" title="%s">%s</td>'
        '<td class="res res-%s">%s</td><td class="conf"%s>%s</td><td class="ev">%s%s</td></tr>'
        % (_esc(r.get("id")), resultado, _esc(r.get("id")), _esc(r.get("tipo")),
           _vclass(esperada), _esc(_VLABEL.get(esperada, esperada)), _esc(esperada),
           _vclass(detectada), _esc(_VLABEL.get(detectada, detectada)), _esc(detectada),
           resultado, resultado, _conf_style(r.get("confianza")), _fmt_conf(r.get("confianza")),
           _evidence_ref(ev), _evidence_img(ev))
    )


_HEAD = ('<thead><tr><th scope="col">Id</th><th scope="col">Tipo</th><th scope="col">Marca esperada</th>'
         '<th scope="col">Detectada</th><th scope="col">Resultado</th><th scope="col">Confianza</th>'
         '<th scope="col">Evidencia</th></tr></thead>')

# Estilos embebidos: sin fuentes, imagenes ni scripts externos (el informe se abre desde S3 o en local).
_CSS = """
:root{--brand:#1a1adb;--brand2:#4f46e5;--cyan:#06b6d4;--ink:#0f172a;--muted:#475569;--line:#e2e8f0;
--bg:#f5f7fb;--card:#fff;--ok:#047857;--ok-bg:#d1fae5;--bad:#b91c1c;--bad-bg:#fee2e2;--warn:#92400e;
--warn-bg:#fef3c7;--none:#334155;--none-bg:#e2e8f0}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,
"Helvetica Neue",Arial,sans-serif}
.hero{background:linear-gradient(135deg,#0b1020 0%,#151a6b 55%,var(--brand) 100%);color:#fff;padding:32px 40px 72px}
.hero .wrap{max-width:1180px;margin:0 auto;display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.mark{width:52px;height:52px;border-radius:14px;display:grid;place-items:center;font-weight:800;font-size:22px;
background:linear-gradient(135deg,var(--cyan),var(--brand2));box-shadow:0 8px 24px rgba(6,182,212,.35)}
.hero h1{margin:0;font-size:28px;letter-spacing:-.02em}
.hero p{margin:2px 0 0;color:#c7d2fe}
.chips{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}
.chip{padding:6px 12px;border-radius:999px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.22);
font-size:13px;white-space:nowrap}
main{max-width:1180px;margin:-48px auto 48px;padding:0 24px}
section{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:24px;margin-bottom:24px;
box-shadow:0 10px 30px rgba(15,23,42,.06)}
h2{margin:0 0 16px;font-size:18px;letter-spacing:-.01em}
.parcial{max-width:1180px;margin:-40px auto 64px;padding:14px 18px;border-radius:14px;background:var(--warn-bg);
color:var(--warn);border:1px solid #fcd34d;font-weight:600}
#resumen{display:grid;grid-template-columns:auto 1fr;gap:28px;align-items:center}
.gauge{--p:0;width:148px;height:148px;border-radius:50%;display:grid;place-items:center;
background:conic-gradient(var(--g) calc(var(--p)*1%),#e5e7eb 0)}
.gauge>div{width:116px;height:116px;border-radius:50%;background:#fff;display:grid;place-items:center;text-align:center}
.gauge strong{font-size:28px;display:block;line-height:1}
.gauge small{color:var(--muted);font-size:12px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}
.kpi{border:1px solid var(--line);border-radius:14px;padding:14px 16px;background:linear-gradient(180deg,#fff,#f8fafc)}
.kpi .k{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.kpi .n{font-size:24px;font-weight:700;margin-top:2px}
.objetivo{grid-column:1/-1;margin:0;padding:12px 16px;border-radius:12px;font-size:15px}
.objetivo.si{background:var(--ok-bg);color:var(--ok)}
.objetivo.no{background:var(--bad-bg);color:var(--bad)}
.tbl{overflow-x:auto;border:1px solid var(--line);border-radius:14px}
table{width:100%;border-collapse:collapse;font-size:14px}
thead th{position:sticky;top:0;background:#f1f5f9;color:#334155;text-align:left;font-size:12px;text-transform:uppercase;
letter-spacing:.05em;padding:12px 14px;border-bottom:1px solid var(--line)}
td{padding:12px 14px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:nth-child(even){background:#fafbff}
tbody tr:hover{background:#eef2ff}
td.id-fallido{box-shadow:inset 3px 0 0 var(--bad)}
td.id-aprobado{box-shadow:inset 3px 0 0 var(--ok)}
td.id{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px;white-space:nowrap}
td.tipo{text-transform:capitalize;color:var(--muted)}
td.v{font-weight:600;font-size:12px;letter-spacing:.03em;white-space:nowrap}
td.v::before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;
vertical-align:middle;background:currentColor}
.v-ok{color:var(--ok)}.v-bad{color:var(--bad)}.v-warn{color:var(--warn)}.v-none,.v-otro{color:var(--none)}
td.res{font-weight:700;text-transform:capitalize}
td.res-aprobado{color:var(--ok)}td.res-fallido{color:var(--bad)}
td.conf{min-width:110px;font-variant-numeric:tabular-nums;
background:linear-gradient(var(--brand2),var(--brand2)) left bottom/var(--c,0%) 3px no-repeat}
td.ev{color:var(--muted);font-size:13px;min-width:220px}
.ev-img{display:block;margin-top:8px;width:220px;max-width:100%;border-radius:10px;border:1px solid var(--line)}
#falsos-negativos{border-color:#fecaca}
#falsos-negativos h2{color:var(--bad)}
.empty{margin:0;padding:14px 16px;border-radius:12px;background:var(--ok-bg);color:var(--ok);font-weight:600}
footer{max-width:1180px;margin:0 auto 32px;padding:0 24px;color:var(--muted);font-size:12px}
@media (max-width:720px){.hero{padding:24px 20px 64px}#resumen{grid-template-columns:1fr;justify-items:center}
.chips{margin-left:0}main{padding:0 12px}}
@media print{body{background:#fff}.hero{background:#fff;color:var(--ink);padding:0 0 12px;border-bottom:3px solid var(--brand)}
.hero p{color:var(--muted)}.chip{border-color:var(--line);background:#fff}main{margin:16px 0}
section{box-shadow:none;break-inside:avoid}tbody tr:hover{background:inherit}thead th{position:static}
.gauge,.mark,td.conf,.objetivo,.empty{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


def _kpi(label: str, value: str) -> str:
    return '<div class="kpi"><div class="k">%s</div><div class="n">%s</div></div>' % (label, value)


def render_report(rows: Sequence[Dict[str, Any]], stats: Optional[Dict[str, Any]] = None) -> str:
    """HTML del informe. ``stats``: precision, tiempo_medio_s, etapa_fallida, motivo."""
    stats = dict(stats or {})
    precision = stats["precision"] if _num(stats.get("precision")) else compute_precision(rows)
    tmean = stats["tiempo_medio_s"] if _num(stats.get("tiempo_medio_s")) else mean_time(rows)
    fns = false_negatives(rows)
    total = len(rows)
    ok = sum(1 for r in rows if is_match(r))
    images = sum(1 for r in rows if r.get("tipo") == "imagen")
    reached = precision >= TARGET_PERCENT
    gauge = max(0.0, min(100.0, float(precision)))

    out = ['<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">'
           "<title>Informe Verificador de marca</title><style>%s</style></head><body>" % _CSS,
           '<header class="hero"><div class="wrap"><div class="mark" aria-hidden="true">BG</div>'
           "<div><h1>Informe Verificador de marca</h1>"
           "<p>Brand Guard &middot; Ayesa Digital es la marca correcta en todo momento</p></div>"
           '<div class="chips"><span class="chip">Amazon Bedrock &middot; us-east-1</span>'
           '<span class="chip">ComfyUI &middot; us-east-2</span>'
           '<span class="chip">Objetivo &ge; %d%%</span></div></div></header>' % int(TARGET_PERCENT)]
    if stats.get("etapa_fallida"):
        msg = "INFORME PARCIAL: etapa fallida: %s" % _esc(stats["etapa_fallida"])
        if stats.get("motivo"):
            msg += " (%s)" % _esc(stats["motivo"])
        out.append('<p class="parcial" role="alert">%s</p>' % msg)
    out.append("<main>")
    out.append(
        '<section id="resumen" aria-label="Resumen">'
        '<div class="gauge" style="--p:%.1f;--g:%s" role="img" aria-label="Precision_Global %.1f%%">'
        "<div><span><strong>%.1f%%</strong><small>Precision_Global</small></span></div></div>"
        '<div class="kpis">%s%s%s%s</div>'
        '<p class="objetivo %s"><strong>%s</strong></p></section>'
        % (gauge, "var(--ok)" if reached else "var(--bad)", precision, precision,
           _kpi("Activos verificados", "%d <small>(%d im&aacute;genes &middot; %d v&iacute;deos)</small>"
                % (total, images, total - images)),
           _kpi("Coinciden con la marca esperada", "%d / %d" % (ok, total)),
           _kpi("Tiempo medio de verificaci&oacute;n", "%.1f s" % tmean),
           _kpi("Falsos negativos", str(len(fns))),
           "si" if reached else "no", target_label(precision)))
    out.append('<section id="resultados"><h2>Resultados</h2><div class="tbl"><table>%s<tbody>%s</tbody></table></div></section>'
               % (_HEAD, "".join(_row_html(r) for r in rows)))
    out.append('<section id="falsos-negativos"><h2>Falsos negativos (error m&aacute;s grave)</h2>')
    if fns:
        out.append('<div class="tbl"><table>%s<tbody>%s</tbody></table></div>'
                   % (_HEAD, "".join(_row_html(r) for r in fns)))
    else:
        out.append('<p class="empty">Ninguno.</p>')
    out.append("</section></main>"
               "<footer>Precision_Global se calcula sobre los activos con etiqueta validada por una persona. "
               "Un solo fotograma con el logotipo incorrecto invalida el v&iacute;deo.</footer></body></html>")
    return "".join(out)


def save_report(s3: Any, html_text: str, name: str = "informe") -> str:
    """Guarda el informe en brand/reports/<name>.html via S3IO; devuelve la clave."""
    import re

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise ValueError("nombre de informe invalido")
    key = "%s%s.html" % (REPORTS_PREFIX, name)
    s3.put(key, html_text.encode("utf-8"), content_type="text/html; charset=utf-8")
    return key
