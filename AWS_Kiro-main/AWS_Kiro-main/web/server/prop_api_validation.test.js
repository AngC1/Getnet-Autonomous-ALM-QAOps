import test from 'node:test';
import assert from 'node:assert/strict';
import fc from 'fast-check';
import { MemoryStore } from './store.js';
import { createApp } from './app.js';
import { SEED } from './seed.js';
import { LABELS } from './arb_assets.js';

const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

// Feature: atm-card-incident-video-simulation, Property 27: Validación de identificador y etiqueta
test('Property 27: id/label inválidos → 400 sin modificar; válidos inexistentes → 404', async () => {
  const s = new MemoryStore();
  for (const a of SEED) await s.upsert(a);
  const before = JSON.stringify(await s.list());
  const server = createApp(s).listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;
  const post = (id, body) => fetch(`${base}/api/assets/${encodeURIComponent(id)}/validate`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  });
  const idArb = fc.oneof(
    fc.stringMatching(/^[A-Za-z0-9_-]{1,64}$/).map((x) => `x${x}`.slice(0, 64)),
    fc.string({ maxLength: 80 }), fc.constant('a'.repeat(65)), fc.constant('a b'), fc.constant('a.b'), fc.constant(' '),
  ).filter((id) => id !== '');
  const labelArb = fc.oneof(fc.constant(undefined), fc.constantFrom(...LABELS), fc.string({ maxLength: 10 }), fc.constant(42), fc.constant(null));
  try {
    await fc.assert(fc.asyncProperty(idArb, labelArb, async (id, label) => {
      const idOk = ID_RE.test(id) ;
      const labelOk = label === undefined || LABELS.includes(label);
      const isSeed = SEED.some((a) => a.id === id);
      const g = await fetch(`${base}/api/assets/${encodeURIComponent(id)}`);
      const p = await post(id, label === undefined ? {} : { label });
      if (!idOk) { assert.equal(g.status, 400); assert.equal(p.status, 400); }
      else {
        assert.equal(g.status, isSeed ? 200 : 404);
        if (!isSeed) { assert.equal((await g.json()).error, 'no encontrado'); }
        if (!labelOk) assert.equal(p.status, 400);
        else if (!isSeed) { assert.equal(p.status, 404); assert.equal((await p.json()).error, 'no encontrado'); }
      }
      if (!(idOk && labelOk && isSeed)) assert.equal(JSON.stringify(await s.list()), before);
      else await s.upsert(SEED.find((a) => a.id === id)); // restaura tras validación válida
    }), { numRuns: 100 });
  } finally { server.close(); }
});
