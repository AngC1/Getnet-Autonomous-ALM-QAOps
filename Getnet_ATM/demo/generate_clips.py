#!/usr/bin/env python3
"""Genera con el ComfyUI del equipo los clips de la cámara de seguridad del cajero.

1. `product-shot`: una imagen fija de la cámara (mismo encuadre para todo el vídeo).
2. `image-to-video` (Wan2.2, 5 s a 16 fps) desde esa imagen: escenas normales y la manipulación.

Los resultados van a /tmp/atm_live/clips y a s3://<bucket>/live/clips/ (no al repo).
Es reanudable: si un clip ya existe en local no se vuelve a generar.
La GPU es compartida: se lanza un trabajo cada vez.

Uso:  python3 demo/generate_clips.py [--only tamper] [--force]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "comfyui"))
import client as comfy  # noqa: E402

OUT = Path("/tmp/atm_live/clips")
BUCKET = "me-hack-media-385927210791-us-east-1"
W, H = 832, 480

STYLE = ("Fixed wall-mounted security camera, high angle, wide shot of a street ATM built into a "
         "bank facade at night, sodium street lights, slight CCTV grain, realistic surveillance footage. "
         "The camera does not move. No text, no logos.")

BASE_PROMPT = (f"{STYLE} The ATM screen glows, card slot and keypad clearly visible in the centre, "
               "empty pavement in front of the machine.")

CLIPS = {
    "idle": "The camera stays perfectly still. Nobody is at the ATM. A car's headlights pass in the "
            "background, light flickers slightly, leaves move on the pavement. No people near the machine.",
    "customer_a": "The camera stays still. A woman in a beige coat walks up to the ATM, inserts a bank card, "
                  "types on the keypad, takes the banknotes and her card, and walks away out of frame.",
    "customer_b": "The camera stays still. A man in a grey jacket with a backpack walks to the ATM, uses the "
                  "touch screen and keypad briefly, takes his card back and leaves to the right.",
    "passerby": "The camera stays still. Two pedestrians walk past along the pavement behind the ATM without "
                "stopping. Nobody touches the machine.",
    "tamper": "The camera stays still. A person in a dark hooded sweatshirt and gloves walks up, looks over "
              "both shoulders nervously, presses a thin plastic overlay onto the card slot, sticks a small "
              "black strip above the keypad, checks it, then walks away quickly. The devices stay attached.",
}


def comfy_connection() -> tuple[str, str]:
    cfn = boto3.client("cloudformation", region_name="us-east-2")
    outs = {o["OutputKey"]: o["OutputValue"]
            for s in cfn.describe_stacks()["Stacks"] for o in s.get("Outputs", [])}
    token = boto3.client("secretsmanager", region_name="us-east-2").get_secret_value(
        SecretId=outs["AgentTokenSecret"])["SecretString"]
    return outs["AgentUrl"].rstrip("/"), token


def graph_for(slug: str, overrides: dict) -> dict:
    catalog = json.loads((ROOT / "comfyui/catalog.json").read_text())["workflows"]
    entry = next(w for w in catalog if w["slug"] == slug)
    graph = json.loads((ROOT / f"comfyui/workflows/{slug}.json").read_text())
    return comfy.apply_overrides(graph, entry["inputs"], overrides)


def run(url: str, token: str, slug: str, overrides: dict, target: Path) -> Path:
    tmp = OUT / f"_{target.stem}"
    files = comfy.run_workflow(url, graph_for(slug, overrides), out_dir=tmp, token=token, timeout_s=1500)
    media = [f for f in files if f.suffix.lower() in (".mp4", ".png", ".jpg", ".webp", ".webm")]
    if not media:
        raise RuntimeError(f"{slug} no devolvió ningún archivo: {files}")
    shutil.move(str(media[0]), target.with_suffix(media[0].suffix))
    shutil.rmtree(tmp, ignore_errors=True)
    return target.with_suffix(media[0].suffix)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="generar solo estos clips")
    ap.add_argument("--force", action="store_true", help="regenerar aunque existan")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    url, token = comfy_connection()
    s3 = boto3.client("s3", region_name="us-east-1")

    base = next(iter(OUT.glob("base.*")), None)
    if base is None or args.force and not args.only:
        print("[*] Imagen base de la cámara…", flush=True)
        base = run(url, token, "product-shot", {"prompt": BASE_PROMPT, "width": W, "height": H}, OUT / "base")
        s3.upload_file(str(base), BUCKET, f"live/clips/{base.name}")
    print(f"[ok] base: {base}", flush=True)
    image_name = comfy.upload_image(url, base, token)

    for name, motion in CLIPS.items():
        if args.only and name not in args.only:
            continue
        target = OUT / f"{name}.mp4"
        if target.exists() and not args.force:
            print(f"[skip] {name}", flush=True)
            continue
        print(f"[*] Clip {name}…", flush=True)
        path = run(url, token, "image-to-video",
                   {"image": image_name, "prompt": f"{STYLE} {motion}", "width": W, "height": H, "frames": 81},
                   OUT / name)
        s3.upload_file(str(path), BUCKET, f"live/clips/{path.name}")
        print(f"[ok] {name}: {path}", flush=True)
    print("[done]", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
