// Modal "Subir imágenes o vídeos": drag & drop, marca esperada por archivo, previsualización y progreso real.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ACCEPT, LABEL_OPTIONS, newItem, uploadFile, kindOf, fmtSize } from './upload.js';
import { useDialog, IconUpload, IconX, IconCheck, IconAlert, IconImage, IconFilm } from './ui.jsx';

function Preview({ file }) {
  const url = useMemo(() => URL.createObjectURL(file), [file]);
  useEffect(() => () => URL.revokeObjectURL(url), [url]);
  return kindOf(file) === 'video'
    ? <video src={`${url}#t=0.5`} muted playsInline preload="metadata" aria-hidden="true" tabIndex={-1} />
    : <img src={url} alt="" />;
}

export default function UploadDialog({ onClose, onUploaded, onVerify, verifyBusy }) {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const inputRef = useRef(null);
  const ref = useDialog(onClose, () => !busy);

  const patch = useCallback((key, p) => setItems((xs) => xs.map((x) => (x.key === key ? { ...x, ...p } : x))), []);
  const add = (files) => setItems((xs) => [...xs, ...[...files].map((f) => newItem(f))]);
  const remove = (key) => setItems((xs) => xs.filter((x) => x.key !== key));

  const pending = items.filter((x) => x.status === 'pending' || (x.status === 'error' && x.retry));
  const done = items.filter((x) => x.status === 'done');
  const finished = done.length > 0 && !busy && pending.length === 0;

  const upload = async () => {
    setBusy(true);
    for (const it of items.filter((x) => x.status === 'pending' || (x.status === 'error' && x.retry))) {
      patch(it.key, { status: 'uploading', progress: 0, error: null });
      try {
        const r = await uploadFile(it.file, it.label, { onProgress: (p) => patch(it.key, { progress: p }) });
        patch(it.key, { status: 'done', progress: 1, id: r.id });
        onUploaded?.(r);
      } catch (e) { patch(it.key, { status: 'error', error: e.message, retry: true }); }
    }
    setBusy(false);
  };

  const onDrop = (e) => { e.preventDefault(); setOver(false); if (!busy && e.dataTransfer?.files?.length) add(e.dataTransfer.files); };
  const pick = (e) => { if (e.target.files?.length) add(e.target.files); e.target.value = ''; };
  const openPicker = () => inputRef.current?.click();

  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="panel dlg wide" role="dialog" aria-modal="true" aria-labelledby="up-title" aria-describedby="up-desc" tabIndex={-1} ref={ref}>
        <button className="close" onClick={onClose} disabled={busy} aria-label="Cerrar"><IconX size={18} /></button>
        <h2 id="up-title">Subir imágenes o vídeos</h2>
        <p id="up-desc" className="muted">PNG, JPEG o WebP (hasta 5 MB) y MP4, MOV o WebM (hasta 200 MB y 60 s). Indica qué marca esperas ver en cada archivo.</p>

        <div className={`dropzone${over ? ' over' : ''}`} onDragOver={(e) => { e.preventDefault(); if (!busy) setOver(true); }}
          onDragLeave={() => setOver(false)} onDrop={onDrop}>
          <IconUpload size={28} />
          <strong>Arrastra aquí tus archivos</strong>
          <span className="muted">o</span>
          <button type="button" className="btn" onClick={openPicker} disabled={busy} data-autofocus>Elegir archivos</button>
          <input ref={inputRef} type="file" hidden multiple accept={ACCEPT} onChange={pick} aria-label="Seleccionar imágenes o vídeos" />
        </div>

        {items.length > 0 && (
          <ul className="up-list" aria-label="Archivos seleccionados">
            {items.map((it) => (
              <li key={it.key} className={`up-item ${it.status}`}>
                <div className="up-prev">{it.error && !it.retry && !it.file.type.match(/^(image|video)\//) ? (kindOf(it.file) === 'video' ? <IconFilm size={22} /> : <IconImage size={22} />) : <Preview file={it.file} />}</div>
                <div className="up-main">
                  <strong title={it.file.name}>{it.file.name}</strong>
                  <small className="muted">{kindOf(it.file) === 'video' ? 'Vídeo' : 'Imagen'} · {fmtSize(it.file.size)}</small>
                  <label className="up-label">
                    <span className="eyebrow">Marca esperada</span>
                    <select value={it.label} disabled={busy || it.status === 'done'} onChange={(e) => patch(it.key, { label: e.target.value })}>
                      {LABEL_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  </label>
                  {(it.status === 'uploading' || it.status === 'done') && (
                    <div className="up-progress">
                      <progress max="100" value={Math.round(it.progress * 100)} aria-label={`Progreso de ${it.file.name}`} />
                      <span>{Math.round(it.progress * 100)}%</span>
                    </div>
                  )}
                  {it.status === 'done' && <span className="ok-msg"><IconCheck size={14} /> Subido como <code>{it.id}</code></span>}
                  {it.status === 'error' && <p className="error" role="alert"><IconAlert size={14} /> {it.error}</p>}
                </div>
                <button type="button" className="close-sm" onClick={() => remove(it.key)} disabled={busy && it.status === 'uploading'}
                  aria-label={`Quitar ${it.file.name}`}><IconX size={16} /></button>
              </li>
            ))}
          </ul>
        )}

        <div className="dlg-actions">
          <button className="btn" onClick={onClose} disabled={busy}>{finished ? 'Cerrar' : 'Cancelar'}</button>
          {pending.length > 0 && (
            <button className="btn primary" onClick={upload} disabled={busy}>{busy ? 'Subiendo…' : `Subir ${pending.length} ${pending.length === 1 ? 'archivo' : 'archivos'}`}</button>
          )}
          {finished && (
            <button className="btn primary" disabled={verifyBusy} onClick={() => onVerify(done.map((x) => x.id))}
              title={verifyBusy ? 'Hay una verificación en curso' : undefined}>
              Verificar los subidos ahora
            </button>
          )}
        </div>
        <p className="sr" role="status" aria-live="polite">{busy ? 'Subiendo archivos' : finished ? `${done.length} archivos subidos` : ''}</p>
      </div>
    </div>
  );
}
