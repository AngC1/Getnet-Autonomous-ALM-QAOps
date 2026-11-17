import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { MemoryStore } from './store.js';
import { createApp } from './app.js';
import { createJobs } from './jobs.js';
import { pythonRegister, sniffType, REPO_ROOT } from './uploads.js';

const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.alloc(64)]);
const MP4 = Buffer.concat([Buffer.from([0, 0, 0, 0x18]), Buffer.from('ftypmp42'), Buffer.alloc(32)]);

async function boot(opts = {}) {
  const store = new MemoryStore();
  const calls = [];
  const runRegister = opts.runRegister ?? (async (file, label) => {
    calls.push({ file, label, existed: fs.existsSync(file), head: fs.readFileSync(file).subarray(0, 4) });
    return { id: 'up-imagen-0123abcd', tipo: 'imagen' };
  });
  const loaded = [];
  const app = createApp(store, {
    runRegister, loadAsset: async (id) => { loaded.push(id); return { id, tipo: 'imagen', etiqueta_esperada: 'CORRECTO', veredicto: null }; },
    jobs: opts.jobs ?? createJobs({ spawnFn: () => { throw new Error('no debe lanzarse python real'); } }),
    getReportUrl: opts.getReportUrl ?? (async () => null), localReport: opts.localReport ?? '/nonexistent/report.html',
  });
  const server = app.listen(0);
  return { store, calls, loaded, server, base: `http://127.0.0.1:${server.address().port}` };
}
const form = (buf, label, name = 'x.png') => {
  const f = new FormData();
  if (label !== undefined) f.set('label', label);
  if (buf) f.set('file', new Blob([buf]), name);
  return f;
};

test('upload OK: ignora el nombre, registra, recarga el activo y borra el tmp', async () => {
  const { server, base, calls, loaded, store } = await boot();
  try {
    const r = await fetch(`${base}/api/uploads`, { method: 'POST', body: form(PNG, 'CORRECTO', '../../etc/passwd; rm -rf.png') });
    assert.equal(r.status, 201);
    assert.deepEqual(await r.json(), { id: 'up-imagen-0123abcd', tipo: 'imagen' });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].label, 'CORRECTO');
    assert.ok(calls[0].existed);
    assert.equal(path.basename(calls[0].file), 'upload.bin');
    assert.ok(calls[0].file.startsWith(os.tmpdir()));
    assert.ok(!fs.existsSync(path.dirname(calls[0].file)), 'el tmp debe borrarse');
    assert.deepEqual(loaded, ['up-imagen-0123abcd']);
    assert.ok(await store.get('up-imagen-0123abcd'));
  } finally { server.close(); }
});

