import test from 'node:test';
import assert from 'node:assert/strict';
import fc from 'fast-check';
import { MemoryStore } from './store.js';
import { anyAsset } from './arb_assets.js';
import { mockRedisStore } from './redis_helper.js';

// Feature: atm-card-incident-video-simulation, Property 29: Ida y vuelta de upsert y get en los almacenes
async function check(store) {
  await fc.assert(fc.asyncProperty(anyAsset, async (a) => {
    await store.clear();
    await store.upsert(a);
    assert.deepEqual(await store.get(a.id), a);
    await store.upsert(a);
    await store.upsert(a);
    assert.deepEqual(await store.get(a.id), a);
    assert.equal((await store.list()).filter((x) => x.id === a.id).length, 1);
    assert.equal(await store.get('no-existe-zzz'), null);
  }), { numRuns: 100 });
}

test('Property 29: MemoryStore ida y vuelta e idempotencia', () => check(new MemoryStore()));

test('Property 29: RedisStore ida y vuelta e idempotencia', async (t) => {
  const redis = await mockRedisStore();
  if (!redis) return t.skip('ioredis-mock no disponible');
  await check(redis);
});
