import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { MemoryStore } from './store.js';
import { createApp } from './app.js';
import { createJobs } from './jobs.js';

function fakeSpawn() {
  const runs = [];
  const spawnFn = (cmd, args, opts) => {
    const c = new EventEmitter(); c.stdout = new EventEmitter(); c.stderr = new EventEmitter(); c.kill = () => {};
    runs.push({ cmd, args, opts, child: c });
    return c;
  };
  return { spawnFn, runs };
}

async function boot(extra = {}) {
  const store = new MemoryStore();
  await store.upsert({ id: 'img-1', tipo: 'imagen', etiqueta_esperada: 'CORRECTO', veredicto: null });
  const { spawnFn, runs } = fakeSpawn();
  const succeeded = [];
  const jobs = createJobs({ spawnFn, env: { MEDIA_BUCKET: 'bkt' }, onSuccess: async () => { succeeded.push(1); } });
  const app = createApp(store, { jobs, loadAll: async () => [], ...extra });
  const server = app.listen(0);
  return { store, runs, succeeded, server, base: `http://127.0.0.1:${server.address().port}` };
}
const post = (base, body) => fetch(`${base}/api/jobs/verify`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });

test('job: lanza python sin shell con --only, un solo job a la vez (409) y log redactado', async () => {
  const { server, base, runs, succeeded } = await boot();
  try {
    assert.equal((await post(base, { only: ['img-1'] })).status, 202);
    assert.equal(runs.length, 1);
    assert.deepEqual(runs[0].args, ['-u', '-m', 'brand_verifier', 'run', '--skip-generation', '--only', 'img-1']);
    assert.equal(runs[0].cmd, 'python3');
    assert.equal(runs[0].opts.shell, false);
    assert.equal(runs[0].opts.env.MEDIA_BUCKET, 'bkt');

    const second = await post(base, {});
    assert.equal(second.status, 409);
    assert.equal(runs.length, 1);

    runs[0].child.stdout.emit('data', '[etapa] verificacion: en curso\nAuthorization: Bearer abcdefgh12345678\npar');
    runs[0].child.stdout.emit('data', 'cial\n');
    let j = await (await fetch(`${base}/api/jobs/latest`)).json();
    assert.equal(j.status, 'running');
    assert.match(j.log, /verificacion: en curso/);
    assert.match(j.log, /parcial/);
    assert.doesNotMatch(j.log, /abcdefgh12345678/);

    runs[0].child.emit('close', 0);
    j = await (await fetch(`${base}/api/jobs/${j.id}`)).json();
    assert.equal(j.status, 'succeeded');
    assert.equal(j.exit_code, 0);
    assert.ok(j.finished_at);
    await new Promise((r) => setTimeout(r, 10));
    assert.equal(succeeded.length, 1);

    assert.equal((await post(base, {})).status, 202); // ya se puede lanzar otro
    assert.deepEqual(runs[1].args, ['-u', '-m', 'brand_verifier', 'run', '--skip-generation']);
    runs[1].child.emit('close', 1);
    const f = await (await fetch(`${base}/api/jobs/latest`)).json();
    assert.equal(f.status, 'failed');
    assert.equal(succeeded.length, 1, 'solo recarga si tiene éxito');
  } finally { server.close(); }
});

test('job: validación de only y de ids', async () => {
  const { server, base, runs } = await boot();
  try {
    assert.equal((await post(base, { only: 'img-1' })).status, 400);
    assert.equal((await post(base, { only: ['../x'] })).status, 400);
    assert.equal((await post(base, { only: ['a,b'] })).status, 400);
    assert.equal((await post(base, { only: ['desconocido'] })).status, 400);
    assert.equal((await fetch(`${base}/api/jobs/nope`)).status, 404);
    assert.equal((await fetch(`${base}/api/jobs/latest`)).status, 404);
    assert.equal(runs.length, 0);
  } finally { server.close(); }
});

test('job: log limitado a las últimas 500 líneas', () => {
  const { spawnFn, runs } = fakeSpawn();
  const jobs = createJobs({ spawnFn });
  jobs.start(null);
  runs[0].child.stdout.emit('data', Array.from({ length: 800 }, (_, i) => `l${i}`).join('\n') + '\n');
  const lines = jobs.latest().log.split('\n');
  assert.equal(lines.length, 500);
  assert.equal(lines.at(-1), 'l799');
});

test('job: error al lanzar -> failed y libera el cerrojo', () => {
  const { spawnFn, runs } = fakeSpawn();
  const jobs = createJobs({ spawnFn });
  jobs.start(null);
  runs[0].child.emit('error', new Error('ENOENT'));
  assert.equal(jobs.latest().status, 'failed');
  assert.equal(jobs.isRunning(), false);
});

test('report: redirige a la URL prefirmada, sirve la copia local o 404', async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'rep-'));
  const local = path.join(tmp, 'report.html'); fs.writeFileSync(local, '<h1>informe</h1>');
  let b = await boot({ getReportUrl: async () => 'https://example.invalid/presigned' });
  try {
    const r = await fetch(`${b.base}/api/report`, { redirect: 'manual' });
    assert.equal(r.status, 302);
    assert.equal(r.headers.get('location'), 'https://example.invalid/presigned');
  } finally { b.server.close(); }
  b = await boot({ getReportUrl: async () => null, localReport: local });
  try {
    const r = await fetch(`${b.base}/api/report`);
    assert.equal(r.status, 200);
    assert.match(await r.text(), /informe/);
  } finally { b.server.close(); }
  b = await boot({ getReportUrl: async () => null, localReport: path.join(tmp, 'no.html') });
  try { assert.equal((await fetch(`${b.base}/api/report`)).status, 404); } finally { b.server.close(); fs.rmSync(tmp, { recursive: true }); }
});

