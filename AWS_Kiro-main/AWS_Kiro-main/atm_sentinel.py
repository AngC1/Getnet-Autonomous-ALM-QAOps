#!/usr/bin/env python3
"""ATM Sentinel: analiza un vídeo de cajero y devuelve un informe JSON de riesgo.

Flujo: vídeo (local o s3://) -> fotogramas clave (OpenCV) + metadatos
       -> Claude en Amazon Bedrock (Converse API, us-east-1) -> informe JSON validado.

Uso:
    python atm_sentinel.py VIDEO --atm-id ATM-MAD-0042 \
        --location "C/ Alcalá 100, Madrid" \
        --event "Objeto extraño detectado en la ranura de la tarjeta" \
        [--timestamp 2026-11-04T10:15:00+01:00] [--frames 6] [--output informe.json]

Dependencias: boto3, opencv-python-headless. Sin secretos en el código: usa la
cadena de credenciales estándar de AWS.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover - fallback cuando boto3 no está instalado localmente
    boto3 = None  # type: ignore[assignment]
    Config = Any  # type: ignore[misc,assignment]
    BotoCoreError = Exception  # type: ignore[misc,assignment]
    ClientError = Exception  # type: ignore[misc,assignment]

try:
    import cv2
except ImportError:  # pragma: no cover - fallback cuando opencv no está instalado localmente
    cv2 = None  # type: ignore[assignment]

REGION = "us-east-1"  # Bedrock denegado en us-east-2
CLIENT_NAME = "Getnet (Grupo Santander)"

# Modelo pedido primero; si la cuenta no lo ofrece se usan los siguientes (se registra).
MODEL_CANDIDATES = [
    "us.anthropic.claude-3-5-sonnet-20241022-v2:0",  # Claude 3.5 Sonnet v2
    "anthropic.claude-3-5-sonnet-20240620-v1:0",  # Claude 3.5 Sonnet v1
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",  # fallback disponible
]

RISK_LEVELS = ["BAJO", "MEDIO", "ALTO", "CRITICO"]
THREAT_TYPES = [
    "SKIMMING",  # lector/cámara clonadora
    "SHIMMING",  # dispositivo dentro de la ranura de chip
    "CARD_TRAPPING",  # retención de tarjeta (lazo libanés)
    "CASH_TRAPPING",  # bloqueo de la salida de efectivo
    "VANDALISMO_O_ATAQUE_FISICO",
    "OBSERVACION_PIN",  # shoulder surfing / cámara oculta
    "SIN_AMENAZA_APARENTE",
    "OTRA",
]

log = logging.getLogger("atm_sentinel")

SYSTEM_PROMPT = (
    "Eres un analista de seguridad de cajeros automáticos para la unidad de fraude "
    f"de {CLIENT_NAME}. Recibes fotogramas clave ordenados cronológicamente de un "
    "vídeo de un cajero y metadatos del incidente. Evalúa si hay manipulación del "
    "cajero. Basa tus conclusiones solo en lo que ves y en los metadatos; si la "
    "evidencia es insuficiente, dilo y baja la confianza. No identifiques a personas. "
    "Responde ÚNICAMENTE con un objeto JSON, sin texto adicional."
)


# --------------------------------------------------------------------------- utilidades
def mask_card_numbers(text: str) -> str:
    """Enmascara secuencias de 13-19 dígitos (también con espacios/guiones) salvo los 4 últimos."""

    def _mask(m: re.Match) -> str:
        raw = m.group(0)
        digits = sum(c.isdigit() for c in raw)
        if not 13 <= digits <= 19:
            return raw
        seen, out = 0, []
        for c in raw:
            if c.isdigit():
                seen += 1
                out.append(c if seen > digits - 4 else "*")
            else:
                out.append(c)
        return "".join(out)

    return re.sub(r"\d(?:[ -]?\d){12,18}", _mask, text)


def parse_s3_uri(uri: str) -> tuple[str, str]:
    m = re.fullmatch(r"s3://([^/]+)/(.+)", uri)
    if not m:
        raise ValueError(f"URI S3 inválida: {uri}")
    return m.group(1), m.group(2)


def resolve_video(source: str, tmpdir: str) -> str:
    """Devuelve una ruta local; descarga si es s3://."""
    if source.startswith("s3://"):
        bucket, key = parse_s3_uri(source)
        # El bucket de medios está en us-east-1; los activos en us-east-2.
        region = "us-east-2" if "us-east-2" in bucket else REGION
        local = os.path.join(tmpdir, os.path.basename(key))
        log.info("Descargando %s (puede tardar si el vídeo es grande)", source)
        boto3.client("s3", region_name=region).download_file(bucket, key, local)
        return local
    if not os.path.isfile(source) or os.path.getsize(source) == 0:
        raise FileNotFoundError(f"Vídeo no existe o está vacío: {source}")
    return source


