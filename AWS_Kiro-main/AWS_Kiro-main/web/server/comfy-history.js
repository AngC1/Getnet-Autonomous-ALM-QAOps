// Resumen puro del historial de ComfyUI (GET /history): uso de GPU del equipo y de esta app. Sin E/S.
// La salida solo lleva etiquetas, tiempos y estados: nunca prompts, nombres de archivo ni extra_data.
//
// La GPU es compartida. Un trabajo es de la app solo si LoadImage.inputs.image cumple las reglas de
// brand_verifier/generator.py:
// - product-shot con un logo de referencia (references.LOGO_CORRECTO / LOGO_INCORRECTO);
// - image-to-video con una imagen base re-subida por el generador (product-shot_NNNNN_.png). base.png es de
//   demo/generate_clips.py (otro proyecto del equipo) y cuenta solo como GPU del equipo;
// - product-shot con la imagen por defecto (use_product_photo=False, SIN_LOGO) solo si el texto del grafo
//   contiene un marcador de nuestros prompts.

export const FLUJO = Object.freeze({ PRODUCT_SHOT: 'product-shot (FLUX.2)', IMAGE_TO_VIDEO: 'image-to-video (Wan2.2)', OTRO: 'otro' });
export const ENTRADA = Object.freeze({ CORRECTO: 'Ayesa Digital (correcto)', INCORRECTO: 'Ayesa (incorrecto)', BASE: 'imagen base', SIN_LOGO: 'sin logo' });
export const MAX_TRABAJOS = 50;

const LOGOS = new Map([['logo-ayesa-boletin.webp', ENTRADA.CORRECTO], ['logo-vector_ayesa.webp', ENTRADA.INCORRECTO]]);
const BASE_IMAGE = /^product-shot_\d+_\.png$/;
const PLACEHOLDER = 'remangu-placeholder.png';
const FIN = new Set(['execution_success', 'execution_error', 'execution_interrupted']);
const MAX_MS = 8.64e15; // límite de Date: un timestamp fuera de rango no es una fecha
const MIN_MARKER = 12; // un marcador corto atribuiría trabajos ajenos

// Frases de los prompts de generator.py; se comparan sin mayúsculas, tildes ni espacios repetidos.
export const PROMPT_MARKERS = Object.freeze([
  'plain white ceramic coffee mug on a wooden desk', // _NO_LOGO_SCENE (img-sinlogo-01 y vid-sinlogo-01)
  'no logo, no text, no lettering anywhere', // _NO_LOGO_SCENE
  'the logo stays perfectly static, sharp and fully legible', // _MOTION (imagen base de cada vídeo)
  'with the attached company logo', // _LOGO_SCENES
  'cajero automatico de calle por la noche, plano medio realista', // incident.scene_prompt (vid-correcto-02-atm)
]);

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const norm = (s) => s.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
const r1 = (n) => Math.round(n * 10) / 10;
const desc = (a, b) => (a === b ? 0 : a > b ? -1 : 1);
const iso = (ms) => (ms == null ? null : new Date(ms).toISOString());
const buckets = (keys) => Object.fromEntries(keys.map((k) => [k, { trabajos: 0, segundosGpu: 0 }]));
const add = (b, s) => { b.trabajos += 1; b.segundosGpu += s; };
const close = (o) => { for (const v of Object.values(o)) v.segundosGpu = r1(v.segundosGpu); return o; };

function nodesOf(graph) {
  if (!isObj(graph)) return [];
  return Object.entries(graph).filter(([, n]) => isObj(n)).map(([id, n]) => ({
    id, tipo: typeof n.class_type === 'string' ? n.class_type : '', inputs: isObj(n.inputs) ? n.inputs : {},
  }));
}

// Wan en algún class_type -> vídeo Wan2.2; FLUX.2 (nodos Flux2 o un loader flux-2) -> product-shot.
function flujoOf(nodes) {
  if (nodes.some((n) => n.tipo.includes('Wan'))) return FLUJO.IMAGE_TO_VIDEO;
  const flux = nodes.some((n) => /flux2/i.test(n.tipo)
    || (/loader/i.test(n.tipo) && Object.values(n.inputs).some((v) => typeof v === 'string' && /flux-?2/i.test(v))));
  return flux ? FLUJO.PRODUCT_SHOT : FLUJO.OTRO;
}

