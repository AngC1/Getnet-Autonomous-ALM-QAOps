// Piezas de UI compartidas: iconos SVG propios, badges y utilidades (sin librerías externas).
import React, { useEffect, useRef } from 'react';

export const LABELS = ['CORRECTO', 'INCORRECTO', 'SIN_LOGO', 'AMBIGUO'];
export const COLOR = { CORRECTO: 'ok', INCORRECTO: 'bad', SIN_LOGO: 'none', AMBIGUO: 'warn' };
export const TEXT = { CORRECTO: 'Correcto', INCORRECTO: 'Incorrecto', SIN_LOGO: 'Sin logo', AMBIGUO: 'Ambiguo' };

const I = ({ children, size = 16, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...p}>{children}</svg>
);
export const IconCheck = (p) => <I {...p}><path d="M20 6 9 17l-5-5" /></I>;
export const IconX = (p) => <I {...p}><path d="M18 6 6 18M6 6l12 12" /></I>;
export const IconFilm = (p) => <I {...p}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4" /></I>;
export const IconImage = (p) => <I {...p}><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-5-5L5 21" /></I>;
export const IconAlert = (p) => <I {...p}><path d="M12 9v4M12 17h.01" /><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></I>;
export const IconPlay = (p) => <I {...p}><path d="m6 4 14 8-14 8z" fill="currentColor" /></I>;
export const IconRefresh = (p) => <I {...p}><path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5" /></I>;

export const IconUpload = (p) => <I {...p}><path d="M12 16V4M7 9l5-5 5 5M4 20h16" /></I>;
export const IconShield = (p) => <I {...p}><path d="M12 3 4 6v6c0 5 3.4 8 8 9 4.6-1 8-4 8-9V6z" /><path d="m9 12 2 2 4-4" /></I>;
export const IconSparkles = (p) => <I {...p}><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" /><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" /></I>;
export const IconExternal = (p) => <I {...p}><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></I>;

export const Badge = ({ v }) => <span className={`badge ${COLOR[v] ?? 'none'}`}>{TEXT[v] ?? 'Sin veredicto'}</span>;

export const pct = (c) => Math.round((c ?? 0) * 100);

export const fmtDur = (s) => (typeof s === 'number' && s > 0 ? `${s.toFixed(s % 1 ? 1 : 0)} s` : null);

export const Skeleton = ({ className = '' }) => <div className={`skeleton ${className}`} aria-hidden="true" />;

export const Empty = ({ icon, title, children }) => (
  <div className="state" role="status">
    <div className="state-icon">{icon}</div>
    <strong>{title}</strong>
    {children && <p>{children}</p>}
  </div>
);

const FOCUSABLE = 'button:not([disabled]), [href], select:not([disabled]), input:not([disabled]):not([hidden]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// Diálogo modal accesible: foco inicial, trampa de Tab, Escape, bloqueo de scroll y foco devuelto al cerrar.
// `canClose()` (opcional) permite bloquear Escape/fondo mientras hay una operación en curso.
export function useDialog(onClose, canClose = () => true) {
  const ref = useRef(null);
  const closeRef = useRef(onClose);
  const canRef = useRef(canClose);
  closeRef.current = onClose; canRef.current = canClose;
  useEffect(() => {
    const prev = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const first = ref.current?.querySelector('[data-autofocus]') ?? ref.current;
    first?.focus();
    const h = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (canRef.current()) closeRef.current(); return; }
      if (e.key !== 'Tab' || !ref.current) return;
      const els = [...ref.current.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null);
      if (!els.length) { e.preventDefault(); return; }
      const a = els[0]; const z = els[els.length - 1];
      if (!ref.current.contains(document.activeElement)) { e.preventDefault(); a.focus(); }
      else if (e.shiftKey && (document.activeElement === a || document.activeElement === ref.current)) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    };
    document.addEventListener('keydown', h);
    return () => { document.removeEventListener('keydown', h); document.body.style.overflow = overflow; prev?.focus?.(); };
  }, []);
  return ref;
}
