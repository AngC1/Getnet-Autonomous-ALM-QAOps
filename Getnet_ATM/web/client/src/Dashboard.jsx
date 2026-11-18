import React, { useCallback, useEffect, useState } from 'react';
import { api } from './api.js';
import { barWidths, breakdown, fmt, fmtBytes, fmtHora, fmtSeg } from './chart.js';
import { Skeleton, Empty, IconAlert, IconRefresh } from './ui.jsx';
const COLOR = { CORRECTO: 'ok', INCORRECTO: 'bad', SIN_LOGO: 'none', AMBIGUO: 'warn' };
const FILL = { CORRECTO: '#34d399', INCORRECTO: '#f87171', SIN_LOGO: '#94a3b8', AMBIGUO: '#fbbf24' };
const Badge = ({ v }) => <span className={`badge ${COLOR[v] ?? 'none'}`}>{v ?? '—'}</span>;
const Kpi = ({ label, value, sub, tone }) => (
  <div className={`card glass kpi ${tone ?? ''}`} role="group" aria-label={label}>
    <span className="num">{value}</span><span>{label}</span>{sub && <small>{sub}</small>}
  </div>
);
const Status = ({ s }) => <span className={`status ${s === 'ok' ? 'up' : 'down'}`}>{s === 'ok' ? '● Operativo' : '● Error'}</span>;

function TokenChart({ rows }) {
  const data = rows.filter((r) => r.tokens != null);
  if (!data.length) return <p className="muted">Sin métricas de tokens todavía.</p>;
  const widths = barWidths(data.map((r) => r.tokens), 100);
  const rowH = 22;
  const alt = `Tokens por activo: ${data.map((r) => `${r.id} ${r.tokens}`).join(', ')}.`;
  return (
    <figure>
      <svg role="img" aria-label={alt} viewBox={`0 0 600 ${data.length * rowH + 4}`} className="chart">
        <title>Tokens por activo</title>
        {data.map((r, i) => (
          <g key={r.id} transform={`translate(0 ${i * rowH + 2})`}>
            <text x="0" y="14" fontSize="11" className="ct">{r.id.slice(0, 22)}</text>
            <rect x="170" y="2" width={Math.max(1, widths[i] * 3.5)} height="16" rx="4" fill={r.tipo === 'video' ? '#818cf8' : '#22d3ee'} />
            <text x={175 + widths[i] * 3.5} y="14" fontSize="11" className="ct">{fmt(r.tokens)}</text>
          </g>
        ))}
      </svg>
      <figcaption><span className="key img" /> Imagen <span className="key vid" /> Vídeo</figcaption>
    </figure>
  );
}

function Verdicts({ counts }) {
  const entries = Object.entries(counts ?? {});
  const total = entries.reduce((s, [, n]) => s + n, 0);
  const alt = `Distribución de veredictos: ${entries.map(([k, n]) => `${k} ${n}`).join(', ')}.`;
  return (
    <figure>
      <div role="img" aria-label={alt} className="stack">
        {entries.map(([k, n]) => n > 0 && <div key={k} style={{ width: `${(n / total) * 100}%`, background: FILL[k] }} title={`${k}: ${n}`} />)}
      </div>
      <ul className="legend">{entries.map(([k, n]) => <li key={k}><Badge v={k} /> {n}</li>)}</ul>
    </figure>
  );
}

function Matrix({ m }) {
  return (
    <table className="matrix">
      <caption>Matriz de confusión: esperada (filas) vs detectada (columnas)</caption>
      <thead><tr><th scope="col">Esperada \ Detectada</th>{m.labels.map((l) => <th key={l} scope="col">{l}</th>)}</tr></thead>
      <tbody>{m.labels.map((l, i) => (
        <tr key={l}><th scope="row">{l}</th>
          {m.valores[i].map((n, j) => <td key={j} className={i === j ? 'diag' : n ? 'off' : ''}>{n}</td>)}</tr>
      ))}</tbody>
    </table>
  );
}

