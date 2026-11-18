#!/usr/bin/env python3
"""Convierte a H.264 (yuv420p, +faststart) los mp4 no-H.264 de brand/generated/*/ en S3
y corrige el ContentType (image/png, video/mp4) si falta.

Uso: python3 scripts/transcode_videos.py [--bucket B] [--dry-run]
Requiere imageio-ffmpeg y boto3. Sobrescribe el objeto con el mismo nombre.
"""
import argparse, os, re, subprocess, sys, tempfile
import boto3

PREFIX = "brand/generated/"
CT = {".png": "image/png", ".mp4": "video/mp4"}


def ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def video_codec(ff, path):
    """Códec de vídeo según `ffmpeg -i` (p. ej. h264, mpeg4, hevc)."""
    out = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    m = re.search(r"Video: (\w+)", out)
    return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default=os.environ.get("MEDIA_BUCKET"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.bucket:
        sys.exit("Falta --bucket o MEDIA_BUCKET")
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    ff = ffmpeg_exe()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=a.bucket, Prefix=PREFIX):
        for o in page.get("Contents", []):
            key, ext = o["Key"], os.path.splitext(o["Key"])[1].lower()
            if ext not in CT:
                continue
            ct = s3.head_object(Bucket=a.bucket, Key=key).get("ContentType")
            with tempfile.TemporaryDirectory() as d:
                src, dst = os.path.join(d, "in" + ext), os.path.join(d, "out.mp4")
                if ext == ".mp4":
                    s3.download_file(a.bucket, key, src)
                    codec = video_codec(ff, src)
                    if codec != "h264":
                        print(f"{key}: {codec} -> h264", flush=True)
                        if a.dry_run:
                            continue
                        subprocess.run([ff, "-y", "-loglevel", "error", "-i", src, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                                        "-preset", "fast", "-crf", "20", "-movflags", "+faststart", "-c:a", "aac", dst], check=True)
                        s3.upload_file(dst, a.bucket, key, ExtraArgs={"ContentType": CT[ext]})
                        continue
                    print(f"{key}: ya es h264 (ContentType {ct})")
                    if ct != CT[ext] and not a.dry_run:
                        s3.copy_object(Bucket=a.bucket, Key=key, CopySource={"Bucket": a.bucket, "Key": key},
                                       ContentType=CT[ext], MetadataDirective="REPLACE")
                        print(f"  ContentType {ct} -> {CT[ext]}")
                elif ct != CT[ext]:
                    print(f"{key}: ContentType {ct} -> {CT[ext]}")
                    if not a.dry_run:
                        s3.copy_object(Bucket=a.bucket, Key=key, CopySource={"Bucket": a.bucket, "Key": key},
                                       ContentType=CT[ext], MetadataDirective="REPLACE")


if __name__ == "__main__":
    main()
