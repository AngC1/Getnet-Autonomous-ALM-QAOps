import test from 'node:test';
import assert from 'node:assert/strict';
import { pollJob, scopeOptions, statusText, isFinished } from './verify.js';

test('statusText / isFinished', () => {
  assert.equal(statusText({ status: 'running' }), 'Verificando…');
  assert.equal(statusText({ status: 'succeeded' }), 'Verificación completada');
  assert.equal(statusText(null), 'Sin verificaciones');
  assert.equal(isFinished({ status: 'running' }), false);
  assert.equal(isFinished({ status: 'failed' }), true);
});

test('scopeOptions: todos siempre; filtrados solo con filtros y resultados', () => {
  assert.deepEqual(scopeOptions({ total: 12, filtered: ['a'], hasFilters: false }).map((o) => o.value), ['all']);
  assert.deepEqual(scopeOptions({ total: 12, filtered: [], hasFilters: true }).map((o) => o.value), ['all']);
  const o = scopeOptions({ total: 12, filtered: ['a', 'b'], hasFilters: true });
  assert.deepEqual(o.map((x) => x.value), ['all', 'filtered']);
  assert.equal(o[0].only, null);
  assert.deepEqual(o[1].only, ['a', 'b']);
});

test('pollJob: sondea hasta terminar, notificando cada estado', async () => {
  const states = ['running', 'running', 'succeeded'];
  const calls = []; const updates = []; const sleeps = [];
  const job = await pollJob(async (id) => { calls.push(id); return { id, status: states.shift() }; }, 'j1', {
    onUpdate: (j) => updates.push(j.status), sleep: async (ms) => { sleeps.push(ms); },
  });
  assert.equal(job.status, 'succeeded');
  assert.deepEqual(calls, ['j1', 'j1', 'j1']);
  assert.deepEqual(updates, ['running', 'running', 'succeeded']);
  assert.deepEqual(sleeps, [2000, 2000]); // cada 2 s
});

test('pollJob: tolera fallos puntuales y se rinde tras varios seguidos', async () => {
  let n = 0;
  const ok = await pollJob(async () => { if (n++ === 0) throw new Error('red'); return { status: 'failed' }; }, 'j', { sleep: async () => {} });
  assert.equal(ok.status, 'failed');
  await assert.rejects(pollJob(async () => { throw new Error('caído'); }, 'j', { sleep: async () => {}, maxErrors: 3 }), /caído/);
});

test('pollJob: cancelable', async () => {
  let cancelled = false;
  const r = await pollJob(async () => { cancelled = true; return { status: 'running' }; }, 'j', { sleep: async () => {}, isCancelled: () => cancelled });
  assert.equal(r, null);
});