function Services({ aws }) {
  return (
    <div className="svc-grid">
      {aws.services.map((s) => (
        <article key={s.name} className={`card glass svc ${s.status === 'ok' ? 'ok' : 'bad'}`} aria-label={`${s.name}: ${s.status === 'ok' ? 'operativo' : 'error'}`}>
          <h4>{s.name}</h4><Status s={s.status} />
          <small>Región {s.region}</small>
          {s.detail && <small>{s.detail}</small>}
          {s.outputs && <small>Outputs: {s.outputs.join(', ') || '—'}</small>}
        </article>
      ))}
    </div>
  );
}

// Uso de ComfyUI: trabajos de esta app (historial de ComfyUI o métricas del pipeline) y GPU del equipo.
function ComfyUsage({ c, error }) {
  const groups = [['flujo', 'Por flujo', breakdown(c.porFlujo)], ['entrada', 'Por entrada', breakdown(c.porEntrada)]];
  return (
    <div className="card glass" role="group" aria-labelledby="h-cf-app">
      <h4 id="h-cf-app">Trabajos de esta app: {fmt(c.trabajos)} · {fmtSeg(c.segundosGpu)} s de GPU</h4>
      {groups.map(([id, label, rows]) => rows.length > 0 && (
        <React.Fragment key={id}>
          <small id={`cf-${id}`}>{label}</small>
          <ul className="legend tight" aria-labelledby={`cf-${id}`}>
            {rows.map(([k, v]) => <li key={k}>{k}: <strong>{fmt(v.trabajos)}</strong> · {fmtSeg(v.segundosGpu)} s</li>)}
          </ul>
        </React.Fragment>
      ))}
      {c.cacheados > 0 && <small>{fmt(c.cacheados)} servidos desde la caché de ComfyUI</small>}
      <small>GPU del equipo (historial): {c.equipo
        ? `${fmt(c.equipo.trabajos)} trabajos · ${fmtSeg(c.equipo.segundosGpu)} s`
        : `no disponible${error ? ` (${error})` : ''}`}</small>
      <small>Fuente: {c.fuente ?? '—'}</small>
    </div>
  );
}

