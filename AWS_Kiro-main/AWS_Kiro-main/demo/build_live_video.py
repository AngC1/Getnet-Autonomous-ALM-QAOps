#!/usr/bin/env python3
"""Monta el vídeo de 2 minutos de la cámara del cajero a partir de los clips de ComfyUI.

Línea temporal (120 s):
  0:00-1:30  escenas normales (cajero vacío, clientes, peatones) con fundidos cortos
  1:30       empieza la manipulación (clip `tamper` a velocidad reducida)
  después    el cajero queda quieto con los dispositivos puestos hasta 2:00

Añade aspecto CCTV (desaturado, grano, hora sobreimpresa, ID de cámara, REC) y codifica
H.264 con el ffmpeg de imageio-ffmpeg. Sube el resultado a s3://<bucket>/live/.

Uso:  python3 demo/build_live_video.py [--start-clock 23:41:00]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import boto3
import cv2
import imageio_ffmpeg
import numpy as np

CLIPS = Path("/tmp/atm_live/clips")
OUT = Path("/tmp/atm_live/atm_cam_live.mp4")
BUCKET = "me-hack-media-385927210791-us-east-1"
S3_KEY = "live/atm_cam_live.mp4"
FPS = 16
TOTAL_S = 120
TAMPER_AT_S = 90
TAMPER_SPEED = 0.6  # la manipulación dura ~8 s en vez de 5
FADE = 12  # fotogramas de fundido entre escenas (0,75 s)
CAMERA_LABEL = "CAM-01  ES_MAD_0482  C/ALCALA MADRID"

# Escenas antes de la manipulación: (clip, segundos). "hold" = plano fijo vacío (primer
# fotograma común a todos los clips, generados desde la misma imagen). None = clip entero.
# El último "hold" se recorta/alarga para que la manipulación empiece justo en 1:30.
PRE_SEQUENCE = [
    ("hold", 9), ("idle_tail", None), ("hold", 7), ("customer_b", None), ("hold", 10),
    ("passerby", None), ("hold", 9), ("customer_a", None), ("hold", 12), ("passerby", None), ("hold", 999),
]


def read_clip(name: str, size: tuple[int, int]) -> list[np.ndarray]:
    path = CLIPS / f"{name}.mp4"
    cap = cv2.VideoCapture(str(path))
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(cv2.resize(f, size) if (f.shape[1], f.shape[0]) != size else f)
    cap.release()
    if not frames:
        raise RuntimeError(f"No se pudo leer {path}")
    return frames


def retime(frames: list[np.ndarray], speed: float) -> list[np.ndarray]:
    n = int(len(frames) / speed)
    out = []
    for i in range(n):
        x = i * speed
        a, b = int(x), min(int(x) + 1, len(frames) - 1)
        w = x - int(x)
        out.append(cv2.addWeighted(frames[a], 1 - w, frames[b], w, 0) if w > 0.01 else frames[a])
    return out


def append_with_fade(timeline: list[np.ndarray], seg: list[np.ndarray]) -> None:
    if not timeline:
        timeline.extend(seg)
        return
    k = min(FADE, len(seg), len(timeline))
    for i in range(k):
        w = (i + 1) / (k + 1)
        timeline[-k + i] = cv2.addWeighted(timeline[-k + i], 1 - w, seg[i], w, 0)
    timeline.extend(seg[k:])


def cctv_look(frame: np.ndarray, t_s: float, clock0: datetime, rng: np.random.Generator) -> np.ndarray:
    gray = cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    f = cv2.addWeighted(frame, 0.35, gray, 0.65, 0)
    f = cv2.GaussianBlur(f, (3, 3), 0)
    noise = rng.normal(0, 4, f.shape[:2]).astype(np.int16)[..., None]
    f = np.clip(f.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    h, w = f.shape[:2]
    stamp = (clock0 + timedelta(seconds=t_s)).strftime("%Y-%m-%d  %H:%M:%S")
    for text, org in ((stamp, (14, 30)), (CAMERA_LABEL, (14, h - 16))):
        cv2.putText(f, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(f, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.62, (235, 235, 235), 1, cv2.LINE_AA)
    if int(t_s * 2) % 2 == 0:
        cv2.circle(f, (w - 70, 24), 7, (0, 0, 220), -1, cv2.LINE_AA)
    cv2.putText(f, "REC", (w - 56, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (235, 235, 235), 1, cv2.LINE_AA)
    return f


def build(clock0: datetime) -> dict:
    base = cv2.VideoCapture(str(CLIPS / "tamper.mp4"))
    size = (int(base.get(cv2.CAP_PROP_FRAME_WIDTH)), int(base.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    base.release()
    names = {n for n, _ in PRE_SEQUENCE if n not in ("hold", "idle_tail")} | {"tamper", "idle"}
    clips = {n: read_clip(n, size) for n in names}
    still = clips["tamper"][0]  # plano vacío, idéntico al inicio de cada clip
    clips["idle_tail"] = clips["idle"][44:]  # la cámara del clip idle se mueve al principio

    pre_frames = TAMPER_AT_S * FPS
    timeline: list[np.ndarray] = []
    for name, secs in PRE_SEQUENCE:
        if len(timeline) >= pre_frames:
            break
        seg = [still] * int(secs * FPS) if name == "hold" else clips[name]
        append_with_fade(timeline, seg[: pre_frames - len(timeline)] if name == "hold" else seg)
    del timeline[pre_frames:]

    tamper = retime(clips["tamper"], TAMPER_SPEED)
    append_with_fade(timeline, tamper)
    tamper_end_s = len(timeline) / FPS
    # Plano final: cajero tal como quedó tras la manipulación, pero sin el resto de la persona
    # que sale por la esquina inferior derecha (máscara suave con el plano vacío).
    h, w = still.shape[:2]
    mask = np.zeros((h, w), np.float32)
    mask[int(h * 0.55):, int(w * 0.62):] = 1.0
    mask = cv2.GaussianBlur(mask, (0, 0), 25)[..., None]
    last = (timeline[-1] * (1 - mask) + still * mask).astype(np.uint8)
    append_with_fade(timeline, [last] * FADE)
    while len(timeline) < TOTAL_S * FPS:  # cajero quieto con el dispositivo instalado
        timeline.append(last)
    del timeline[TOTAL_S * FPS:]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.Popen(
        [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{size[0]}x{size[1]}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "30",
         "-pix_fmt", "yuv420p", "-g", str(FPS), "-movflags", "+faststart", str(OUT)],
        stdin=subprocess.PIPE)
    rng = np.random.default_rng(7)
    for n, frame in enumerate(timeline):
        proc.stdin.write(cctv_look(frame, n / FPS, clock0, rng).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg falló al codificar")

    manifest = {
        "video_key": S3_KEY, "duration_s": TOTAL_S, "fps": FPS, "width": size[0], "height": size[1],
        "tamper_start_s": TAMPER_AT_S, "tamper_end_s": round(tamper_end_s, 2),
        "camera": CAMERA_LABEL, "clock_start": clock0.isoformat(), "pre_sequence": PRE_SEQUENCE,
    }
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.upload_file(str(OUT), BUCKET, S3_KEY, ExtraArgs={"ContentType": "video/mp4"})
    s3.put_object(Bucket=BUCKET, Key="live/manifest.json", ContentType="application/json",
                  Body=json.dumps(manifest, indent=2).encode())
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-clock", default="23:41:00", help="hora sobreimpresa al inicio (HH:MM:SS)")
    args = ap.parse_args()
    clock0 = datetime.combine(datetime.now().date(), datetime.strptime(args.start_clock, "%H:%M:%S").time())
    m = build(clock0)
    print(json.dumps(m, indent=2))
    print(f"[ok] {OUT} ({OUT.stat().st_size / 1e6:.1f} MB) -> s3://{BUCKET}/{S3_KEY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
