// Verificación y auditoría: hook del job, diálogo de confirmación y panel de progreso.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api, REPORT_URL } from './api.js';
import { pollJob, statusText, isFinished } from './verify.js';
import { useDialog, IconCheck, IconAlert, IconX, IconExternal } from './ui.jsx';

// Estado del job con sondeo cada 2 s. `onFinished(job)` se invoca una vez al terminar.
export function useVerifyJob(onFinished) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const doneRef = useRef(onFinished);
  doneRef.current = onFinished;
  const running = job?.status === 'running';
  const jobId = job?.id;

  // Retoma un job en curso si se recarga la página.
  useEffect(() => { api.latestJob().then((j) => { if (j?.status === 'running') setJob(j); }).catch(() => {}); }, []);

  useEffect(() => {
    if (!running) return undefined;
    let cancelled = false;
    pollJob(api.job, jobId, { onUpdate: (j) => !cancelled && setJob(j), isCancelled: () => cancelled })
      .then((j) => { if (j && !cancelled) doneRef.current?.(j); })
      .catch(() => { if (!cancelled) setError('Se perdió la conexión con la verificación. Reintenta en unos segundos.'); });
    return () => { cancelled = true; };
  }, [running, jobId]);

  const start = useCallback(async (only) => {
    setError(''); setStarting(true);
    try { setJob(await api.startVerify(only)); return true; }
    catch (e) {
      setError(e.message);
      api.latestJob().then((j) => { if (j?.status === 'running') setJob(j); }).catch(() => {});
      return false;
    } finally { setStarting(false); }
  }, []);
  const startGenerate = useCallback(async (body) => {
    setError(''); setStarting(true);
    try { setJob(await api.startGenerate(body)); return true; }
    catch (e) {
      setError(e.message);
      api.latestJob().then((j) => { if (j?.status === 'running') setJob(j); }).catch(() => {});
      return false;
    } finally { setStarting(false); }
  }, []);
  const dismiss = useCallback(() => { setJob((j) => (isFinished(j) ? null : j)); setError(''); }, []);
  return { job, error, starting, busy: running || starting, start, startGenerate, dismiss };
}

export function ConfirmVerify({ options, onConfirm, onClose }) {
  const [scope, setScope] = useState(options[0].value);
  const ref = useDialog(onClose);
  const chosen = options.find((o) => o.value === scope) ?? options[0];
  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="panel dlg" role="dialog" aria-modal="true" aria-labelledby="cv-title" aria-describedby="cv-desc" tabIndex={-1} ref={ref}>
        <button className="close" onClick={onClose} aria-label="Cerrar"><IconX size={18} /></button>
        <h2 id="cv-title">Lanzar verificación y auditoría</h2>
        <p id="cv-desc" className="muted">Cada activo se analiza con Amazon Bedrock y al terminar se genera el informe de auditoría. Puede tardar unos minutos.</p>
        <fieldset className="scope">
          <legend className="eyebrow">Alcance</legend>
          {options.map((o) => (
            <label key={o.value} className="radio">
              <input type="radio" name="scope" value={o.value} checked={scope === o.value} onChange={() => setScope(o.value)} {...(o.value === options[0].value ? { 'data-autofocus': true } : {})} />
              <span>{o.label}</span>
            </label>
          ))}
        </fieldset>
        <div className="dlg-actions">
          <button className="btn" onClick={onClose}>Cancelar</button>
          <button className="btn primary" onClick={() => onConfirm(chosen.only)}>Lanzar verificación</button>
        </div>
      </div>
    </div>
  );
}

export function JobPanel({ job, error, onClose }) {
  const logRef = useRef(null);
  const text = job?.log ?? '';
  useEffect(() => { const el = logRef.current; if (el) el.scrollTop = el.scrollHeight; }, [text]);
  if (!job && !error) return null;
  const running = job?.status === 'running';
  const ok = job?.status === 'succeeded';
  const gen = job?.kind === 'generate';
  const showReport = ok && (!gen || job?.params?.verify);
  return (
    <aside className={`job-panel glass ${ok ? 'ok' : job && !running ? 'bad' : ''}`} aria-label={gen ? 'Progreso de la generación' : 'Progreso de la verificación'}>
      <div className="job-head">
        {running && <span className="spinner" aria-hidden="true" />}
        {ok && <IconCheck size={18} />}
        {job && !running && !ok && <IconAlert size={18} />}
        <strong role="status">{statusText(job)}</strong>
        {isFinished(job) && <button className="close-sm" onClick={onClose} aria-label={gen ? 'Cerrar panel de generación' : 'Cerrar panel de verificación'}><IconX size={16} /></button>}
      </div>
      {gen && (
        <ol className="phases" aria-label="Fases">
          {[['generating', 'Generando en ComfyUI'], ...(job.params?.verify ? [['verifying', 'Verificando con Bedrock']] : [])].map(([p, l], i) => {
            const cur = job.phase === p; const past = i === 0 && job.phase === 'verifying';
            const cls = past ? 'done' : cur ? (running ? 'on' : ok ? 'done' : 'fail') : '';
            return <li key={p} className={cls} aria-current={cur && running ? 'step' : undefined}>{l}</li>;
          })}
        </ol>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {job && (
        <pre ref={logRef} className="job-log" aria-live="polite" aria-label={gen ? 'Registro de la generación' : 'Registro de la verificación'} tabIndex={0}>{text || 'Iniciando…'}</pre>
      )}
      {showReport && (
        <a className="btn primary" href={REPORT_URL} target="_blank" rel="noopener noreferrer">
          Ver informe de auditoría <IconExternal size={14} /><span className="sr"> (se abre en una pestaña nueva)</span>
        </a>
      )}
    </aside>
  );
}
