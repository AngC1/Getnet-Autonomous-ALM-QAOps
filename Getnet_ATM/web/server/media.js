// Resuelve la URL del medio: URL prefirmada de S3 (3600 s) o archivo local en web/media/.
import fs from 'node:fs';
import path from 'node:path';
import { S3Client, GetObjectCommand, HeadObjectCommand, ListObjectsV2Command } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';

export const MEDIA_DIR = path.resolve(process.env.MEDIA_DIR || new URL('../media', import.meta.url).pathname);
const BUCKET = process.env.MEDIA_BUCKET; // p. ej. el valor del Output MediaToolkitIngestBucket
const s3 = BUCKET ? new S3Client({ region: process.env.AWS_REGION || 'us-east-1' }) : null;
export const s3Enabled = () => !!s3;

const sign = (Key) => getSignedUrl(s3, new GetObjectCommand({ Bucket: BUCKET, Key }), { expiresIn: 3600 });

// Si existe el vídeo con audio (Stable Audio) se sirve ése; si no, el original.
export async function mediaUrl(a) {
  if (s3 && a.video_audio_key) return sign(a.video_audio_key);
  if (s3 && a.s3_key) return sign(a.s3_key);
  if (a.file && fs.existsSync(path.join(MEDIA_DIR, a.file))) return `media/${encodeURIComponent(a.file)}`;
  return null;
}

// Carga datos reales: brand/generated/manifest.json + brand/verdicts/<id>.json
async function getJson(Key) {
  const { Body } = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key }));
  return JSON.parse(await Body.transformToString());
}
async function withVerdict(m, audio) {
  let veredicto = null;
  try { veredicto = await getJson(`brand/verdicts/${m.id}.json`); } catch { /* sin veredicto aún */ }
  const au = audio?.[m.id];
  return au
    ? { ...m, veredicto, audio_key: au.audio_key, video_audio_key: au.video_audio_key, audio_prompt: au.prompt }
    : { ...m, veredicto };
}
const loadAudioIndex = async () => { try { return await getJson('brand/audio/index.json'); } catch { return {}; } };

export async function loadFromS3() {
  if (!s3) return [];
  const manifest = await getJson('brand/generated/manifest.json');
  const audio = await loadAudioIndex();
  const out = [];
  for (const m of manifest.assets ?? []) out.push(await withVerdict(m, audio));
  return out;
}
// Un solo activo (manifest + veredicto); null si no existe o S3 no está activo.
export async function loadAssetFromS3(id) {
  if (!s3) return null;
  const manifest = await getJson('brand/generated/manifest.json');
  const m = (manifest.assets ?? []).find((x) => x.id === id);
  return m ? withVerdict(m, await loadAudioIndex()) : null;
}

// Informe de auditoría: URL prefirmada (600 s) si existe en S3; si no, null (se usa la copia local).
export const REPORT_KEY = 'brand/reports/report.html';
export const LOCAL_REPORT = path.resolve(new URL('../../brand/reports/report.html', import.meta.url).pathname);
export async function reportUrl() {
  if (!s3) return null;
  try { await s3.send(new HeadObjectCommand({ Bucket: BUCKET, Key: REPORT_KEY })); } catch { return null; }
  return getSignedUrl(s3, new GetObjectCommand({
    Bucket: BUCKET, Key: REPORT_KEY, ResponseContentType: 'text/html; charset=utf-8', ResponseContentDisposition: 'inline',
  }), { expiresIn: 600 });
}
// URL prefirmada (3600 s) de la cortina sonora suelta, o null.
export async function audioUrl(a) {
  return s3 && a.audio_key ? sign(a.audio_key) : null;
}
export { ListObjectsV2Command };
