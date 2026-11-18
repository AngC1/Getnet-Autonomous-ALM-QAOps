// Generadores fast-check compartidos por las propiedades de almacén y API.
import fc from 'fast-check';

export const LABELS = ['CORRECTO', 'INCORRECTO', 'SIN_LOGO', 'AMBIGUO'];
export const TIPOS = ['imagen', 'video'];

const veredicto = fc.record({
  veredicto: fc.constantFrom(...LABELS),
  confianza: fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }).filter((n) => !Object.is(n, -0)),
  evidencias: fc.constant([]),
  recomendacion: fc.string({ maxLength: 20 }),
}, { noNullPrototype: true });

export const assetWith = (idArb) => fc.record({
  id: idArb,
  tipo: fc.constantFrom(...TIPOS),
  flujo: fc.string({ maxLength: 12 }),
  etiqueta_esperada: fc.constantFrom(...LABELS),
  etiqueta_validada: fc.boolean(),
}, { requiredKeys: ['id', 'tipo', 'etiqueta_esperada', 'etiqueta_validada'], noNullPrototype: true })
  .chain((a) => fc.option(veredicto, { nil: undefined }).map((v) => (v ? { ...a, veredicto: v } : a)));

export const ID_POOL = ['a', 'b', 'c', 'd', 'e'];
export const poolAsset = assetWith(fc.constantFrom(...ID_POOL));
export const anyAsset = assetWith(fc.stringMatching(/^[A-Za-z0-9_-]{1,64}$/));
