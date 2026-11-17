// Funciones puras (sin React) para dibujar las cajas de evidencia sobre el medio.

// [x_min, y_min, x_max, y_max] normalizado (0..1) -> estilo CSS en porcentaje.
export function bboxToStyle([x0, y0, x1, y1]) {
  return {
    left: `${x0 * 100}%`,
    top: `${y0 * 100}%`,
    width: `${(x1 - x0) * 100}%`,
    height: `${(y1 - y0) * 100}%`,
  };
}

// Imagen: todas las evidencias. Vídeo: las de |timestamp_s - t| <= 0.5.
export function visibleEvidences(evidencias, tipo, t) {
  const evs = evidencias ?? [];
  return tipo === 'imagen' ? evs : evs.filter((e) => Math.abs(e.timestamp_s - t) <= 0.5);
}
