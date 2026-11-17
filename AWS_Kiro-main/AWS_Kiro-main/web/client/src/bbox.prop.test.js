import { test } from 'node:test';
import assert from 'node:assert/strict';
import fc from 'fast-check';
import { bboxToStyle, visibleEvidences } from './bbox.js';

const EPS = 1e-9;
const pct = (s) => {
  assert.match(s, /^-?[\d.]+(e[+-]?\d+)?%$/i);
  return parseFloat(s);
};

// Genera un par a < b dentro de [0, 1].
const interval = fc
  .tuple(fc.double({ min: 0, max: 1, noNaN: true }), fc.double({ min: 0, max: 1, noNaN: true }))
  .filter(([a, b]) => a !== b)
  .map(([a, b]) => (a < b ? [a, b] : [b, a]));

const validBbox = fc.tuple(interval, interval).map(([[x0, x1], [y0, y1]]) => [x0, y0, x1, y1]);

// Feature: atm-card-incident-video-simulation, Property 30: Mapeo de caja normalizada a porcentajes CSS
// Validates: Requirements 13.13
test('Property 30: bboxToStyle mapea la caja normalizada a porcentajes CSS dentro de 0..100', () => {
  fc.assert(
    fc.property(validBbox, ([x0, y0, x1, y1]) => {
      const s = bboxToStyle([x0, y0, x1, y1]);
      const left = pct(s.left);
      const top = pct(s.top);
      const width = pct(s.width);
      const height = pct(s.height);

      assert.ok(Math.abs(left - x0 * 100) <= EPS);
      assert.ok(Math.abs(top - y0 * 100) <= EPS);
      assert.ok(Math.abs(width - (x1 - x0) * 100) <= EPS);
      assert.ok(Math.abs(height - (y1 - y0) * 100) <= EPS);

      for (const v of [left, top, width, height]) {
        assert.ok(v >= 0 && v <= 100 + EPS);
      }
      assert.ok(left + width <= 100 + EPS);
      assert.ok(top + height <= 100 + EPS);
    }),
    { numRuns: 100 },
  );
});

const evidence = fc.record({
  id: fc.integer(),
  timestamp_s: fc.double({ min: 0, max: 60, noNaN: true }),
});
const evidences = fc.array(evidence, { maxLength: 20 });
const tiempo = fc.double({ min: 0, max: 60, noNaN: true });

// Feature: atm-card-incident-video-simulation, Property 31: Evidencias visibles de un vídeo según el instante
// Validates: Requirements 13.14
test('Property 31: visibleEvidences filtra por instante en vídeo y devuelve todas en imagen', () => {
  fc.assert(
    fc.property(evidences, tiempo, (evs, t) => {
      const snapshot = evs.map((e) => ({ ...e }));

      // Imagen: todas las evidencias.
      const img = visibleEvidences(evs, 'imagen', t);
      assert.equal(img.length, evs.length);
      img.forEach((e, i) => assert.equal(e, evs[i]));

      // Vídeo: exactamente |timestamp_s - t| <= 0.5, en orden, mismas referencias.
      const vid = visibleEvidences(evs, 'video', t);
      const expected = evs.filter((e) => Math.abs(e.timestamp_s - t) <= 0.5);
      assert.equal(vid.length, expected.length);
      vid.forEach((e, i) => assert.equal(e, expected[i]));

      // No muta la entrada.
      assert.equal(evs.length, snapshot.length);
      evs.forEach((e, i) => {
        assert.equal(e.id, snapshot[i].id);
        assert.equal(e.timestamp_s, snapshot[i].timestamp_s);
      });

      // undefined/null => [].
      for (const tipo of ['imagen', 'video']) {
        assert.deepEqual(visibleEvidences(undefined, tipo, t), []);
        assert.deepEqual(visibleEvidences(null, tipo, t), []);
      }
    }),
    { numRuns: 100 },
  );
});
