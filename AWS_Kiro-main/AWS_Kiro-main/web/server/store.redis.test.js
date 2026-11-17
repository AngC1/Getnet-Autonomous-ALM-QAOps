import test from 'node:test';
import assert from 'node:assert/strict';
import { createStore } from './store.js';
import { mockRedisStore } from './redis_helper.js';

const A = (id, tipo, esp, det) => ({ id, tipo, etiqueta_esperada: esp, etiqueta_validada: false, ...(det ? { veredicto: { veredicto: det } } : {}) });

test('RedisStore: claves, índices, intersección y reindexado', async (t) => {
  const s = await mockRedisStore();
  if (!s) return t.skip('ioredis-mock no disponible');
  await s.clear();
  await s.upsert(A('z1', 'imagen', 'CORRECTO', 'CORRECTO'));
  await s.upsert(A('a2', 'video', 'INCORRECTO'));
  await s.upsert(A('m3', 'imagen', 'CORRECTO', 'AMBIGUO'));
  const r = s.r;

  assert.equal(JSON.parse(await r.get('asset:z1')).id, 'z1');
  assert.deepEqual(await r.zrange('assets:all', 0, -1), ['z1', 'a2', 'm3']); // orden de inserción, no alfabético
  assert.deepEqual(await r.smembers('idx:detectada:NONE'), ['a2']);
  assert.deepEqual((await r.smembers('idx:tipo:imagen')).sort(), ['m3', 'z1']);
  assert.deepEqual((await r.smembers('idx:esperada:INCORRECTO')), ['a2']);

  const ids = async (f) => (await s.list(f)).map((a) => a.id);
  assert.deepEqual(await ids({ tipo: 'imagen', esperada: 'CORRECTO' }), ['z1', 'm3']);
  assert.deepEqual(await ids({ tipo: 'imagen', detectada: 'AMBIGUO' }), ['m3']);
  assert.deepEqual(await ids({ tipo: 'video', detectada: 'CORRECTO' }), []);

  // Reindexado: cambia tipo, etiqueta y veredicto; conserva posición
  await s.upsert(A('z1', 'video', 'SIN_LOGO'));
  assert.deepEqual(await r.zrange('assets:all', 0, -1), ['z1', 'a2', 'm3']);
  assert.ok(!(await r.sismember('idx:tipo:imagen', 'z1')));
  assert.ok(!(await r.sismember('idx:esperada:CORRECTO', 'z1')));
  assert.ok(!(await r.sismember('idx:detectada:CORRECTO', 'z1')));
  assert.ok(await r.sismember('idx:tipo:video', 'z1'));
  assert.ok(await r.sismember('idx:detectada:NONE', 'z1'));
  assert.deepEqual(await ids({ tipo: 'video' }), ['z1', 'a2']);
});

test('createStore: URL inválida cae a memoria', async () => {
  const orig = console.warn; console.warn = () => {};
  try {
    const s = await createStore('redis://127.0.0.1:1');
    assert.equal(s.name, 'memory');
  } finally { console.warn = orig; }
});
