import { test } from 'node:test';
import assert from 'node:assert/strict';
import fc from 'fast-check';
import { computeStats } from './stats.js';

const LABELS = ['CORRECTO', 'INCORRECTO', 'SIN_LOGO', 'AMBIGUO'];

const assetArb = fc.record({
  id: fc.uuid(),
  etiqueta_esperada: fc.constantFrom(...LABELS),
  etiqueta_validada: fc.boolean(),
  veredicto: fc.option(fc.record({ veredicto: fc.constantFrom(...LABELS) }), { nil: null }),
  duracion_s: fc.option(fc.double({ min: 0, max: 600, noNaN: true }), { nil: undefined }),
});
const assetsArb = fc.array(assetArb, { maxLength: 40 });

const sum = (o) => Object.values(o).reduce((a, b) => a + b, 0);

// Feature: atm-card-incident-video-simulation, Property 24: Coherencia del resto de estadísticas
test('Property 24: Coherencia del resto de estadísticas', () => {
  // **Validates: Requirements 13.9, 13.10, 13.37**
  fc.assert(
    fc.property(assetsArb, (assets) => {
      const stats = computeStats(assets);

      // Objetivo según la precisión sin redondear.
      const validated = assets.filter((a) => a.etiqueta_validada === true && !!a.veredicto);
      const hits = validated.filter((a) => a.veredicto.veredicto === a.etiqueta_esperada).length;
      const raw = validated.length ? (hits / validated.length) * 100 : 0;
      assert.equal(stats.objetivo, raw >= 90 ? 'OBJETIVO ALCANZADO' : 'OBJETIVO NO ALCANZADO');

      // Falsos negativos: exactamente esperada INCORRECTO y detectada CORRECTO.
      const expectedFn = assets
        .filter((a) => a.etiqueta_esperada === 'INCORRECTO' && a.veredicto?.veredicto === 'CORRECTO')
        .map((a) => a.id);
      assert.deepEqual([...stats.falsosNegativos].sort(), [...expectedFn].sort());
      const ids = new Set(assets.map((a) => a.id));
      assert.ok(stats.falsosNegativos.every((id) => ids.has(id)));

      // Tiempo medio.
      const times = assets.map((a) => a.duracion_s).filter((n) => typeof n === 'number');
      const expectedAvg = times.length ? +(times.reduce((a, b) => a + b, 0) / times.length).toFixed(1) : 0;
      assert.equal(stats.tiempoMedioS, expectedAvg);

      // Totales y recuentos.
      assert.equal(stats.total, assets.length);
      assert.equal(sum(stats.porEsperada), assets.length);
      assert.equal(sum(stats.porDetectada), assets.filter((a) => a.veredicto).length);
      assert.ok(sum(stats.porDetectada) <= stats.total);
      assert.ok(sum(stats.porEsperada) <= stats.total);
    }),
    { numRuns: 100 },
  );
});
