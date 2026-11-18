// POST api/uploads: multipart (busboy) -> archivo temporal seguro -> `python3 -m brand_verifier register`.
// Nunca se usa el nombre del archivo del cliente ni se invoca una shell.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import Busboy from 'busboy';

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
export const MAX_UPLOAD_BYTES = 200 * 1024 * 1024;
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const LABELS = ['CORRECTO', 'INCORRECTO', 'SIN_LOGO', 'AMBIGUO'];
const REGISTER_TIMEOUT_MS = 10 * 60 * 1000;

export class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

// Tipo por contenido (magic bytes): { tipo, ext } o null.
export function sniffType(h) {
  const eq = (off, s) => h.length >= off + s.length && Buffer.from(s, 'latin1').equals(h.subarray(off, off + s.length));
  if (h.length >= 8 && h.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return { tipo: 'imagen', ext: 'png' };
  if (h.length >= 3 && h[0] === 0xff && h[1] === 0xd8 && h[2] === 0xff) return { tipo: 'imagen', ext: 'jpg' };
  if (eq(0, 'RIFF') && eq(8, 'WEBP')) return { tipo: 'imagen', ext: 'webp' };
  if (eq(4, 'ftyp')) return { tipo: 'video', ext: eq(8, 'qt  ') ? 'mov' : 'mp4' };
  if (h.length >= 4 && h[0] === 0x1a && h[1] === 0x45 && h[2] === 0xdf && h[3] === 0xa3) return { tipo: 'video', ext: 'webm' };
  return null;
}

// Ejecutor por defecto: spawn con argumentos en array (sin shell), cwd = raíz del repo.
export function pythonRegister({ python = process.env.PYTHON || 'python3', cwd = REPO_ROOT, env = process.env, timeoutMs = REGISTER_TIMEOUT_MS, spawnFn = spawn } = {}) {
  return (file, label) => new Promise((resolve, reject) => {
    const child = spawnFn(python, ['-m', 'brand_verifier', 'register', '--file', file, '--label', label], {
      cwd, shell: false, stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...env, MEDIA_BUCKET: env.MEDIA_BUCKET, AWS_REGION: env.AWS_REGION || 'us-east-1' },
    });
    let out = ''; let err = '';
    const timer = setTimeout(() => child.kill('SIGKILL'), timeoutMs);
    child.stdout.on('data', (d) => { out = (out + d).slice(-8192); });
    child.stderr.on('data', (d) => { err = (err + d).slice(-8192); });
    child.on('error', () => { clearTimeout(timer); reject(new HttpError(500, 'no se pudo registrar el archivo')); });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (code === 1) { // archivo no válido: el mensaje de la CLI es apto para el usuario
        const line = err.trim().split('\n').pop().replace(/^register:\s*/, '').slice(0, 200);
        return reject(new HttpError(400, line || 'archivo no válido'));
      }
      if (code !== 0) return reject(new HttpError(500, 'no se pudo registrar el archivo'));
      try {
        const r = JSON.parse(out.trim().split('\n').pop());
        if (typeof r.id !== 'string' || typeof r.tipo !== 'string') throw new Error('formato');
        resolve({ id: r.id, tipo: r.tipo });
      } catch { reject(new HttpError(500, 'no se pudo registrar el archivo')); }
    });
  });
}

// Guarda el archivo del multipart en `dir`; devuelve { label, file, truncated } sin validar el contenido.
function receive(req, dir, maxBytes) {
  return new Promise((resolve, reject) => {
    let bb;
    try {
      bb = Busboy({ headers: req.headers, limits: { fileSize: maxBytes, files: 1, fields: 4, parts: 6, fieldSize: 256 } });
    } catch { return reject(new HttpError(400, 'se esperaba multipart/form-data')); }
    const out = { label: undefined, file: null, truncated: false, extra: false };
    let pendingWrite = null;
    bb.on('field', (name, val) => { if (name === 'label') out.label = val; });
    bb.on('file', (name, stream) => {
      if (name !== 'file' || out.file) { out.extra = true; stream.resume(); return; }
      const dest = path.join(dir, 'upload.bin'); // nombre fijo: se ignora el del cliente
      const ws = fs.createWriteStream(dest, { mode: 0o600 });
      out.file = dest;
      stream.on('limit', () => { out.truncated = true; });
      pendingWrite = new Promise((res, rej) => { ws.on('finish', res); ws.on('error', rej); });
      stream.pipe(ws);
    });
    bb.on('filesLimit', () => { out.extra = true; });
    bb.on('error', () => reject(new HttpError(400, 'multipart mal formado')));
    bb.on('close', () => { (pendingWrite ?? Promise.resolve()).then(() => resolve(out), () => reject(new HttpError(500, 'no se pudo guardar el archivo'))); });
    req.on('aborted', () => reject(new HttpError(400, 'subida cancelada')));
    req.pipe(bb);
  });
}

export function createUploadHandler({ runRegister = pythonRegister(), onRegistered, maxBytes = MAX_UPLOAD_BYTES, tmpRoot = os.tmpdir() } = {}) {
  let chain = Promise.resolve(); // registros en serie: el manifiesto se lee-modifica-escribe
  const serial = (fn) => { const p = chain.then(fn, fn); chain = p.catch(() => {}); return p; };

  return async function upload(req, res, next) {
    let dir;
    let reply; // la respuesta se envía tras borrar el tmp
    try {
      if (!/^multipart\/form-data/i.test(req.headers['content-type'] ?? '')) throw new HttpError(400, 'se esperaba multipart/form-data');
      dir = await fs.promises.mkdtemp(path.join(tmpRoot, 'brand-upload-'));
      await fs.promises.chmod(dir, 0o700);
      const got = await receive(req, dir, maxBytes);
      if (got.truncated) throw new HttpError(413, `el archivo supera el límite de ${Math.round(maxBytes / 1048576)} MB`);
      if (!LABELS.includes(got.label)) throw new HttpError(400, `label obligatorio: ${LABELS.join(', ')}`);
      if (!got.file || got.extra) throw new HttpError(400, 'se esperaba un único archivo en el campo "file"');
      const fh = await fs.promises.open(got.file, 'r');
      let head;
      try { const b = Buffer.alloc(16); const { bytesRead } = await fh.read(b, 0, 16, 0); head = b.subarray(0, bytesRead); } finally { await fh.close(); }
      const kind = sniffType(head);
      if (!kind) throw new HttpError(415, 'tipo de archivo no permitido (PNG, JPEG, WebP, MP4, MOV o WebM)');
      const { size } = await fs.promises.stat(got.file);
      if (kind.tipo === 'imagen' && size > MAX_IMAGE_BYTES) throw new HttpError(413, 'la imagen supera 5 MB');
      const result = await serial(() => runRegister(got.file, got.label));
      if (onRegistered) { try { await onRegistered(result.id); } catch (e) { console.warn(`recarga tras subida fallida (${e?.name})`); } }
      reply = () => res.status(201).json({ id: result.id, tipo: result.tipo });
    } catch (e) {
      reply = e instanceof HttpError ? () => res.status(e.status).json({ error: e.message }) : () => next(e);
    }
    if (dir) await fs.promises.rm(dir, { recursive: true, force: true }).catch(() => {});
    reply();
  };
}
