// Lógica pura del job de verificación: sondeo, textos de estado y alcance.
import { generateStatusText } from './generate.js';

export const POLL_MS = 2000;

export const isFinished = (job) => !!job && job.status !== 'running';

export const STATUS_TEXT = {
  running: 'Verificando…',
  succeeded: 'Verificación completada',
  failed: 'La verificación ha fallado',
};
export const statusText = (job) => (job?.kind === 'generate' ? generateStatusText(job) : STATUS_TEXT[job?.status] ?? 'Sin verificaciones');

// Opciones del diálogo de confirmación. `filtered` = activos visibles con los filtros actuales.
export function scopeOptions({ total, filtered, hasFilters }) {
  const opts = [{ value: 'all', label: `Todos los activos (${total})`, only: null }];
  if (hasFilters && filtered.length > 0) {
    opts.push({ value: 'filtered', label: `Solo los activos filtrados (${filtered.length})`, only: filtered });
  }
  return opts;
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// Consulta el job cada `intervalMs` hasta que termina. Tolera fallos puntuales de red (maxErrors seguidos).
export async function pollJob(getJob, id, { onUpdate = () => {}, intervalMs = POLL_MS, sleep = wait, isCancelled = () => false, maxErrors = 5 } = {}) {
  let errors = 0;
  for (;;) {
    if (isCancelled()) return null;
    try {
      const job = await getJob(id);
      errors = 0;
      if (isCancelled()) return null;
      onUpdate(job);
      if (isFinished(job)) return job;
    } catch (e) {
      if (++errors >= maxErrors) throw e;
    }
    await sleep(intervalMs);
  }
}
