import test from 'node:test';
import assert from 'node:assert/strict';
import fc from 'fast-check';
import { MemoryStore } from './store.js';
import { createApp } from './app.js';
import { poolAsset, LABELS, ID_POOL } from './arb_assets.js';

// Feature: atm-card-incident-video-simulation, Property 28: Validación manual de un activo en la API
test('Property 28: validate fija etiqueta_validada y cambia etiqueta solo con label', async () => {
  const s = new MemoryStore();
  const server = createApp(s).listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    await fc.assert(fc.asyncProperty(
      fc.uniqueArray(poolAsset, { selector: (a) => a.id, minLength: 1, maxLength: 5 }),
      fc.constantFrom(...ID_POOL), fc.option(fc.constantFrom(...LABELS), { nil: undefined }),
      async (assets, pick, label) => {
        await s.clear();
        for (const a of assets) await s.upsert(structuredClone(a));
        const target = assets.find((a) => a.id === pick) ?? assets[0];
        const snapshot = structuredClone(assets);
        const r = await fetch(`${base}/api/assets/${target.id}/validate`, {
          method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(label === undefined ? {} : { label }),
        });
        assert.equal(r.status, 200);
        assert.deepEqual(await r.json(), { ok: true });
        for (const orig of snapshot) {
          const now = await s.get(orig.id);
          if (orig.id === target.id) {
            assert.deepEqual(now, { ...orig, etiqueta_esperada: label ?? orig.etiqueta_esperada, etiqueta_validada: true });
          } else assert.deepEqual(now, orig);
        }
      },
    ), { numRuns: 100 });
  } finally { server.close(); }
});