const FEW_JOBS = 10;
function ComfyJobs({ rows }) {
  const [all, setAll] = useState(false);
  if (!rows.length) return <p className="muted">Sin trabajos de esta app en el historial de ComfyUI.</p>;
  const shown = all ? rows : rows.slice(0, FEW_JOBS);
  return (
    <div className="cf-jobs">
      <div className="scroll" id="cf-jobs"><table>
        <caption>Últimos trabajos de esta app en ComfyUI: {shown.length} de {rows.length}, del más reciente al más antiguo</caption>
        <thead><tr>{['Hora', 'Flujo', 'Entrada', 'Segundos', 'Cacheado'].map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>{shown.map((t, i) => (
          <tr key={`${t.prompt_id}-${i}`}>
            <th scope="row">{t.inicio ? <time dateTime={t.inicio}>{fmtHora(t.inicio)}</time> : '—'}</th>
            <td>{t.flujo}</td><td>{t.entrada}</td><td>{fmtSeg(t.segundos)}</td><td>{t.cacheado ? 'Sí' : 'No'}</td>
          </tr>
        ))}</tbody>
      </table></div>
      {rows.length > FEW_JOBS && (
        <button className="btn" aria-controls="cf-jobs" aria-expanded={all} onClick={() => setAll((v) => !v)}>
          {all ? `Mostrar solo los ${FEW_JOBS} últimos` : `Mostrar los ${rows.length}`}
        </button>
      )}
    </div>
  );
}

export default function Dashboard({ reloadKey = 0 }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(false);
  const load = useCallback((force) => {
    setLoading(true);
    api.dashboard(force).then((x) => { setD(x); setErr(''); }).catch((e) => setErr(e.message)).finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(reloadKey > 0); const t = setInterval(() => load(false), 30000); return () => clearInterval(t); }, [load, reloadKey]);

  if (!d && err) return <Empty icon={<IconAlert size={32} />} title="No se pudo cargar el dashboard">{err}<br /><button className="btn" onClick={() => load(true)}><IconRefresh size={14} /> Reintentar</button></Empty>;
  if (!d) return <div className="dashboard" aria-busy="true" role="status" aria-label="Cargando dashboard"><div className="stats">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="sk-kpi" />)}</div><Skeleton className="sk-block" /></div>;
  const k = d.kpis; const aws = d.aws; const cf = aws.comfyui; const tk = aws.mediaToolkit;
  return (
    <div className="dashboard">
      <div className="dash-head">
        <h2>Dashboard</h2>
        <button className="btn" onClick={() => load(true)} disabled={loading} aria-label="Actualizar datos del dashboard"><IconRefresh size={14} /> {loading ? 'Actualizando…' : 'Actualizar'}</button>
        <small>Generado {new Date(d.generatedAt).toLocaleTimeString('es-ES')} · auto-refresco cada 30 s</small>
      </div>
      {err && <p className="fail" role="alert">{err}</p>}

      <section aria-labelledby="h-kpi"><h3 id="h-kpi">Indicadores clave</h3>
        <div className="stats">
          <Kpi label="Activos" value={k.activos.total} sub={`${k.activos.imagenes} imágenes · ${k.activos.videos} vídeos`} />
          <Kpi label="Precisión con etiquetas esperadas" value={`${k.precisionEtiquetada.porcentaje}%`} sub={`${k.precisionEtiquetada.aciertos}/${k.precisionEtiquetada.total}`} />
          <Kpi label="Precision_Global (validados)" value={`${k.precisionGlobal.porcentaje}%`} sub={`${k.precisionGlobal.aciertos}/${k.precisionGlobal.validados} · ${k.precisionGlobal.objetivo}`} tone={k.precisionGlobal.porcentaje >= 90 ? 'ok' : 'bad'} />
          <Kpi label="Falsos negativos" value={k.falsosNegativos.total} sub={k.falsosNegativos.ids.join(', ') || 'ninguno'} tone={k.falsosNegativos.total ? 'bad' : 'ok'} />
          <Kpi label="Confianza media" value={`${Math.round(k.confianzaMedia * 100)}%`} />
          <Kpi label="Tiempo medio de verificación" value={`${fmt(k.tiempoMedioVerificacionMs)} ms`} />
          <Kpi label="Tokens de entrada" value={fmt(k.tokens.entrada)} />
          <Kpi label="Tokens de salida" value={fmt(k.tokens.salida)} />
          <Kpi label="Tokens medios por activo" value={fmt(k.tokens.medioPorActivo)} sub={`imagen ${fmt(k.tokens.medioPorImagen)} · vídeo ${fmt(k.tokens.medioPorVideo)}`} />
          <Kpi label="Llamadas al modelo" value={fmt(k.llamadas)} />
          <Kpi label="Trabajos ComfyUI de esta app" value={fmt(k.comfyui.trabajos)} sub={`${fmtSeg(k.comfyui.segundosGpu)} s de GPU · ${k.comfyui.fuente ?? '—'}`} />
        </div>
      </section>

      <div className="two-col">
        <section aria-labelledby="h-tok"><h3 id="h-tok">Tokens por activo</h3><TokenChart rows={d.perAsset} /></section>
        <section aria-labelledby="h-ver"><h3 id="h-ver">Distribución de veredictos</h3><Verdicts counts={k.porVeredicto} /></section>
      </div>

      <section aria-labelledby="h-mat"><h3 id="h-mat">Esperada vs detectada</h3><Matrix m={d.matrix} /></section>

      <section aria-labelledby="h-as"><h3 id="h-as">Detalle por activo</h3>
        <div className="scroll"><table>
          <caption className="sr">Resultados de verificación por activo</caption>
          <thead><tr>{['ID', 'Tipo', 'Esperada', 'Detectada', 'Acierto', 'Confianza', 'Modelo', 'Tokens', 'Latencia (ms)', 'Frames'].map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
          <tbody>{d.perAsset.map((p) => (
            <tr key={p.id}><th scope="row">{p.id}</th><td>{p.tipo}</td><td><Badge v={p.esperada} /></td><td><Badge v={p.detectada} /></td>
              <td>{p.acierto == null ? '—' : p.acierto ? <span className="pass">Sí</span> : <span className="fail">No</span>}</td>
              <td>{p.confianza == null ? '—' : `${Math.round(p.confianza * 100)}%`}</td><td>{p.model_id ?? '—'}</td>
              <td>{fmt(p.tokens)}</td><td>{fmt(p.latency_ms)}</td><td>{fmt(p.frames)}</td></tr>
          ))}</tbody>
        </table></div>
      </section>

      <section aria-labelledby="h-mod"><h3 id="h-mod">Modelos en uso</h3>
        <div className="svc-grid">{d.models.map((m) => (
          <article key={m.servicio + m.model_id} className={`card glass svc ${m.actual ? 'current' : ''}`}>
            <h4>{m.model_id} {m.actual && <span className="badge ok">Verificación actual</span>}</h4>
            <small>{m.servicio}</small><small>Región {m.region}</small><small>{m.uso}</small>
            {m.llamadas > 0 && <small>{fmt(m.llamadas)} llamadas · {fmt(m.tokens_entrada)} / {fmt(m.tokens_salida)} tokens</small>}
          </article>
        ))}</div>
      </section>

      <section aria-labelledby="h-aws"><h3 id="h-aws">Arquitectura AWS</h3>
        <p>Región de ejecución <strong>{aws.region}</strong> · Cuenta <strong>{aws.account ?? '—'}</strong></p>
        <Services aws={aws} />
      </section>

      <section aria-labelledby="h-cf"><h3 id="h-cf">ComfyUI</h3>
        <div className="two-col">
          {cf ? (
            <div className={`card glass ${cf.status === 'ok' ? 'ok' : 'bad'}`} role="group" aria-label="Estado de ComfyUI">
              <Status s={cf.status} />
              <small>Host {cf.host ?? d.comfyui.agent_url_host ?? '—'} · Región {cf.region}</small>
              {cf.status === 'ok' ? (<>
                <small>Versión {cf.version ?? '—'}</small>
                {cf.gpus.map((g, i) => <small key={i}>GPU {g.nombre}: VRAM {fmtBytes(g.vram_libre)} libres de {fmtBytes(g.vram_total)}</small>)}
                <small>Cola: {cf.cola.en_curso} en curso · {cf.cola.pendiente} pendientes</small>
              </>) : <small>{cf.detail}</small>}
            </div>) : <p>Sin datos de ComfyUI.</p>}
          <ComfyUsage c={k.comfyui} error={cf?.historialError} />
        </div>
        {cf?.historial && <ComfyJobs rows={cf.historial.trabajos ?? []} />}
      </section>

      <section aria-labelledby="h-tk"><h3 id="h-tk">Unified Media Toolkit</h3>
        {tk ? (
          <div className={`card glass ${tk.status === 'ok' ? 'ok' : 'bad'}`}>
            <Status s={tk.status} />
            <small>Stack {tk.stack} · {tk.stackStatus ?? tk.detail}</small>
            {tk.recursos != null && <small>{tk.recursos} recursos</small>}
            {tk.nombres && <small>{tk.nombres.slice(0, 12).join(', ')}{tk.nombres.length > 12 ? '…' : ''}</small>}
          </div>) : <p>Sin datos del Media Toolkit.</p>}
      </section>

      <section aria-labelledby="h-run"><h3 id="h-run">Últimas ejecuciones</h3>
        {d.runs.length ? d.runs.map((r) => (
          <details key={r.run_id ?? r.started_at} open={d.runs[0] === r}>
            <summary>{r.run_id ?? 'run'} · {r.started_at ?? '—'} · {fmt(r.duration_s)} s · {r.assets_verified} activos · {fmt(r.total_tokens)} tokens</summary>
            {r.stages.length ? (
              <table><caption className="sr">Etapas de {r.run_id}</caption>
                <thead><tr><th scope="col">Etapa</th><th scope="col">Estado</th><th scope="col">Segundos</th></tr></thead>
                <tbody>{r.stages.map((s) => <tr key={s.name}><th scope="row">{s.name}</th><td>{s.status ?? '—'}</td><td>{fmt(s.seconds)}</td></tr>)}</tbody></table>
            ) : <p>Sin etapas registradas.</p>}
          </details>
        )) : <p>Sin ejecuciones registradas todavía.</p>}
      </section>
    </div>
  );
}
