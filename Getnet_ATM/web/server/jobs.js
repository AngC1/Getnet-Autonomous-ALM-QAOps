// Jobs de Python: un solo proceso a la vez (mismo candado para verificación y generación).
// - verify:   python3 -u -m brand_verifier run --skip-generation [--only ...]
// - generate: python3 -u -m brand_verifier generate --logo X --tipo Y [--escena Z | --prompt=T] [--verify]
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { redactString } from './dashboard.js';
import { REPO_ROOT } from './uploads.js';

export const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
export const MAX_ONLY = 500;
export const GEN_LOGOS = Object.freeze(['CORRECTO', 'INCORRECTO', 'SIN_LOGO']);
export const GEN_TIPOS = Object.freeze(['imagen', 'video']);
export const GEN_SCENES = Object.freeze(['atm', 'oficina', 'valla', 'taza', 'camiseta', 'movil']);
export const PROMPT_MAX = 300;
const CONTROL_RE = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u; // mismo criterio que brand_verifier/ondemand.py
const MAX_LINES = 500;
const MAX_JOBS = 20;

export class JobConflict extends Error {}

// Valida el cuerpo de POST /api/jobs/generate. Devuelve { params } o { error } (mensaje para el usuario).
export function parseGenerateBody(body) {
  const b = body && typeof body === 'object' && !Array.isArray(body) ? body : {};
  if (!GEN_LOGOS.includes(b.logo)) return { error: 'logo debe ser CORRECTO, INCORRECTO o SIN_LOGO' };
  if (!GEN_TIPOS.includes(b.tipo)) return { error: 'tipo debe ser imagen o video' };
  const has = (v) => v !== undefined && v !== null && v !== '';
  if (has(b.escena) && !GEN_SCENES.includes(b.escena)) return { error: `escena debe ser una de: ${GEN_SCENES.join(', ')}` };
  let prompt = null;
  if (has(b.prompt)) {
    if (typeof b.prompt !== 'string') return { error: 'prompt debe ser texto' };
    if (CONTROL_RE.test(b.prompt)) return { error: 'prompt no admite caracteres de control' };
    prompt = b.prompt.trim();
    if (!prompt) return { error: 'prompt no puede estar vacío' };
    if ([...prompt].length > PROMPT_MAX) return { error: `prompt admite como máximo ${PROMPT_MAX} caracteres` };
  }
  if (b.verify !== undefined && b.verify !== null && typeof b.verify !== 'boolean') return { error: 'verify debe ser true o false' };
  return { params: { logo: b.logo, tipo: b.tipo, escena: prompt ? null : (has(b.escena) ? b.escena : 'taza'), prompt, verify: b.verify ?? true } };
}

// Línea final de `generate`: RESULT {"id","tipo","s3_key","estado"} -> { id, tipo, estado } o null.
export function parseResultLine(line) {
  if (typeof line !== 'string' || !line.startsWith('RESULT ')) return null;
  try {
    const r = JSON.parse(line.slice(7));
    if (!r || typeof r !== 'object' || !ID_RE.test(r.id ?? '') || !GEN_TIPOS.includes(r.tipo)) return null;
    return { id: r.id, tipo: r.tipo, estado: typeof r.estado === 'string' ? r.estado : null };
  } catch { return null; }
}

export function generateArgs({ logo, tipo, escena, prompt, verify }) {
  const args = ['-u', '-m', 'brand_verifier', 'generate', '--logo', logo, '--tipo', tipo];
  if (prompt) args.push(`--prompt=${prompt}`); // con '=': un texto que empiece por '-' no se toma como opción
  else if (escena) args.push('--escena', escena);
  if (verify) args.push('--verify');
  return args;
}

export function createJobs({ spawnFn = spawn, python = process.env.PYTHON || 'python3', cwd = REPO_ROOT, env = process.env, onSuccess, redact = redactString, now = () => new Date() } = {}) {
  const jobs = new Map(); // id -> job (inserción = orden)
  let running = null;

  const view = (j) => ({
    id: j.id, kind: j.kind, status: j.status, phase: j.phase, started_at: j.started_at, finished_at: j.finished_at, exit_code: j.exit_code,
    only: j.only, params: j.params, result: j.result, log: j.lines.join('\n'),
  });

  function launch(kind, args, extra) {
    if (running) throw new JobConflict(running.kind === 'generate' ? 'ya hay una generación en curso' : 'ya hay una verificación en curso');
    const job = {
      id: randomUUID(), kind, status: 'running', phase: kind === 'generate' ? 'generating' : 'verifying',
      started_at: now().toISOString(), finished_at: null, exit_code: null, only: null, params: null, result: null, lines: [], ...extra,
    };
    jobs.set(job.id, job);
    while (jobs.size > MAX_JOBS) jobs.delete(jobs.keys().next().value);
    running = job;

    const push = (line) => {
      if (kind === 'generate') {
        const r = parseResultLine(line);
        if (r) job.result = r;
        if (line.startsWith('[fase] verificacion: en curso')) job.phase = 'verifying';
      }
      job.lines.push(redact(line)); if (job.lines.length > MAX_LINES) job.lines.splice(0, job.lines.length - MAX_LINES);
    };
    const feed = () => { let buf = ''; return { write(d) { buf += d; const parts = buf.split(/\r?\n/); buf = parts.pop(); parts.forEach(push); }, end() { if (buf) push(buf); buf = ''; } }; };
    const finish = (code) => {
      if (job.status !== 'running') return;
      out.end(); err.end();
      job.exit_code = code; job.status = code === 0 ? 'succeeded' : 'failed'; job.finished_at = now().toISOString();
      running = null;
      // generate con exit 3 (verificación fallida) también deja un activo nuevo: se recarga igualmente.
      const reload = code === 0 || (kind === 'generate' && job.result?.estado === 'GENERADO');
      if (reload && onSuccess) Promise.resolve().then(onSuccess).catch((e) => console.warn(`recarga tras el job fallida (${e?.name})`));
    };
    const out = feed(); const err = feed();
    const what = kind === 'generate' ? 'generación' : 'verificación';
    let child;
    try {
      child = spawnFn(python, args, { cwd, shell: false, stdio: ['ignore', 'pipe', 'pipe'], env: { ...env, MEDIA_BUCKET: env.MEDIA_BUCKET, AWS_REGION: env.AWS_REGION || 'us-east-1', PYTHONUNBUFFERED: '1' } });
    } catch { push(`No se pudo iniciar el proceso de ${what}.`); finish(-1); return view(job); }
    child.stdout?.on('data', (d) => out.write(String(d)));
    child.stderr?.on('data', (d) => err.write(String(d)));
    child.on('error', () => { push(`No se pudo iniciar el proceso de ${what}.`); finish(-1); });
    child.on('close', (code) => finish(code ?? -1));
    return view(job);
  }

  function start(only) {
    const args = ['-u', '-m', 'brand_verifier', 'run', '--skip-generation'];
    if (only?.length) args.push('--only', only.join(','));
    return launch('verify', args, { only: only ?? null });
  }

  function startGenerate(params) {
    return launch('generate', generateArgs(params), { params: { logo: params.logo, tipo: params.tipo, escena: params.escena ?? null, custom: !!params.prompt, verify: !!params.verify } });
  }

  return {
    start,
    startGenerate,
    get: (id) => (jobs.has(id) ? view(jobs.get(id)) : null),
    latest: () => { let last = null; for (const j of jobs.values()) last = j; return last ? view(last) : null; },
    isRunning: () => !!running,
  };
}
