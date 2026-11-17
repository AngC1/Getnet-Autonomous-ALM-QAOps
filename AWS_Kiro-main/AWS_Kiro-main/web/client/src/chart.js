// Utilidades puras del Dashboard (probadas con node:test).
export const barWidths = (values, max = 100) => {
  const top = Math.max(0, ...values.map((v) => (Number.isFinite(v) ? v : 0)));
  return values.map((v) => (top > 0 && Number.isFinite(v) ? Math.round((v / top) * max * 10) / 10 : 0));
};
export const fmt = (n) => (typeof n === 'number' && Number.isFinite(n) ? n.toLocaleString('es-ES') : '—');
export const fmtBytes = (b) => (typeof b === 'number' ? `${(b / 1024 ** 3).toFixed(1)} GB` : '—');
// Segundos con un decimal (442,1); guion si no hay dato.
export const fmtSeg = (n) => (typeof n === 'number' && Number.isFinite(n)
  ? n.toLocaleString('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : '—');
// Hora local de una fecha ISO; guion si falta o no es válida.
export const fmtHora = (iso) => {
  const d = typeof iso === 'string' ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleTimeString('es-ES') : '—';
};
// Desglose {etiqueta: {trabajos, segundosGpu}} -> [[etiqueta, valor]] sin las filas vacías, en el orden recibido.
export const breakdown = (o) => Object.entries(o && typeof o === 'object' ? o : {})
  .filter(([, v]) => v && typeof v.trabajos === 'number' && v.trabajos > 0);
