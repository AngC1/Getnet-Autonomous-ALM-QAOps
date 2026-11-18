// Datos de demostración. Se usan solo si no hay datos reales en S3 (brand/generated/manifest.json).
const ev = (t, bbox, logo) => ({ timestamp_s: t, bbox, logo_detectado: logo });
const A = (id, tipo, flujo, esperada, detectada, conf, evidencias, rec, extra = {}) => ({
  id, tipo, flujo, etiqueta_esperada: esperada, etiqueta_validada: true, estado: 'GENERADO',
  file: `${id}.${tipo === 'video' ? 'mp4' : 'png'}`, duracion_s: +(3 + conf * 4).toFixed(1),
  veredicto: { veredicto: detectada, confianza: conf, evidencias, recomendacion: rec }, ...extra,
});
const OK = 'Logotipo conforme: Ayesa Digital.';
const BAD = 'Sustituir el logotipo por Ayesa Digital.';
const NONE = 'No se detecta ningún logotipo de Ayesa.';
export const SEED = [
  A('img-correcto-01', 'imagen', 'product-shot', 'CORRECTO', 'CORRECTO', 0.97, [ev(0, [0.2, 0.3, 0.8, 0.6], 'CORRECTO')], OK),
  A('img-correcto-02', 'imagen', 'product-shot', 'CORRECTO', 'CORRECTO', 0.94, [ev(0, [0.1, 0.4, 0.7, 0.7], 'CORRECTO')], OK),
  A('img-correcto-03', 'imagen', 'product-shot', 'CORRECTO', 'AMBIGUO', 0.55, [ev(0, [0.6, 0.7, 0.75, 0.8], 'CORRECTO')], 'Logotipo demasiado pequeño para confirmar la variante.'),
  A('img-incorrecto-01', 'imagen', 'product-shot', 'INCORRECTO', 'INCORRECTO', 0.96, [ev(0, [0.2, 0.3, 0.8, 0.55], 'INCORRECTO')], BAD),
  A('img-incorrecto-02', 'imagen', 'product-shot', 'INCORRECTO', 'INCORRECTO', 0.91, [ev(0, [0.15, 0.35, 0.75, 0.6], 'INCORRECTO')], BAD),
  A('img-incorrecto-03', 'imagen', 'product-shot', 'INCORRECTO', 'CORRECTO', 0.62, [ev(0, [0.2, 0.3, 0.8, 0.6], 'CORRECTO')], OK),
  A('img-sinlogo-01', 'imagen', 'product-shot', 'SIN_LOGO', 'SIN_LOGO', 0.98, [], NONE),
  A('vid-correcto-01', 'video', 'image-to-video', 'CORRECTO', 'CORRECTO', 0.93, [ev(1, [0.2, 0.3, 0.8, 0.6], 'CORRECTO'), ev(4, [0.22, 0.32, 0.8, 0.6], 'CORRECTO')], OK),
  A('vid-correcto-02', 'video', 'image-to-video', 'CORRECTO', 'CORRECTO', 0.9, [ev(2, [0.25, 0.3, 0.8, 0.6], 'CORRECTO')], OK),
  A('vid-incorrecto-01', 'video', 'image-to-video', 'INCORRECTO', 'INCORRECTO', 0.92, [ev(2, [0.2, 0.3, 0.8, 0.55], 'INCORRECTO'), ev(5, [0.2, 0.3, 0.8, 0.55], 'INCORRECTO')], BAD),
  A('vid-atm-mixto-01', 'video', 'image-to-video + ffmpeg', 'INCORRECTO', 'INCORRECTO', 0.89,
    [ev(1, [0.3, 0.2, 0.7, 0.4], 'CORRECTO'), ev(4, [0.3, 0.2, 0.7, 0.4], 'INCORRECTO')], 'Un fotograma INCORRECTO invalida el vídeo. ' + BAD,
    { narrativa: 'Cajero de calle: la pantalla muestra la marca mientras se reporta una tarjeta retenida.' }),
  A('vid-sinlogo-01', 'video', 'text-to-video', 'SIN_LOGO', 'SIN_LOGO', 0.95, [], NONE),
];
