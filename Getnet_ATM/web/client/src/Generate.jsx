// Modal "Generar con ComfyUI": marca, tipo, escena (preset o personalizada) y verificación opcional.
import React, { useState } from 'react';
import { LOGO_OPTIONS, TIPO_OPTIONS, SCENE_OPTIONS, CUSTOM, PROMPT_MAX, DEFAULT_FORM, validateForm, buildBody, promptLength } from './generate.js';
import { useDialog, IconX, IconSparkles } from './ui.jsx';

function Radios({ name, legend, value, options, onChange, autofocus }) {
  return (
    <fieldset className="scope">
      <legend className="eyebrow">{legend}</legend>
      {options.map(([v, l], i) => (
        <label key={v} className="radio">
          <input type="radio" name={name} value={v} checked={value === v} onChange={() => onChange(v)} {...(autofocus && i === 0 ? { 'data-autofocus': true } : {})} />
          <span>{l}</span>
        </label>
      ))}
    </fieldset>
  );
}

export default function GenerateDialog({ onConfirm, onClose, busy }) {
  const [f, setF] = useState({ ...DEFAULT_FORM });
  const [touched, setTouched] = useState(false);
  const ref = useDialog(onClose);
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }));
  const error = validateForm(f);
  const n = promptLength(f.prompt);
  const submit = (e) => { e.preventDefault(); setTouched(true); if (!error && !busy) onConfirm(buildBody(f)); };
  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="panel dlg" role="dialog" aria-modal="true" aria-labelledby="gen-title" aria-describedby="gen-desc gen-note" tabIndex={-1} ref={ref} onSubmit={submit} noValidate>
        <button type="button" className="close" onClick={onClose} aria-label="Cerrar"><IconX size={18} /></button>
        <h2 id="gen-title">Generar con ComfyUI</h2>
        <p id="gen-desc" className="muted">Crea un activo nuevo con FLUX.2 (imagen) o Wan2.2 (vídeo) y, si quieres, lo verifica con Amazon Bedrock. Aparecerá en la galería al terminar.</p>
        <div className="gen-grid">
          <Radios name="gen-logo" legend="Marca" value={f.logo} options={LOGO_OPTIONS} onChange={set('logo')} autofocus />
          <Radios name="gen-tipo" legend="Tipo" value={f.tipo} options={TIPO_OPTIONS} onChange={set('tipo')} />
        </div>
        <label className="field">
          <span className="eyebrow">Escena</span>
          <select value={f.escena} onChange={(e) => set('escena')(e.target.value)}>
            {SCENE_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        {f.escena === CUSTOM && (
          <label className="field">
            <span className="eyebrow">Describe la escena</span>
            <textarea rows={3} maxLength={PROMPT_MAX} value={f.prompt} onChange={(e) => set('prompt')(e.target.value)}
              placeholder="Por ejemplo: un autobús urbano aparcado en una calle soleada" aria-describedby="gen-count"
              aria-invalid={touched && !!error} required />
            <small id="gen-count" className={`counter${n > PROMPT_MAX ? ' over' : ''}`}>{n}/{PROMPT_MAX} caracteres</small>
          </label>
        )}
        <label className="check">
          <input type="checkbox" checked={f.verify} onChange={(e) => set('verify')(e.target.checked)} />
          <span>Verificar con Amazon Bedrock al terminar</span>
        </label>
        <p id="gen-note" className="gen-note">Se ejecuta en la GPU compartida del equipo (ComfyUI, us-east-2): un trabajo a la vez</p>
        {touched && error && <p className="error" role="alert">{error}</p>}
        {busy && <p className="muted" role="status">Hay un trabajo en curso; espera a que termine.</p>}
        <div className="dlg-actions">
          <button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button type="submit" className="btn primary" disabled={busy}><IconSparkles size={16} /> Generar</button>
        </div>
      </form>
    </div>
  );
}
