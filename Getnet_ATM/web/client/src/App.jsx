import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { api } from './api.js';
import Dashboard from './Dashboard.jsx';
import UploadDialog from './Upload.jsx';
import { useVerifyJob, ConfirmVerify, JobPanel } from './Verify.jsx';
import { scopeOptions } from './verify.js';
import { bboxToStyle, visibleEvidences } from './bbox.js';
import {
  LABELS, COLOR, Badge, pct, fmtDur, Skeleton, Empty,
  IconCheck, IconX, IconFilm, IconImage, IconAlert, IconPlay, IconRefresh, IconUpload, IconShield, IconSparkles,
} from './ui.jsx';
import GenerateDialog from './Generate.jsx';

const TABS = [['galeria', 'Galería'], ['dashboard', 'Dashboard']];
const prefersReduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
const shortModel = (id) => id?.replace(/^(us|eu|apac|global)\./, '').replace(/-v\d+:\d+$/, '').replace(/^anthropic\./, '');

function Header({ tab, setTab, model, region, onUpload, onGenerate, onVerify, verifyBusy }) {
  const refs = useRef({});
  const onKey = (e) => {
    const i = TABS.findIndex(([k]) => k === tab);
    let n = null;
    if (e.key === 'ArrowRight') n = (i + 1) % TABS.length;
    else if (e.key === 'ArrowLeft') n = (i - 1 + TABS.length) % TABS.length;
    else if (e.key === 'Home') n = 0;
    else if (e.key === 'End') n = TABS.length - 1;
    if (n == null) return;
    e.preventDefault();
    setTab(TABS[n][0]);
    refs.current[TABS[n][0]]?.focus();
  };
  return (
    <header className="app-header">
      <div className="hdr-inner">
        <div className="brand">
          <span className="monogram" aria-hidden="true"><i /><i /><i /><i /></span>
          <div>
            <h1>Brand Guard <span className="dot">·</span> Ayesa Digital</h1>
            <p>Verificación de marca con Amazon Bedrock + ComfyUI</p>
          </div>
        </div>
        <div className="chips" aria-label="Estado del sistema">
          <span className="chip"><span className="pulse" aria-hidden="true" />Región {region}</span>
          {model && <span className="chip model" title={model}>Modelo {shortModel(model)}</span>}
        </div>
        <div className="hdr-row">
          <div className="tabs" role="tablist" aria-label="Secciones" onKeyDown={onKey}>
            {TABS.map(([k, l]) => (
              <button key={k} id={`tab-${k}`} role="tab" ref={(el) => { refs.current[k] = el; }} aria-selected={tab === k}
                aria-controls={`panel-${k}`} tabIndex={tab === k ? 0 : -1} className={tab === k ? 'tab active' : 'tab'}
                onClick={() => setTab(k)}>{l}</button>
            ))}
          </div>
          <div className="hdr-actions">
            <button type="button" className="btn" onClick={onUpload}><IconUpload size={16} /> Subir imágenes o vídeos</button>
            <button type="button" className="btn" onClick={onGenerate} disabled={verifyBusy} aria-describedby={verifyBusy ? 'verify-busy' : undefined}>
              <IconSparkles size={16} /> Generar con ComfyUI
            </button>
            <button type="button" className="btn primary" onClick={onVerify} disabled={verifyBusy} aria-describedby={verifyBusy ? 'verify-busy' : undefined}>
              <IconShield size={16} /> Lanzar verificación y auditoría
            </button>
            {verifyBusy && <span id="verify-busy" className="sr">Hay un trabajo en curso</span>}
          </div>
        </div>
      </div>
    </header>
  );
}

function Gauge({ value, ok }) {
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  return (
    <div className={`gauge ${ok ? 'ok' : 'bad'}`} style={{ '--p': v }} role="img" aria-label={`Precisión ${v}%`}>
      <span>{v}<small>%</small></span>
    </div>
  );
}

