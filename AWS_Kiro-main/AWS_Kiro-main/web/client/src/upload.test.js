import test from 'node:test';
import assert from 'node:assert/strict';
import { checkFile, newItem, uploadFile, kindOf, fmtSize, ACCEPT, LABEL_OPTIONS, MAX_BYTES } from './upload.js';

const f = (type, size, name = 'a') => ({ type, size, name });

test('checkFile: tipos y tamaños', () => {
  assert.equal(checkFile(f('image/png', 100)), null);
  assert.equal(checkFile(f('video/quicktime', 100)), null);
  assert.match(checkFile(f('image/gif', 100)), /Tipo no permitido/);
  assert.match(checkFile(f('application/pdf', 100)), /Tipo no permitido/);
  assert.match(checkFile(f('image/webp', 5 * 1024 * 1024 + 1)), /5 MB/);
  assert.equal(checkFile(f('video/mp4', 100 * 1024 * 1024)), null);
  assert.match(checkFile(f('video/mp4', MAX_BYTES + 1)), /200 MB/);
  assert.match(checkFile(f('image/png', 0)), /vacío/);
});

test('newItem: estado inicial y error previo; accept y marcas', () => {
  assert.equal(newItem(f('image/png', 10)).status, 'pending');
  const bad = newItem(f('text/plain', 10));
  assert.equal(bad.status, 'error');
  assert.ok(bad.error);
  assert.notEqual(newItem(f('image/png', 1)).key, newItem(f('image/png', 1)).key);
  assert.deepEqual(LABEL_OPTIONS.map(([v]) => v), ['CORRECTO', 'INCORRECTO', 'SIN_LOGO', 'AMBIGUO']);
  for (const t of ['image/png', 'image/jpeg', 'image/webp', 'video/mp4', 'video/quicktime', 'video/webm']) assert.ok(ACCEPT.includes(t));
  assert.equal(kindOf(f('video/webm', 1)), 'video');
  assert.equal(fmtSize(2 * 1048576), '2.0 MB');
});

class FakeXHR {
  static last;
  constructor() { FakeXHR.last = this; this.upload = {}; }
  open(m, u) { this.method = m; this.url = u; }
  send(body) { this.body = body; }
}

test('uploadFile: ruta relativa, progreso y éxito', async () => {
  const seen = [];
  const p = uploadFile(new Blob(['x']), 'CORRECTO', { onProgress: (v) => seen.push(v), XHR: FakeXHR });
  const x = FakeXHR.last;
  assert.equal(x.method, 'POST');
  assert.equal(x.url, 'api/uploads'); // relativa: funciona detrás de /proxy/3001/
  assert.equal(x.body.get('label'), 'CORRECTO');
  assert.ok(x.body.get('file'));
  x.upload.onprogress({ lengthComputable: true, loaded: 50, total: 100 });
  x.status = 201; x.responseText = '{"id":"up-imagen-1","tipo":"imagen"}'; x.onload();
  assert.deepEqual(await p, { id: 'up-imagen-1', tipo: 'imagen' });
  assert.deepEqual(seen, [0.5, 1]);
});

test('uploadFile: errores del servidor y de red', async () => {
  let p = uploadFile(new Blob(['x']), 'CORRECTO', { XHR: FakeXHR });
  FakeXHR.last.status = 415; FakeXHR.last.responseText = '{"error":"tipo de archivo no permitido"}'; FakeXHR.last.onload();
  await assert.rejects(p, /tipo de archivo no permitido/);
  p = uploadFile(new Blob(['x']), 'CORRECTO', { XHR: FakeXHR });
  FakeXHR.last.status = 502; FakeXHR.last.responseText = '<html>bad gateway</html>'; FakeXHR.last.onload();
  await assert.rejects(p, /Error 502/);
  p = uploadFile(new Blob(['x']), 'CORRECTO', { XHR: FakeXHR });
  FakeXHR.last.onerror();
  await assert.rejects(p, /red/);
});
