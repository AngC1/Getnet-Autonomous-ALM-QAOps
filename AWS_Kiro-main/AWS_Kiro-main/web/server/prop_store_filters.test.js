import test from 'node:test';
import assert from 'node:assert/strict';
import fc from 'fast-check';
import { MemoryStore } from './store.js';
import { poolAsset, LABELS, TIPOS } from './arb_assets.js';
import { mockRedisStore } from './redis_helper.js';

const filters = fc.record({
  tipo: fc.option(fc.constantFrom(...TIPOS), { nil: undefined }),
  esperada: fc.option(fc.constantFrom(...LABELS), { nil: undefined }),
  detectada: fc.option(fc.constantFrom(...LABELS, 'NONE'), { nil: undefined }),
}, { requiredKeys: [] });

// Feature: atm-card-incident-video-simulation, Property 25: Consistencia de filtros entre RedisStore y MemoryStore
test('Property 25: RedisStore y MemoryStore listan los mismos ids en el mismo orden', async (t) => {
  const redis = await mockRedisStore();
  if (!redis) return t.skip('ioredis-mock no disponible');
  await fc.assert(fc.asyncProperty(
    fc.array(poolAsset, { minLength: 1, maxLength: 15 }),
    fc.array(filters, { minLength: 1, maxLength: 5 }),
    async (seq, fs) => {
      const mem = new MemoryStore();
      await redis.clear();
      for (const a of seq) { await mem.upsert(a); await redis.upsert(a); }
      for (const f of fs) {
        // 'NONE' solo es un valor de índice; en memoria equivale a "sin veredicto", se compara contra el modelo directo.
        const q = { ...f };
        if (q.detectada === 'NONE') delete q.detectada;
        const m = (await mem.list(q)).map((a) => a.id);
        const r = (await redis.list(q)).map((a) => a.id);
        assert.deepEqual(r, m);
        for (const a of await redis.list(q)) {
          if (q.tipo) assert.equal(a.tipo, q.tipo);
          if (q.esperada) assert.equal(a.etiqueta_esperada, q.esperada);
          if (q.detectada) assert.equal(a.veredicto?.veredicto, q.detectada);
        }
      }
    },
  ), { numRuns: 100 });
});