function Hero({ s, loading }) {
  if (loading && !s) {
    return <section className="hero" aria-label="Resumen" aria-busy="true">
      <Skeleton className="sk-hero" /><Skeleton className="sk-kpi" /><Skeleton className="sk-kpi" /><Skeleton className="sk-kpi" />
    </section>;
  }
  if (!s) return null;
  const ok = s.precision >= 90;
  const fn = s.falsosNegativos.length;
  return (
    <section className="hero" aria-label="Resumen">
      <div className={`glass hero-main ${ok ? 'ok' : 'bad'}`}>
        <Gauge value={s.precision} ok={ok} />
        <div>
          <span className="eyebrow">Precisión global</span>
          <strong className="hero-title">{s.aciertos}/{s.validados} validados</strong>
          <span className={`pill ${ok ? 'ok' : 'bad'}`}>{ok ? <IconCheck size={14} /> : <IconAlert size={14} />}{s.objetivo}</span>
        </div>
      </div>
      <div className="glass kpi-tile"><span className="eyebrow">Activos</span><span className="num">{s.total}</span><small>verificados por el modelo</small></div>
      <div className={`glass kpi-tile ${fn ? 'bad' : 'ok'}`}>
        <span className="eyebrow">Falsos negativos</span><span className="num">{fn}</span>
        <small>{s.falsosNegativos.join(', ') || 'ninguno'}</small>
      </div>
      <div className="glass kpi-tile"><span className="eyebrow">Tiempo medio</span><span className="num">{s.tiempoMedioS}<small className="unit">s</small></span><small>por verificación</small></div>
    </section>
  );
}

function Segmented({ label, value, onChange, options }) {
  return (
    <div className="seg-group">
      <span className="seg-label" id={`seg-${label}`}>{label}</span>
      <div className="seg" role="group" aria-labelledby={`seg-${label}`}>
        {options.map(([v, l]) => (
          <button key={v} type="button" className={value === v ? 'on' : ''} aria-pressed={value === v} onClick={() => onChange(v)}>{l}</button>
        ))}
      </div>
    </div>
  );
}

function Filters({ f, setF }) {
  const set = (k) => (v) => setF({ ...f, [k]: v });
  const lab = (x) => [['', 'Todos'], ...LABELS.map((l) => [l, l === 'SIN_LOGO' ? 'Sin logo' : l[0] + l.slice(1).toLowerCase()])];
  return (
    <div className="filters" role="region" aria-label="Filtros">
      <Segmented label="Tipo" value={f.tipo ?? ''} onChange={set('tipo')} options={[['', 'Todos'], ['imagen', 'Imágenes'], ['video', 'Vídeos']]} />
      <Segmented label="Esperada" value={f.esperada ?? ''} onChange={set('esperada')} options={lab()} />
      <Segmented label="Detectada" value={f.detectada ?? ''} onChange={set('detectada')} options={lab()} />
    </div>
  );
}

function Fallback({ tipo, text = 'Sin vista previa' }) {
  return <div className="thumb-fallback">{tipo === 'video' ? <IconFilm size={28} /> : <IconImage size={28} />}<span>{text}</span></div>;
}

function Thumb({ a, videoRef }) {
  const [failed, setFailed] = useState(false);
  if (!a.thumbUrl || failed) return <Fallback tipo={a.tipo} text={a.thumbUrl ? 'No se pudo cargar' : 'Sin vista previa'} />;
  return a.tipo === 'video'
    ? <video ref={videoRef} muted playsInline preload="metadata" loop src={`${a.thumbUrl}#t=1`} onError={() => setFailed(true)} tabIndex={-1} aria-hidden="true" />
    : <img src={a.thumbUrl} loading="lazy" alt={`Vista previa de ${a.id}`} onError={() => setFailed(true)} />;
}

function AssetCard({ a, onOpen, isNew }) {
  const videoRef = useRef(null);
  const pass = a.detectada === a.etiqueta_esperada;
  const dur = fmtDur(a.duracion_s);
  const play = () => { if (!prefersReduced()) videoRef.current?.play?.().catch(() => {}); };
  const stop = () => { const v = videoRef.current; if (v) { v.pause(); try { v.currentTime = 1; } catch { /* aún sin metadatos */ } } };
  return (
    <button className="asset" onClick={() => onOpen(a.id)} aria-label={`Abrir ${a.id}: ${pass ? 'aprobado' : 'fallido'}`}
      onPointerEnter={play} onPointerLeave={stop} onFocus={play} onBlur={stop}>
      <div className="thumb">
        <Thumb a={a} videoRef={videoRef} />
        <div className="thumb-overlay" />
        <span className="tag type">{a.tipo === 'video' ? <IconFilm size={13} /> : <IconImage size={13} />}{a.tipo === 'video' ? 'Vídeo' : 'Imagen'}{dur ? ` · ${dur}` : ''}</span>
        <span className={`tag result ${pass ? 'ok' : 'bad'}`}>{pass ? <IconCheck size={13} /> : <IconX size={13} />}{pass ? 'Aprobado' : 'Fallido'}</span>
        {a.tipo === 'video' && a.thumbUrl && <span className="play-hint" aria-hidden="true"><IconPlay size={14} /></span>}
        <div className="thumb-foot"><Badge v={a.detectada} /></div>
      </div>
      <div className="meta">
        <strong title={a.id}>{a.id}{isNew && <span className="new-badge">Nuevo</span>}</strong>
        <div className="row"><span>Esperada</span><Badge v={a.etiqueta_esperada} /></div>
        <div className="conf" title={`Confianza ${pct(a.confianza)}%`}>
          <div className="bar"><i style={{ width: `${pct(a.confianza)}%` }} className={COLOR[a.detectada] ?? 'none'} /></div>
          <span>{a.confianza == null ? '—' : `${pct(a.confianza)}%`}</span>
        </div>
        {!a.etiqueta_validada && <small className="unval">Sin validar</small>}
      </div>
    </button>
  );
}