# --------------------------------------------------------------------------- fotogramas
def extract_key_frames(video_path: str, n_frames: int = 6, max_side: int = 1024) -> list[dict]:
    """Selecciona n fotogramas clave: muestrea candidatos uniformes y conserva los de
    mayor cambio visual respecto al anterior (más probable que muestren la acción).
    El primero siempre se incluye como referencia. Devuelve JPEG en bytes."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"No se pudo abrir el vídeo: {video_path}")
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        if total <= 0:
            raise ValueError("El vídeo no contiene fotogramas legibles")

        n_candidates = min(total, max(n_frames * 4, n_frames))
        indices = sorted({int(i * (total - 1) / max(n_candidates - 1, 1)) for i in range(n_candidates)})

        candidates, prev_small = [], None
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                continue
            small = cv2.cvtColor(cv2.resize(frame, (64, 36)), cv2.COLOR_BGR2GRAY)
            score = float("inf") if prev_small is None else float(cv2.absdiff(small, prev_small).mean())
            prev_small = small
            candidates.append((idx, score, frame))
    finally:
        cap.release()

    if not candidates:
        raise ValueError("No se pudo leer ningún fotograma")

    chosen = sorted(candidates, key=lambda c: c[1], reverse=True)[:n_frames]
    chosen.sort(key=lambda c: c[0])

    frames = []
    for idx, _, frame in chosen:
        h, w = frame.shape[:2]
        scale = max_side / max(h, w)
        if scale < 1:
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            frames.append({"index": idx, "time_s": round(idx / fps, 2), "jpeg": buf.tobytes()})
    return frames


# --------------------------------------------------------------------------- Bedrock
def build_user_content(meta: dict, frames: list[dict]) -> list[dict]:
    schema = {
        "risk_level": f"uno de {RISK_LEVELS}",
        "threat_type": f"uno de {THREAT_TYPES}",
        "confidence": "número entre 0 y 1",
        "summary": "resumen de 1-3 frases (máx. 500 caracteres)",
        "evidence": ["observaciones concretas por fotograma (1-6 elementos)"],
        "recommended_actions": ["acciones para el banco (1-5 elementos)"],
    }
    text = (
        "Metadatos del incidente:\n"
        f"{json.dumps(meta, ensure_ascii=False, indent=2)}\n\n"
        f"A continuación van {len(frames)} fotogramas clave en orden cronológico "
        f"(instantes en segundos: {[f['time_s'] for f in frames]}).\n"
        "Devuelve un JSON con exactamente este esquema:\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}"
    )
    content: list[dict] = [{"text": text}]
    for i, f in enumerate(frames, 1):
        content.append({"text": f"Fotograma {i} (t={f['time_s']}s):"})
        content.append({"image": {"format": "jpeg", "source": {"bytes": f["jpeg"]}}})
    return content


def extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("La respuesta del modelo no contiene JSON")
        text = text[start : end + 1]
    return json.loads(text)


def validate_analysis(d: dict) -> dict:
    if d.get("risk_level") not in RISK_LEVELS:
        raise ValueError(f"risk_level inválido: {d.get('risk_level')!r}")
    if d.get("threat_type") not in THREAT_TYPES:
        raise ValueError(f"threat_type inválido: {d.get('threat_type')!r}")
    conf = d.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
        raise ValueError("confidence debe ser un número entre 0 y 1")
    if not isinstance(d.get("summary"), str) or not d["summary"].strip():
        raise ValueError("summary vacío")
    for key in ("evidence", "recommended_actions"):
        v = d.get(key)
        if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
            raise ValueError(f"{key} debe ser una lista no vacía de textos")
    return {k: d[k] for k in ("risk_level", "threat_type", "confidence", "summary", "evidence", "recommended_actions")}


def analyze(client, model_ids: list[str], meta: dict, frames: list[dict]) -> tuple[dict, str]:
    """Invoca el modelo. Prueba cada modelo candidato si no está disponible; para cada
    modelo reintenta una vez si la salida no es JSON válido. Devuelve (análisis, model_id)."""
    messages = [{"role": "user", "content": build_user_content(meta, frames)}]
    last_err: Exception | None = None
    for model_id in model_ids:
        for attempt in (1, 2):
            try:
                resp = client.converse(
                    modelId=model_id,
                    system=[{"text": SYSTEM_PROMPT}],
                    messages=messages,
                    inferenceConfig={"maxTokens": 1500, "temperature": 0.1},
                )
                out = resp["output"]["message"]["content"]
                text = "".join(b.get("text", "") for b in out)
                return validate_analysis(extract_json(text)), model_id
            except (ValueError, json.JSONDecodeError) as e:  # salida inválida: reintento único
                last_err = e
                log.warning("Salida inválida de %s (intento %d/2): %s", model_id, attempt, e)
            except ClientError as e:
                last_err = e
                code = e.response["Error"]["Code"]
                log.warning("Modelo %s no utilizable (%s); probando siguiente", model_id, code)
                break  # pasa al siguiente modelo
            except BotoCoreError as e:
                last_err = e
                log.warning("Error de red/SDK con %s: %s", model_id, e)
                break
    raise RuntimeError(f"Ningún modelo produjo un análisis válido: {last_err}")


# --------------------------------------------------------------------------- principal
def build_meta(atm_id: str, location: str, event: str, timestamp: str) -> dict:
    return {
        "atm_id": atm_id.strip(),
        "location": location.strip(),
        "tamper_event": mask_card_numbers(event.strip()),
        "event_timestamp": timestamp,
        "client": CLIENT_NAME,
    }


def bedrock_client():
    return boto3.client(
        "bedrock-runtime",
        region_name=REGION,
        config=Config(read_timeout=60, retries={"max_attempts": 3, "mode": "standard"}),
    )


def assemble_report(meta: dict, analysis: dict, model_used: str, video: str, frames: list[dict]) -> dict:
    return {
        "client": CLIENT_NAME,
        "atm_id": meta["atm_id"],
        "location": meta["location"],
        "tamper_event": meta["tamper_event"],
        "event_timestamp": meta["event_timestamp"],
        **analysis,
        "analysis": {
            "model_id": model_used,
            "region": REGION,
            "video": video,
            "frames_analyzed": [
                {k: f[k] for k in ("index", "time_s", "s3_key") if k in f} for f in frames
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    }


def build_report(args: argparse.Namespace) -> dict:
    meta = build_meta(args.atm_id, args.location, args.event, args.timestamp)
    model_ids = [args.model_id] if args.model_id else MODEL_CANDIDATES

    with tempfile.TemporaryDirectory() as tmp:
        video = resolve_video(args.video, tmp)
        frames = extract_key_frames(video, args.frames)
    log.info("Extraídos %d fotogramas clave: %s", len(frames), [f["time_s"] for f in frames])

    analysis, model_used = analyze(bedrock_client(), model_ids, meta, frames)
    return assemble_report(meta, analysis, model_used, args.video, frames)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Informe de riesgo de vídeo de cajero con Bedrock")
    p.add_argument("video", help="Ruta local o URI s3:// del vídeo")
    p.add_argument("--atm-id", required=True, help="ID del cajero")
    p.add_argument("--location", required=True, help="Ubicación del cajero")
    p.add_argument("--event", required=True, help="Descripción del evento de manipulación")
    p.add_argument("--timestamp", default=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   help="Fecha-hora ISO 8601 del evento (por defecto: ahora UTC)")
    p.add_argument("--frames", type=int, default=6, help="Nº de fotogramas clave (1-20, defecto 6)")
    p.add_argument("--model-id", help="Forzar un modelo/perfil de inferencia concreto")
    p.add_argument("--output", help="Guardar el informe en este fichero además de imprimirlo")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    if not 1 <= args.frames <= 20:
        p.error("--frames debe estar entre 1 y 20")
    for name in ("atm_id", "location", "event"):
        if not getattr(args, name).strip():
            p.error(f"--{name.replace('_', '-')} no puede estar vacío")
    try:
        datetime.fromisoformat(args.timestamp.replace("Z", "+00:00"))
    except ValueError:
        p.error("--timestamp debe ser ISO 8601")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s", stream=sys.stderr)
    try:
        report = build_report(args)
    except (FileNotFoundError, ValueError, RuntimeError, ClientError, BotoCoreError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1
    out = json.dumps(report, ensure_ascii=False, indent=2)
    print(out)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
