// Lógica pura del diálogo "Generar con ComfyUI": opciones, validación y cuerpo de POST api/jobs/generate.
export const PROMPT_MAX = 300;
export const CUSTOM = 'custom';

export const LOGO_OPTIONS = [
  ['CORRECTO', 'Ayesa Digital (correcto)'],
  ['INCORRECTO', 'Ayesa (incorrecto)'],
  ['SIN_LOGO', 'Sin logo'],
];
export const TIPO_OPTIONS = [
  ['imagen', 'Imagen, unos segundos'],
  ['video', 'Vídeo, 1-2 minutos'],
];
// Mismos ids que brand_verifier/ondemand.py SCENES.
export const SCENE_OPTIONS = [
  ['atm', 'Cajero automático en la calle'],
  ['oficina', 'Recepción de oficina'],
  ['valla', 'Valla publicitaria urbana'],
  ['taza', 'Taza en un escritorio'],
  ['camiseta', 'Camiseta'],
  ['movil', 'Pantalla de móvil'],
  [CUSTOM, 'Personalizada'],
];

export const DEFAULT_FORM = Object.freeze({ logo: 'CORRECTO', tipo: 'imagen', escena: 'atm', prompt: '', verify: true });

const CONTROL_RE = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/gu;
// Los saltos de línea del textarea se convierten en espacios (el servidor rechaza caracteres de control).
export const cleanPrompt = (s) => String(s ?? '').replace(/\s+/g, ' ').replace(CONTROL_RE, '').trim();
export const promptLength = (s) => [...cleanPrompt(s)].length;

// Mensaje de error (o null si el formulario es válido).
export function validateForm(f) {
  if (!LOGO_OPTIONS.some(([v]) => v === f.logo)) return 'Elige la marca.';
  if (!TIPO_OPTIONS.some(([v]) => v === f.tipo)) return 'Elige el tipo de activo.';
  if (!SCENE_OPTIONS.some(([v]) => v === f.escena)) return 'Elige una escena.';
  if (f.escena === CUSTOM) {
    const n = promptLength(f.prompt);
    if (!n) return 'Describe la escena personalizada.';
    if (n > PROMPT_MAX) return `La escena admite como máximo ${PROMPT_MAX} caracteres.`;
  }
  return null;
}

export function buildBody(f) {
  const body = { logo: f.logo, tipo: f.tipo, verify: !!f.verify };
  if (f.escena === CUSTOM) body.prompt = cleanPrompt(f.prompt);
  else body.escena = f.escena;
  return body;
}

// Texto de estado del panel de progreso para un job de generación.
export function generateStatusText(job) {
  if (!job) return 'Sin trabajos';
  if (job.status === 'running') return job.phase === 'verifying' ? 'Verificando con Bedrock…' : 'Generando en ComfyUI…';
  if (job.status === 'succeeded') return job.params?.verify ? 'Activo generado y verificado' : 'Activo generado';
  if (job.exit_code === 3) return 'Activo generado; la verificación ha fallado';
  if (job.exit_code === 1) return 'Parámetros no válidos';
  return 'La generación ha fallado';
}