function SkeletonGrid() {
  return <div className="grid" aria-busy="true" aria-label="Cargando activos">{Array.from({ length: 8 }, (_, i) => (
    <div key={i} className="asset sk"><Skeleton className="sk-thumb" /><div className="meta"><Skeleton className="sk-line" /><Skeleton className="sk-line short" /></div></div>
  ))}</div>;
}

// Medio con cajas de evidencia animadas.
function Media({ a, t, setT, videoRef }) {
  const [failed, setFailed] = useState(false);
  const evs = visibleEvidences(a.veredicto?.evidencias, a.tipo, t);
  const hasMedia = a.mediaUrl && !failed;
  return (
    <div className="media">
      {hasMedia ? (a.tipo === 'video'
        ? <video ref={videoRef} src={a.mediaUrl} controls playsInline preload="metadata" onTimeUpdate={(e) => setT(e.currentTarget.currentTime)} onError={() => setFailed(true)} />
        : <img src={a.mediaUrl} alt={`Activo ${a.id}`} onError={() => setFailed(true)} />)
        : <div className="placeholder"><IconAlert size={28} />
          <strong>{failed ? 'No se pudo reproducir el medio' : 'Sin medio disponible'}</strong>
          {failed ? <span>El navegador no pudo cargar o decodificar el archivo.</span>
            : <span>Copia <code>{a.file}</code> a <code>web/media/</code> o configura <code>MEDIA_BUCKET</code>.</span>}
        </div>}
      {hasMedia && evs.map((e, i) => (
        <div key={`${e.timestamp_s}-${i}`} className={`bbox ${COLOR[e.logo_detectado]}`} title={e.logo_detectado} style={bboxToStyle(e.bbox)}>
          <span>{e.logo_detectado}</span>
        </div>
      ))}
    </div>
  );
}

const FOCUSABLE = 'button:not([disabled]), [href], select:not([disabled]), input:not([disabled]), video[controls], audio[controls], [tabindex]:not([tabindex="-1"])';

