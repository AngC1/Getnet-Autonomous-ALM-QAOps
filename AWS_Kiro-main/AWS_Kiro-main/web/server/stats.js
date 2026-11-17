// Precision_Global solo sobre activos con etiqueta_validada = true (Requirement 9.4).
export function computeStats(assets) {
  const validated = assets.filter((a) => a.etiqueta_validada && a.veredicto);
  const hits = validated.filter((a) => a.veredicto.veredicto === a.etiqueta_esperada).length;
  const precision = validated.length ? (hits / validated.length) * 100 : 0;
  const falseNegatives = assets.filter((a) => a.etiqueta_esperada === 'INCORRECTO' && a.veredicto?.veredicto === 'CORRECTO').map((a) => a.id);
  const times = assets.map((a) => a.duracion_s).filter((n) => typeof n === 'number');
  const count = (f) => Object.fromEntries(['CORRECTO', 'INCORRECTO', 'SIN_LOGO', 'AMBIGUO'].map((v) => [v, assets.filter((a) => f(a) === v).length]));
  return {
    total: assets.length, validados: validated.length, aciertos: hits,
    precision: +precision.toFixed(1), objetivo: precision >= 90 ? 'OBJETIVO ALCANZADO' : 'OBJETIVO NO ALCANZADO',
    falsosNegativos: falseNegatives, tiempoMedioS: times.length ? +(times.reduce((a, b) => a + b, 0) / times.length).toFixed(1) : 0,
    porEsperada: count((a) => a.etiqueta_esperada), porDetectada: count((a) => a.veredicto?.veredicto),
  };
}
