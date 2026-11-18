import test from 'node:test';
import assert from 'node:assert/strict';
import { barWidths, fmt, fmtSeg, fmtHora, breakdown } from './chart.js';

test('barWidths escala al máximo y tolera vacíos/NaN', () => {
  assert.deepEqual(barWidths([50, 100, 0]), [50, 100, 0]);
  assert.deepEqual(barWidths([]), []);
  assert.deepEqual(barWidths([0, NaN]), [0, 0]);
});
test('fmt devuelve guion para no numéricos', () => {
  assert.equal(fmt(null), '—');
  assert.equal(fmt(5), '5');
});
test('fmtSeg: un decimal con coma; guion si no hay dato', () => {
  assert.equal(fmtSeg(441.94), '441,9');
  assert.equal(fmtSeg(0.004), '0,0');
  assert.equal(fmtSeg(30), '30,0');
  for (const v of [null, undefined, NaN, '3']) assert.equal(fmtSeg(v), '—');
});
test('fmtHora: hora local de una fecha ISO; guion si no es válida', () => {
  assert.match(fmtHora('2026-11-04T13:52:27.186Z'), /^\d{1,2}:\d{2}:\d{2}$/);
  for (const v of [null, undefined, '', 'ayer', 1793642147983]) assert.equal(fmtHora(v), '—');
});
test('breakdown: quita filas vacías o malformadas y conserva el orden', () => {
  const o = { 'product-shot (FLUX.2)': { trabajos: 26, segundosGpu: 39.2 }, otro: { trabajos: 0, segundosGpu: 0 }, 'image-to-video (Wan2.2)': { trabajos: 23, segundosGpu: 441.9 }, roto: null, raro: { trabajos: '3' } };
  assert.deepEqual(breakdown(o).map(([k]) => k), ['product-shot (FLUX.2)', 'image-to-video (Wan2.2)']);
  for (const v of [null, undefined, 'x']) assert.deepEqual(breakdown(v), []);
});
