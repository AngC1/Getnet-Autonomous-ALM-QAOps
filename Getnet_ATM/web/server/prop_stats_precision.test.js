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

const isValidated = (a) => a.etiqueta_validada === true && !!a.veredicto;

// Feature: atm-card-incident-video-simulation, Property 23: Precision_Global solo sobre validados, en rango
test('Property 23: Precision_Global solo sobre validados, en rango', () => {
  // **Validates: Requirements 13.8, 13.37**
  fc.assert(
    fc.property(assetsArb, assetsArb, (assets, extra) => {
      const stats = computeStats(assets);
      const validated = assets.filter(isValidated);
      const hits = validated.filter((a) => a.veredicto.veredicto === a.etiqueta_esperada).length;
      const expected = validated.length ? +((hits / validated.length) * 100).toFixed(1) : 0;

      assert.equal(stats.validados, validated.length);
      assert.equal(stats.aciertos, hits);
      assert.equal(stats.precision, expected);
      assert.ok(stats.precision >= 0 && stats.precision <= 100);
      if (validated.length === 0) assert.equal(stats.precision, 0);

      // Añadir activos no validados no cambia la precisión.
      const unvalidated = extra.map((a) => ({ ...a, etiqueta_validada: false }));
      const withExtra = computeStats([...assets, ...unvalidated]);
      assert.equal(withExtra.precision, stats.precision);
      assert.equal(withExtra.validados, stats.validados);
      assert.equal(withExtra.aciertos, stats.aciertos);
    }),
    { numRuns: 100 },
  );
});