test('upload: label inválido o ausente -> 400', async () => {
  const { server, base, calls } = await boot();
  try {
    for (const label of ['NOPE', '', undefined]) {
      const r = await fetch(`${base}/api/uploads`, { method: 'POST', body: form(PNG, label) });
      assert.equal(r.status, 400, String(label));
      assert.match((await r.json()).error, /label/);
    }
    assert.equal((await fetch(`${base}/api/uploads`, { method: 'POST', body: form(null, 'CORRECTO') })).status, 400);
    assert.equal((await fetch(`${base}/api/uploads`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' })).status, 400);
    assert.equal(calls.length, 0);
  } finally { server.close(); }
});

test('upload: tipo no permitido por contenido -> 415 (aunque el nombre diga .png)', async () => {
  const { server, base, calls } = await boot();
  try {
    const r = await fetch(`${base}/api/uploads`, { method: 'POST', body: form(Buffer.from('GIF89a' + 'x'.repeat(50)), 'CORRECTO', 'a.png') });
    assert.equal(r.status, 415);
    assert.equal(calls.length, 0);
    assert.equal((await fetch(`${base}/api/uploads`, { method: 'POST', body: form(Buffer.from('MZ\x90\x00' + 'x'.repeat(50)), 'CORRECTO') })).status, 415);
  } finally { server.close(); }
});

test('upload: tamaño -> 413 (imagen > 5 MB) y se borra el tmp', async () => {
  const { server, base, calls } = await boot();
  try {
    const big = Buffer.concat([PNG, Buffer.alloc(5 * 1024 * 1024)]);
    const r = await fetch(`${base}/api/uploads`, { method: 'POST', body: form(big, 'CORRECTO') });
    assert.equal(r.status, 413);
    assert.equal(calls.length, 0);
    const leftovers = fs.readdirSync(os.tmpdir()).filter((n) => n.startsWith('brand-upload-'));
    assert.deepEqual(leftovers, []);
  } finally { server.close(); }
});

test('upload: límite de 200 MB (configurable) -> 413', async () => {
  const store = new MemoryStore();
  const { createUploadHandler } = await import('./uploads.js');
  const express = (await import('express')).default;
  const app = express();
  app.post('/u', createUploadHandler({ runRegister: async () => { throw new Error('no'); }, maxBytes: 1000 }));
  const server = app.listen(0);
  try {
    const r = await fetch(`http://127.0.0.1:${server.address().port}/u`, { method: 'POST', body: form(Buffer.concat([MP4, Buffer.alloc(2000)]), 'CORRECTO', 'v.mp4') });
    assert.equal(r.status, 413);
  } finally { server.close(); }
  assert.ok(store);
});

test('upload: vídeo MP4 aceptado; fallo del registro -> 500 genérico, error del archivo -> 400', async () => {
  const { server, base } = await boot({ runRegister: async () => ({ id: 'up-video-aaaaaaaa', tipo: 'video' }) });
  try {
    const r = await fetch(`${base}/api/uploads`, { method: 'POST', body: form(MP4, 'INCORRECTO', 'v.mp4') });
    assert.equal(r.status, 201);
    assert.equal((await r.json()).tipo, 'video');
  } finally { server.close(); }
  const b = await boot({ runRegister: async () => { throw new Error('boto3 /home/secret/path exploded'); } });
  try {
    const r = await fetch(`${b.base}/api/uploads`, { method: 'POST', body: form(PNG, 'CORRECTO') });
    assert.equal(r.status, 500);
    assert.deepEqual(await r.json(), { error: 'error interno' });
  } finally { b.server.close(); }
});

test('sniffType reconoce PNG/JPEG/WebP/MP4/MOV/WebM', () => {
  assert.deepEqual(sniffType(PNG), { tipo: 'imagen', ext: 'png' });
  assert.deepEqual(sniffType(Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0])), { tipo: 'imagen', ext: 'jpg' });
  assert.deepEqual(sniffType(Buffer.from('RIFF\0\0\0\0WEBPVP8 ', 'latin1')), { tipo: 'imagen', ext: 'webp' });
  assert.deepEqual(sniffType(MP4), { tipo: 'video', ext: 'mp4' });
  assert.deepEqual(sniffType(Buffer.concat([Buffer.from([0, 0, 0, 0x14]), Buffer.from('ftypqt  ')])), { tipo: 'video', ext: 'mov' });
  assert.deepEqual(sniffType(Buffer.from([0x1a, 0x45, 0xdf, 0xa3, 0])), { tipo: 'video', ext: 'webm' });
  assert.equal(sniffType(Buffer.from('hola')), null);
});

test('pythonRegister: args en array sin shell, cwd del repo, env con bucket y región', async () => {
  let seen;
  const spawnFn = (cmd, args, o) => {
    seen = { cmd, args, o };
    const c = new EventEmitter(); c.stdout = new EventEmitter(); c.stderr = new EventEmitter(); c.kill = () => {};
    setImmediate(() => { c.stdout.emit('data', '{"id":"up-imagen-1","tipo":"imagen","s3_key":"k"}\n'); c.emit('close', 0); });
    return c;
  };
  const run = pythonRegister({ spawnFn, env: { MEDIA_BUCKET: 'bkt', PATH: '/bin' } });
  assert.deepEqual(await run('/tmp/x; rm -rf /', 'CORRECTO'), { id: 'up-imagen-1', tipo: 'imagen' });
  assert.equal(seen.cmd, 'python3');
  assert.deepEqual(seen.args, ['-m', 'brand_verifier', 'register', '--file', '/tmp/x; rm -rf /', '--label', 'CORRECTO']);
  assert.equal(seen.o.shell, false);
  assert.equal(seen.o.cwd, REPO_ROOT);
  assert.ok(fs.existsSync(path.join(REPO_ROOT, 'brand_verifier')));
  assert.equal(seen.o.env.MEDIA_BUCKET, 'bkt');
  assert.equal(seen.o.env.AWS_REGION, 'us-east-1');
});
