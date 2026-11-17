import test from 'node:test';
import assert from 'node:assert/strict';
import { MemoryStore } from './store.js';
import { createApp } from './app.js';
import { SEED } from './seed.js';
import { computeStats } from './stats.js';

async function boot() {
  const s = new MemoryStore();
  for (const a of SEED) await s.upsert(a);
  const server = createApp(s).listen(0);
  return { s, server, base: `http://127.0.0.1:${server.address().port}` };
}

test('stats: precisión solo sobre validados y falsos negativos', () => {
  const st = computeStats([
    { id: 'a', etiqueta_esperada: 'CORRECTO', etiqueta_validada: true, veredicto: { veredicto: 'CORRECTO' } },
    { id: 'b', etiqueta_esperada: 'INCORRECTO', etiqueta_validada: true, veredicto: { veredicto: 'CORRECTO' } },
    { id: 'c', etiqueta_esperada: 'CORRECTO', etiqueta_validada: false, veredicto: { veredicto: 'INCORRECTO' } },
  ]);
  assert.equal(st.validados, 2);
  assert.equal(st.precision, 50);
  assert.deepEqual(st.falsosNegativos, ['b']);
  assert.equal(st.objetivo, 'OBJETIVO NO ALCANZADO');
});

test('API: listado con filtros, detalle, validación e id inválido', async () => {
  const { server, base } = await boot();
  try {
    const all = await (await fetch(`${base}/api/assets`)).json();
    assert.equal(all.length, SEED.length);
    const vids = await (await fetch(`${base}/api/assets?tipo=video`)).json();
    assert.ok(vids.every((a) => a.tipo === 'video'));
    assert.equal((await fetch(`${base}/api/assets/img-correcto-01`)).status, 200);
    assert.equal((await fetch(`${base}/api/assets/nope`)).status, 404);
    assert.equal((await fetch(`${base}/api/assets/..%2Fx`)).status, 400);
    const r = await fetch(`${base}/api/assets/img-correcto-03/validate`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ label: 'NOPE' }) });
    assert.equal(r.status, 400);
  } finally { server.close(); }
});
test('API: /api/assets incluye thumbUrl (local o null) con MemoryStore', async () => {
  const s = new MemoryStore();
  await s.upsert({ id: 'x-1', tipo: 'imagen', etiqueta_esperada: 'CORRECTO', file: 'no-existe.png', veredicto: null });
  const server = createApp(s).listen(0);
  try {
    const list = await (await fetch(`http://127.0.0.1:${server.address().port}/api/assets`)).json();
    assert.ok('thumbUrl' in list[0]);
    assert.equal(list[0].thumbUrl, null);
  } finally { server.close(); }
});
