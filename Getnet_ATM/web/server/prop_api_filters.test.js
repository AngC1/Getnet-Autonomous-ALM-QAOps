import test from 'node:test';
import assert from 'node:assert/strict';
import fc from 'fast-check';
import { MemoryStore } from './store.js';
import { createApp } from './app.js';
import { SEED } from './seed.js';
import { LABELS, TIPOS } from './arb_assets.js';

const ids = (r) => r.map((a) => a.id);
const qs = (o) => new URLSearchParams(Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined))).toString();
const valid = (k) => (k === 'tipo' ? TIPOS : LABELS);

// Feature: atm-card-incident-video-simulation, Property 26: Filtros inválidos se ignoran
test('Property 26: GET /api/assets aplica solo filtros con valor permitido', async () => {
  const s = new MemoryStore();
  for (const a of SEED) await s.upsert(a);
  const server = createApp(s).listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;
  const get = async (o) => ids(await (await fetch(`${base}/api/assets?${qs(o)}`)).json());
  const val = (k) => fc.oneof(fc.constantFrom(...valid(k)), fc.string({ maxLength: 12 }), fc.constantFrom('', 'CORRECTO ', 'Imagen', 'NONE', '__proto__'));
  try {
    await fc.assert(fc.asyncProperty(
      fc.record({ tipo: val('tipo'), esperada: val('esperada'), detectada: val('detectada') }, { requiredKeys: [] }),
      async (q) => {
        const cleaned = Object.fromEntries(Object.entries(q).filter(([k, v]) => valid(k).includes(v)));
        assert.deepEqual(await get(q), await get(cleaned));
      },
    ), { numRuns: 100 });
  } finally { server.close(); }
});