function Detail({ id, onClose, onChanged }) {
  const [a, setA] = useState(null);
  const [t, setT] = useState(0);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const panelRef = useRef(null);
  const videoRef = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => { setA(null); setErr(''); api.asset(id).then(setA).catch((e) => setErr(e.message)); }, [id]);

  // Focus trap, Escape, bloqueo de scroll y foco devuelto al elemento que abrió el modal.
  useEffect(() => {
    const prev = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    panelRef.current?.focus();
    const h = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); closeRef.current(); return; }
      if (e.key !== 'Tab' || !panelRef.current) return;
      const els = [...panelRef.current.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null);
      if (!els.length) { e.preventDefault(); return; }
      const first = els[0]; const last = els[els.length - 1];
      if (!panelRef.current.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
      else if (e.shiftKey && (document.activeElement === first || document.activeElement === panelRef.current)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', h);
    return () => {
      document.removeEventListener('keydown', h);
      document.body.style.overflow = overflow;
      prev?.focus?.();
    };
  }, []);

  const seek = (s) => {
    setT(s);
    const v = videoRef.current;
    if (v) { v.pause(); v.currentTime = s; }
  };
  const validate = async (label) => {
    setBusy(true); setErr('');
    try { await api.validate(id, label); setA(await api.asset(id)); onChanged(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const v = a?.veredicto;
  const pass = a && v?.veredicto === a.etiqueta_esperada;
  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="panel" role="dialog" aria-modal="true" aria-labelledby="dlg-title" tabIndex={-1} ref={panelRef}>
        <button className="close" onClick={onClose} aria-label="Cerrar detalle"><IconX size={18} /></button>
        {!a && !err && <div className="detail-grid" aria-busy="true"><Skeleton className="sk-media" /><div className="side"><Skeleton className="sk-line" /><Skeleton className="sk-line short" /><Skeleton className="sk-block" /></div></div>}
        {!a && err && <Empty icon={<IconAlert size={28} />} title="No se pudo cargar el activo">{err}</Empty>}
        {a && (
          <div className="detail-grid">
            <Media a={a} t={t} setT={setT} videoRef={videoRef} />
            <div className="side">
              <div className="side-head">
                <h2 id="dlg-title">{a.id}</h2>
                <span className={`pill ${pass ? 'ok' : 'bad'}`}>{pass ? <IconCheck size={14} /> : <IconX size={14} />}{pass ? 'Aprobado' : 'Fallido'}</span>
              </div>
              <div className="verdicts">
                <div><span className="eyebrow">Esperada</span><Badge v={a.etiqueta_esperada} /></div>
                <div><span className="eyebrow">Detectada</span><Badge v={v?.veredicto} /></div>
              </div>
              <div className="conf big" aria-label={`Confianza ${pct(v?.confianza)}%`}>
                <div className="conf-head"><span className="eyebrow">Confianza</span><strong>{pct(v?.confianza)}%</strong></div>
                <div className="bar"><i style={{ width: `${pct(v?.confianza)}%` }} className={COLOR[v?.veredicto] ?? 'none'} /></div>
              </div>
              {a.narrativa && <p className="narr">{a.narrativa}</p>}
              <section aria-labelledby="h-rec"><h3 id="h-rec">Recomendación</h3><p>{v?.recomendacion || 'Sin recomendación.'}</p></section>
              {a.audio_prompt && (
                <section className="audio-info" aria-label="Sonido generado con Stability AI">
                  <h3>Sonido generado con Stability AI</h3>
                  <p>Stable Audio · prompt: <em>{a.audio_prompt}</em></p>
                  {a.audioUrl && <audio controls src={a.audioUrl} aria-label={`Cortina sonora de ${a.id}`} />}
                </section>
              )}
              <section aria-labelledby="h-ev"><h3 id="h-ev">Evidencias</h3>
                {v?.evidencias?.length ? (
                  <ul className="evid">{v.evidencias.map((e, i) => (
                    <li key={i}>
                      <button className={a.tipo === 'video' && Math.abs(e.timestamp_s - t) <= 0.5 ? 'active' : ''} onClick={() => seek(e.timestamp_s)}
                        aria-label={a.tipo === 'video' ? `Saltar a ${e.timestamp_s} segundos` : 'Ver evidencia en la imagen'}>
                        {a.tipo === 'video' ? <><IconPlay size={12} />{e.timestamp_s}s</> : 'Imagen'}
                      </button>
                      <Badge v={e.logo_detectado} /> <code>[{e.bbox.join(', ')}]</code>
                    </li>
                  ))}</ul>) : <p className="muted">Sin evidencias.</p>}
              </section>
              {err && <p className="error" role="alert">{err}</p>}
              <div className="actions">
                <span className={a.etiqueta_validada ? 'validated' : 'muted'}>{a.etiqueta_validada ? <><IconCheck size={14} /> Etiqueta validada</> : 'Etiqueta sin validar'}</span>
                <button className="btn primary" disabled={busy} onClick={() => validate()}>Confirmar etiqueta</button>
                <select aria-label="Corregir etiqueta" disabled={busy} value="" onChange={(e) => e.target.value && validate(e.target.value)}>
                  <option value="">Corregir a…</option>{LABELS.map((l) => <option key={l}>{l}</option>)}
                </select>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState('galeria');
  const [f, setF] = useState({});
  const [assets, setAssets] = useState([]);
  const [stats, setStats] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState(null);
  const [err, setErr] = useState('');
  const [info, setInfo] = useState({ model: null, region: 'us-east-1' });
  const [confirm, setConfirm] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const refresh = useCallback(() => {
    setErr('');
    api.stats().then(setStats).catch((e) => setErr(e.message));
    api.assets(f).then((x) => { setAssets(x); setLoaded(true); }).catch((e) => { setErr(e.message); setLoaded(true); });
  }, [f]);
  useEffect(refresh, [refresh]);
  useEffect(() => {
    api.dashboard(false).then((d) => setInfo({ model: d.models?.find((m) => m.actual)?.model_id ?? null, region: d.aws?.region ?? 'us-east-1' })).catch(() => {});
  }, []);
  const [generating, setGenerating] = useState(false);
  const [newIds, setNewIds] = useState(() => new Set());
  const onJobDone = useCallback((job) => {
    refresh(); setReloadKey((k) => k + 1);
    const id = job?.kind === 'generate' && job.result?.estado === 'GENERADO' ? job.result.id : null;
    if (!id) return;
    setNewIds((s) => new Set(s).add(id));
    // El servidor recarga los activos de S3 al terminar el job: espera a que el activo nuevo esté disponible.
    (async () => {
      for (let i = 0; i < 15; i++) {
        try { await api.asset(id); refresh(); setReloadKey((k) => k + 1); setTab('galeria'); setOpen(id); return; }
        catch { await new Promise((r) => setTimeout(r, 1000)); }
      }
    })();
  }, [refresh]);
  const verify = useVerifyJob(onJobDone);
  const launchGenerate = async (body) => { setGenerating(false); await verify.startGenerate(body); };
  const hasFilters = Object.values(f).some(Boolean);
  const options = scopeOptions({ total: stats?.total ?? assets.length, filtered: assets.map((a) => a.id), hasFilters });
  const launch = async (only) => { setConfirm(false); setUploading(false); await verify.start(only); };
  const close = useCallback(() => setOpen(null), []);
  const groups = useMemo(() => ({ imagen: assets.filter((a) => a.tipo === 'imagen'), video: assets.filter((a) => a.tipo === 'video') }), [assets]);
  return (
    <>
      <Header tab={tab} setTab={setTab} model={info.model} region={info.region} onUpload={() => setUploading(true)} onGenerate={() => setGenerating(true)} onVerify={() => setConfirm(true)} verifyBusy={verify.busy} />
      <main>
        <div role="tabpanel" id="panel-galeria" aria-labelledby="tab-galeria" hidden={tab !== 'galeria'}>
          {tab === 'galeria' && <>
            <p className="lead">Ayesa <strong>Digital</strong> es la marca correcta en todo momento. Un solo fotograma con el logo erróneo invalida el vídeo.</p>
            {err && <div className="error banner" role="alert"><IconAlert size={18} /><span>{err}</span><button className="btn" onClick={refresh}><IconRefresh size={14} /> Reintentar</button></div>}
            <Hero s={stats} loading={!err} />
            <Filters f={f} setF={setF} />
            {!loaded && <SkeletonGrid />}
            {loaded && ['imagen', 'video'].map((k) => groups[k].length > 0 && (
              <section key={k} aria-labelledby={`h-${k}`}>
                <h2 id={`h-${k}`} className="sec-title">{k === 'imagen' ? 'Imágenes' : 'Vídeos'} <span className="count">{groups[k].length}</span></h2>
                <div className="grid">{groups[k].map((a) => <AssetCard key={a.id} a={a} onOpen={setOpen} isNew={newIds.has(a.id)} />)}</div>
              </section>
            ))}
            {loaded && !assets.length && !err && <Empty icon={<IconImage size={32} />} title="Sin resultados">Prueba a cambiar o quitar algún filtro.</Empty>}
          </>}
        </div>
        <div role="tabpanel" id="panel-dashboard" aria-labelledby="tab-dashboard" hidden={tab !== 'dashboard'}>
          {tab === 'dashboard' && <Dashboard reloadKey={reloadKey} />}
        </div>
        {tab === 'galeria' && open && <Detail id={open} onClose={close} onChanged={refresh} />}
      </main>
      {confirm && <ConfirmVerify options={options} onConfirm={launch} onClose={() => setConfirm(false)} />}
      {generating && <GenerateDialog onConfirm={launchGenerate} onClose={() => setGenerating(false)} busy={verify.busy} />}
      {uploading && <UploadDialog onClose={() => setUploading(false)} onUploaded={refresh} onVerify={launch} verifyBusy={verify.busy} />}
      <JobPanel job={verify.job} error={verify.error} onClose={verify.dismiss} />
    </>
  );
}