const postGen = (base, body) => fetch(`${base}/api/jobs/generate`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });

test('generate: valida el cuerpo con 400 y mensaje claro, sin lanzar nada', async () => {
  const { server, base, runs } = await boot();
  try {
    const cases = [
      [{}, /logo/], [{ logo: 'OTRO', tipo: 'imagen' }, /logo/], [{ logo: 'CORRECTO' }, /tipo/],
      [{ logo: 'CORRECTO', tipo: 'gif' }, /tipo/], [{ logo: 'CORRECTO', tipo: 'imagen', escena: 'luna' }, /escena/],
      [{ logo: 'CORRECTO', tipo: 'imagen', prompt: 'x'.repeat(301) }, /300/], [{ logo: 'CORRECTO', tipo: 'imagen', prompt: 'a\nb' }, /control/],
      [{ logo: 'CORRECTO', tipo: 'imagen', prompt: '   ' }, /vacío/], [{ logo: 'CORRECTO', tipo: 'imagen', prompt: 7 }, /texto/],
      [{ logo: 'CORRECTO', tipo: 'imagen', verify: 'si' }, /verify/],
    ];
    for (const [body, msg] of cases) {
      const r = await postGen(base, body);
      assert.equal(r.status, 400, JSON.stringify(body));
      assert.match((await r.json()).error, msg);
    }
    assert.equal(runs.length, 0);
  } finally { server.close(); }
});

test('generate: argumentos en array sin shell, mismo candado (409) y RESULT/fase en el job', async () => {
  const { server, base, runs, succeeded } = await boot();
  try {
    const r = await postGen(base, { logo: 'INCORRECTO', tipo: 'imagen', escena: 'atm' });
    assert.equal(r.status, 202);
    const started = await r.json();
    assert.equal(started.kind, 'generate');
    assert.equal(started.phase, 'generating');
    assert.deepEqual(runs[0].args, ['-u', '-m', 'brand_verifier', 'generate', '--logo', 'INCORRECTO', '--tipo', 'imagen', '--escena', 'atm', '--verify']);
    assert.equal(runs[0].opts.shell, false);

    assert.equal((await post(base, {})).status, 409, 'la verificación espera a la generación');
    const again = await postGen(base, { logo: 'CORRECTO', tipo: 'video' });
    assert.equal(again.status, 409);
    assert.match((await again.json()).error, /generación en curso/);
    assert.equal(runs.length, 1);

    runs[0].child.stdout.emit('data', '[fase] generacion: completada (20.1 s)\n[fase] verificacion: en curso (gen-imagen-0a1b2c3d)\n');
    let j = await (await fetch(`${base}/api/jobs/${started.id}`)).json();
    assert.equal(j.phase, 'verifying');
    assert.equal(j.result, null);
    runs[0].child.stdout.emit('data', 'RESULT {"id": "gen-imagen-0a1b2c3d", "tipo": "imagen", "s3_key": "brand/generated/gen-imagen-0a1b2c3d/output.png", "estado": "GENERADO"}\n');
    runs[0].child.emit('close', 0);
    j = await (await fetch(`${base}/api/jobs/${started.id}`)).json();
    assert.equal(j.status, 'succeeded');
    assert.deepEqual(j.result, { id: 'gen-imagen-0a1b2c3d', tipo: 'imagen', estado: 'GENERADO' });
    await new Promise((res) => setTimeout(res, 10));
    assert.equal(succeeded.length, 1, 'recarga activos y caché del dashboard');

    // Una verificación en curso también bloquea la generación.
    assert.equal((await post(base, {})).status, 202);
    assert.equal((await postGen(base, { logo: 'SIN_LOGO', tipo: 'imagen' })).status, 409);
  } finally { server.close(); }
});

test('generate: prompt personalizado como un solo argumento (--prompt=) y verify:false', async () => {
  const { server, base, runs } = await boot();
  try {
    assert.equal((await postGen(base, { logo: 'SIN_LOGO', tipo: 'video', escena: 'valla', prompt: '  --verify; rm -rf / ', verify: false })).status, 202);
    assert.deepEqual(runs[0].args, ['-u', '-m', 'brand_verifier', 'generate', '--logo', 'SIN_LOGO', '--tipo', 'video', '--prompt=--verify; rm -rf /']);
  } finally { server.close(); }
});

test('generate: RESULT malformado se ignora; fallo de generación no recarga', () => {
  const { spawnFn, runs } = fakeSpawn();
  let reloads = 0;
  const jobs = createJobs({ spawnFn, onSuccess: () => { reloads += 1; } });
  jobs.startGenerate({ logo: 'CORRECTO', tipo: 'imagen', escena: 'taza', verify: true });
  runs[0].child.stdout.emit('data', 'RESULT {roto\nRESULT {"id": "../x", "tipo": "imagen"}\n');
  runs[0].child.emit('close', 2);
  const j = jobs.latest();
  assert.equal(j.status, 'failed');
  assert.equal(j.exit_code, 2);
  assert.equal(j.result, null);
  assert.equal(reloads, 0);
  assert.equal(jobs.isRunning(), false);
});