// Entrada de un trabajo de la app, o null si no cumple ninguna regla (trabajo del equipo).
function entradaOf(flujo, nodes, markers) {
  const images = nodes.filter((n) => n.tipo === 'LoadImage' && typeof n.inputs.image === 'string').map((n) => n.inputs.image.trim());
  if (flujo === FLUJO.PRODUCT_SHOT) {
    const logo = images.find((i) => LOGOS.has(i));
    if (logo) return LOGOS.get(logo);
    if (markers.length && images.includes(PLACEHOLDER)) {
      const text = norm(nodes.flatMap((n) => Object.values(n.inputs).filter((v) => typeof v === 'string')).join('\n'));
      if (markers.some((m) => text.includes(m))) return ENTRADA.SIN_LOGO;
    }
  }
  if (flujo === FLUJO.IMAGE_TO_VIDEO && images.some((i) => BASE_IMAGE.test(i))) return ENTRADA.BASE;
  return null;
}

// Tiempos, estado y caché a partir de status.messages: [[nombre, {timestamp (ms), nodes?}], ...].
function execution(status, outputs, nodes) {
  let start = null; let end = null;
  const cached = new Set(); const seen = new Set();
  for (const m of Array.isArray(status.messages) ? status.messages : []) {
    if (!Array.isArray(m) || typeof m[0] !== 'string') continue;
    const name = m[0]; const data = isObj(m[1]) ? m[1] : {};
    seen.add(name);
    const ts = typeof data.timestamp === 'number' && Math.abs(data.timestamp) <= MAX_MS ? data.timestamp : null;
    if (name === 'execution_start' && ts != null) start = start == null ? ts : Math.min(start, ts);
    else if (FIN.has(name) && ts != null) end = end == null ? ts : Math.max(end, ts);
    else if (name === 'execution_cached' && Array.isArray(data.nodes)) for (const id of data.nodes) cached.add(String(id));
  }
  const segundos = start != null && end != null && end >= start ? Math.round(end - start) / 1000 : null;
  // Cacheado = todas las salidas pedidas (prompt[4]) salieron de la caché: ComfyUI no usó la GPU.
  const outs = Array.isArray(outputs) && outputs.length ? outputs.map(String) : nodes.filter((n) => /^(Save|Preview)/.test(n.tipo)).map((n) => n.id);
  const cacheado = outs.length > 0 && outs.every((id) => cached.has(id));
  const estado = seen.has('execution_interrupted') ? 'interrumpido'
    : seen.has('execution_error') || status.status_str === 'error' ? 'error'
      : status.status_str === 'success' || seen.has('execution_success') ? 'completado' : 'desconocido';
  return { start, segundos, cacheado, estado };
}

/**
 * history: respuesta de GET /history ({prompt_id: {prompt: [n, prompt_id, graph, extra, outputs], status}}).
 * markers: frases de prompt que identifican nuestros trabajos con la imagen por defecto (por defecto PROMPT_MARKERS).
 * Nunca lanza: las entradas malformadas se ignoran o cuentan sin tiempos.
 */
export function summarizeHistory(history, { markers = PROMPT_MARKERS } = {}) {
  const marks = (Array.isArray(markers) ? markers : []).filter((m) => typeof m === 'string').map(norm).filter((m) => m.length >= MIN_MARKER);
  const equipo = { trabajos: 0, segundosGpu: 0, porFlujo: buckets(Object.values(FLUJO)) };
  const app = { trabajos: 0, segundosGpu: 0, cacheados: 0, porFlujo: buckets(Object.values(FLUJO)), porEntrada: buckets(Object.values(ENTRADA)) };
  const mine = [];
  for (const [key, entry] of isObj(history) ? Object.entries(history) : []) {
    if (!isObj(entry) || !Array.isArray(entry.prompt)) continue;
    const [number, , graph, , outputs] = entry.prompt;
    const nodes = nodesOf(graph);
    const flujo = flujoOf(nodes);
    const x = execution(isObj(entry.status) ? entry.status : {}, outputs, nodes);
    const s = x.segundos ?? 0;
    equipo.trabajos += 1; equipo.segundosGpu += s; add(equipo.porFlujo[flujo], s);
    const entrada = entradaOf(flujo, nodes, marks);
    if (!entrada) continue;
    app.trabajos += 1; app.segundosGpu += s; if (x.cacheado) app.cacheados += 1;
    add(app.porFlujo[flujo], s); add(app.porEntrada[entrada], s);
    mine.push({
      start: x.start ?? -Infinity, number: typeof number === 'number' && Number.isFinite(number) ? number : -Infinity,
      row: { prompt_id: key.slice(0, 8), flujo, entrada, estado: x.estado, segundos: x.segundos, inicio: iso(x.start), cacheado: x.cacheado },
    });
  }
  mine.sort((a, b) => desc(a.start, b.start) || desc(a.number, b.number));
  equipo.segundosGpu = r1(equipo.segundosGpu); close(equipo.porFlujo);
  app.segundosGpu = r1(app.segundosGpu); close(app.porFlujo); close(app.porEntrada);
  return { equipo, app, trabajos: mine.slice(0, MAX_TRABAJOS).map((m) => m.row) };
}
