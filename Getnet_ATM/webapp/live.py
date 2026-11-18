"""Simulación de cámara en directo + detector de manipulación en tiempo real.

- El vídeo de 2 minutos se "emite" a velocidad real: la posición en directo es
  (ahora - t0) * speed. El navegador reproduce el mismo archivo sincronizado con t0.
- Cada SAMPLE_EVERY_S segundos de vídeo, el detector toma el fotograma actual y el de
  1 s antes y pregunta a un modelo rápido de Bedrock (Claude Haiku 4.5) si hay manipulación.
- Con CONFIRM muestras positivas seguidas se confirma la detección. Se espera a que el
  directo llegue a detección + POST_S, se corta [detección - PRE_S, detección + POST_S]
  con ffmpeg y se entrega como incidencia al pipeline de análisis completo.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import boto3
import cv2
import imageio_ffmpeg
from botocore.config import Config

log = logging.getLogger("atm_live")

DETECTOR_MODEL = os.environ.get("ATM_DETECTOR_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
SAMPLE_EVERY_S = 2.0
CONFIRM = 2
CLEAR_AFTER = 2  # negativos seguidos para volver a "comportamiento normal"
MIN_CONFIDENCE = 0.6
PRE_S = 10.0
POST_S = 8.0
REF_AT_S = 3.0
LOCAL_VIDEO = Path("/tmp/atm_live/atm_cam_live.mp4")
CLIP_DIR = Path("/tmp/atm_live/cuts")

DETECTOR_PROMPT = (
    "Eres el detector en tiempo real de una cámara de seguridad fija que enfoca un cajero automático en la calle. "
    "Recibes 3 imágenes: REFERENCIA (el cajero vacío y en buen estado), ANTERIOR (hace 1 s) y ACTUAL.\n"
    "Decide si en ANTERIOR/ACTUAL hay un INTENTO DE MANIPULACIÓN del cajero (instalar skimmer o carcasa en la "
    "ranura, tiras o cámaras sobre el teclado, forzar o dañar el frontal).\n"
    "Indicadores de manipulación (varios juntos = manipulación):\n"
    "- capucha que oculta la cara, guantes, mirar alrededor o por encima del hombro;\n"
    "- manos presionando o colocando algo en el marco de la ranura de tarjeta, el teclado o el frontal, "
    "en lugar de usar la pantalla o recoger billetes;\n"
    "- objetos o cambios en el frontal respecto a la REFERENCIA.\n"
    "Uso legítimo (NO es manipulación): cliente a cara descubierta que mete la tarjeta, teclea, mira la pantalla "
    "o recoge billetes; peatones que pasan; cajero vacío sin cambios respecto a la REFERENCIA.\n"
    'Responde solo JSON: {"manipulation": true|false, "confidence": 0-1, '
    '"observation": "máx. 15 palabras en español, describe lo que ves"}'
)


def classify(bedrock, model_id: str, ref: bytes, prev: bytes, cur: bytes) -> dict:
    content = [{"text": DETECTOR_PROMPT}]
    for label, b in (("REFERENCIA", ref), ("ANTERIOR", prev), ("ACTUAL", cur)):
        content += [{"text": f"{label}:"}, {"image": {"format": "jpeg", "source": {"bytes": b}}}]
    resp = bedrock.converse(modelId=model_id, messages=[{"role": "user", "content": content}],
                            inferenceConfig={"maxTokens": 150, "temperature": 0})
    return _parse("".join(c.get("text", "") for c in resp["output"]["message"]["content"]))


def _jpeg(frame, max_side: int = 640) -> bytes:
    h, w = frame.shape[:2]
    s = max_side / max(h, w)
    if s < 1:
        frame = cv2.resize(frame, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()


def _parse(text: str) -> dict:
    a, b = text.find("{"), text.rfind("}")
    d = json.loads(text[a:b + 1])
    return {"manipulation": bool(d.get("manipulation")),
            "confidence": float(d.get("confidence", 0) or 0),
            "observation": str(d.get("observation", ""))[:160]}


class LiveSession:
    def __init__(self, s3, bucket: str, video_key: str, on_clip: Callable[[Path, dict], str]):
        self.s3, self.bucket, self.video_key, self.on_clip = s3, bucket, video_key, on_clip
        self.bedrock = boto3.client("bedrock-runtime", region_name="us-east-1",
                                    config=Config(read_timeout=15, connect_timeout=5, retries={"max_attempts": 1}))
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.lock = threading.Lock()
        self._reset()

    # ------------------------------------------------------------------ estado
    def _reset(self):
        self.state = "IDLE"
        self.t0 = None
        self.speed = 1.0
        self.duration = None
        self.samples: list[dict] = []
        self.detection: dict | None = None
        self.incident_id: str | None = None
        self.error: str | None = None
        self.run_id = None
        self.ended = False
        # Alerta en directo, independiente del corte/informe: NONE -> ACTIVE <-> CLEARED
        self.alert = "NONE"
        self.alert_events: list[dict] = []

    def snapshot(self) -> dict:
        with self.lock:
            pos = None
            if self.t0 is not None:
                pos = max(0.0, min((time.time() - self.t0) * self.speed, self.duration or 0))
            return {
                "state": self.state, "t0": self.t0, "server_now": time.time(), "speed": self.speed,
                "position_s": pos, "duration_s": self.duration, "detector_model": DETECTOR_MODEL,
                "sample_every_s": SAMPLE_EVERY_S, "confirm": CONFIRM, "pre_s": PRE_S, "post_s": POST_S,
                "samples": sorted(self.samples, key=lambda s: s["t"])[-60:],
                "detection": self.detection, "incident_id": self.incident_id, "error": self.error,
                "ended": self.ended, "clear_after": CLEAR_AFTER,
                "alert": {"state": self.alert, "events": list(self.alert_events),
                          "normal_since_s": next((e["t"] for e in reversed(self.alert_events)
                                                  if e["type"] == "NORMAL"), None) if self.alert == "CLEARED" else None},
            }

    def _set(self, **kw):
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, v)

    # ------------------------------------------------------------------ control
    def start(self, speed: float = 1.0, lead_s: float = 0.0) -> dict:
        self._reset()  # reinicia cualquier emisión anterior (sus hilos ven otro run_id y terminan)
        run_id = time.time()
        self._set(state="STARTING", speed=speed, run_id=run_id)
        if not LOCAL_VIDEO.exists():
            LOCAL_VIDEO.parent.mkdir(parents=True, exist_ok=True)
            self.s3.download_file(self.bucket, self.video_key, str(LOCAL_VIDEO))
        cap = cv2.VideoCapture(str(LOCAL_VIDEO))
        fps = cap.get(cv2.CAP_PROP_FPS) or 16
        duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
        # Fotograma de referencia: el cajero vacío al inicio de la emisión
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(REF_AT_S * fps))
        ok, ref = cap.read()
        cap.release()
        if not ok:
            raise RuntimeError("No se pudo leer el fotograma de referencia")
        self.ref_frame = _jpeg(ref)
        self._set(duration=duration, t0=time.time() + lead_s / speed, state="LIVE")
        threading.Thread(target=self._run, args=(run_id,), daemon=True).start()
        return self.snapshot()

    def stop(self):
        self._set(state="IDLE", run_id=None, t0=None)

    # ------------------------------------------------------------------ bucle
    def _pos(self) -> float:
        return (time.time() - self.t0) * self.speed

    def _wait_until(self, video_s: float, run_id) -> bool:
        while self.run_id == run_id and self._pos() < video_s:
            time.sleep(0.05)
        return self.run_id == run_id

    def _run(self, run_id):
        cap = cv2.VideoCapture(str(LOCAL_VIDEO))
        fps = cap.get(cv2.CAP_PROP_FPS) or 16
        try:
            next_t = SAMPLE_EVERY_S
            # Se sigue analizando hasta el final, también después de la alerta
            while self.run_id == run_id:
                if next_t > self.duration - 0.5:
                    break
                if not self._wait_until(next_t, run_id):
                    return
                frames = []
                for t in (next_t - 1.0, next_t):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
                    ok, f = cap.read()
                    if ok:
                        frames.append(_jpeg(f))
                if len(frames) == 2:
                    self.pool.submit(self._classify, run_id, round(next_t, 2), frames)
                next_t += SAMPLE_EVERY_S
            # Fin de la emisión
            if not self._wait_until(self.duration, run_id):
                return
            with self.lock:
                self.ended = True
                if self.state in ("LIVE", "DETECTED", "ANALYZING"):
                    self.state = "FINISHED"
        except Exception as e:  # noqa: BLE001
            log.exception("Fallo en la sesión en directo")
            self._set(state="ERROR", error=str(e)[:300])
        finally:
            cap.release()

    def _classify(self, run_id, t: float, frames: list[bytes]):
        started = time.time()
        sample = {"t": t, "status": "pending"}
        with self.lock:
            if self.run_id != run_id:
                return
            self.samples.append(sample)
        try:
            sample.update(classify(self.bedrock, DETECTOR_MODEL, self.ref_frame, *frames), status="ok")
        except Exception as e:  # noqa: BLE001
            sample.update(status="error", observation=str(e)[:120], manipulation=False, confidence=0)
        sample["latency_s"] = round(time.time() - started, 2)
        sample["positive"] = bool(sample.get("manipulation")) and sample.get("confidence", 0) >= MIN_CONFIDENCE
        log.info("t=%.1fs %s %.2f %s (%.1fs)", t, "POS" if sample["positive"] else "neg",
                 sample.get("confidence", 0), sample.get("observation", ""), sample["latency_s"])
        self._check_detection(run_id)

    def _check_detection(self, run_id):
        with self.lock:
            if self.run_id != run_id:
                return
            # Solo el tramo contiguo de muestras ya resueltas (las respuestas pueden llegar desordenadas)
            done = []
            for s in sorted(self.samples, key=lambda s: s["t"]):
                if s["status"] == "pending":
                    break
                done.append(s)
            if self.detection is not None:
                self._update_alert(done)
                return
            streak = []
            for s in done:
                streak = streak + [s] if s["positive"] else []
                if len(streak) >= CONFIRM:
                    break
            if len(streak) < CONFIRM:
                return
            onset = streak[0]["t"]
            start = max(0.0, onset - PRE_S)
            end = min(self.duration, onset + POST_S)
            self.detection = {
                "detected_at_s": onset, "confirmed_at_s": streak[-1]["t"],
                "confirmed_wall": time.time(), "observation": streak[-1]["observation"],
                "confidence": max(s["confidence"] for s in streak),
                "clip_start_s": round(start, 2), "clip_end_s": round(end, 2),
            }
            self.state = "DETECTED"
            self._update_alert(done)
        threading.Thread(target=self._cut_and_send, args=(run_id,), daemon=True).start()

    def _update_alert(self, done: list[dict]) -> None:
        """Recalcula la alerta tras la primera detección (llamar con el lock cogido).

        ACTIVE  -> CLEARED con CLEAR_AFTER negativos seguidos (el sospechoso se ha ido).
        CLEARED -> ACTIVE  con CONFIRM positivos seguidos (vuelve a haber manipulación).
        """
        det = self.detection
        state, events = "ACTIVE", [{"type": "ALERTA", "t": det["detected_at_s"],
                                    "observation": det["observation"]}]
        pos = neg = 0
        first_neg = first_pos = None
        for s in done:
            if s["t"] <= det["confirmed_at_s"]:
                continue
            if s["positive"]:
                pos, neg = pos + 1, 0
                first_pos = s if pos == 1 else first_pos
                if state == "CLEARED" and pos >= CONFIRM:
                    state = "ACTIVE"
                    events.append({"type": "ALERTA", "t": first_pos["t"], "observation": s["observation"]})
            else:
                neg, pos = neg + 1, 0
                first_neg = s if neg == 1 else first_neg
                if state == "ACTIVE" and neg >= CLEAR_AFTER:
                    state = "CLEARED"
                    events.append({"type": "NORMAL", "t": first_neg["t"], "observation": s["observation"]})
        if state != self.alert:
            log.info("Alerta %s -> %s (t=%.1fs)", self.alert, state, events[-1]["t"])
        self.alert, self.alert_events = state, events

    def _cut_and_send(self, run_id):
        det = self.detection
        try:
            # Realista: el corte se envía cuando el directo ya ha emitido el final de la ventana.
            if not self._wait_until(det["clip_end_s"], run_id):
                return
            self._set(state="CUTTING")
            CLIP_DIR.mkdir(parents=True, exist_ok=True)
            out = CLIP_DIR / f"corte_{int(det['clip_start_s'])}-{int(det['clip_end_s'])}s_{int(time.time())}.mp4"
            subprocess.run(
                [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                 "-ss", f"{det['clip_start_s']:.2f}", "-i", str(LOCAL_VIDEO),
                 "-t", f"{det['clip_end_s'] - det['clip_start_s']:.2f}",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", "-an", str(out)], check=True, timeout=60)
            incident_id = self.on_clip(out, dict(det, detector_model=DETECTOR_MODEL))
            with self.lock:
                self.incident_id = incident_id
                self.state = "FINISHED" if self.ended else "ANALYZING"
            out.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            log.exception("Fallo al cortar/enviar el clip")
            self._set(state="ERROR", error=str(e)[:300])
