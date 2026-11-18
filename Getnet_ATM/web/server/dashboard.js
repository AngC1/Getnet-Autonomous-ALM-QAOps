// Cálculo puro del Dashboard (KPIs, modelos, ejecuciones) y saneado de secretos. Sin E/S.
import { computeStats } from './stats.js';

export const LABELS = ['CORRECTO', 'INCORRECTO', 'SIN_LOGO', 'AMBIGUO'];
// Mismo modelo por defecto que brand_verifier/verifier.py (DEFAULT_MODEL_ID); BRAND_MODEL_ID lo sustituye.
export const DEFAULT_MODEL_ID = 'us.anthropic.claude-sonnet-4-5-20250929-v1:0';
const num = (n) => (typeof n === 'number' && Number.isFinite(n) ? n : 0);
const round = (n, d = 1) => +n.toFixed(d);
const avg = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);

// ---- Saneado: ninguna respuesta debe contener secretos ----
const SECRET_KEY = /(secret|password|passwd|api[_-]?key|authorization|credential|private[_-]?key|(^|[_-])token$)/i;
const SECRET_VALUE = [
  /\bAKIA[0-9A-Z]{16}\b/g, /\bASIA[0-9A-Z]{16}\b/g,
  /\bBearer\s+[A-Za-z0-9._~+/=-]{8,}/gi,
  /\b(?:sk|pk|rk)[-_][A-Za-z0-9_-]{16,}/g,
  /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}/g, // JWT
  /\b[A-Fa-f0-9]{40,}\b/g, // hex largo
  /\b[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9])/g, // base64/base64url largo
];
export const REDACTED = '[REDACTED]';

export function redactString(s, secrets = []) {
  let out = s;
  for (const v of secrets) if (typeof v === 'string' && v.length >= 6) out = out.split(v).join(REDACTED);
  for (const re of SECRET_VALUE) out = out.replace(re, REDACTED);
  return out;
}

export function sanitize(value, secrets = []) {
  if (typeof value === 'string') return redactString(value, secrets);
  if (Array.isArray(value)) return value.map((v) => sanitize(v, secrets));
  if (value && typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      if (SECRET_KEY.test(k)) continue; // se elimina la clave completa
      out[k] = sanitize(v, secrets);
    }
    return out;
  }
  return value;
}

// ---- KPIs ----
const tokensOf = (m) => num(m?.total_tokens) || num(m?.input_tokens) + num(m?.output_tokens);

export const COMFY_FUENTE = Object.freeze({ HISTORIAL: 'historial de ComfyUI', PIPELINE: 'métricas del pipeline' });
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

// Trabajos de ComfyUI de esta app: del historial de ComfyUI (summarizeHistory) si existe, salvo que no tenga
// trabajos de la app y brand/metrics/comfyui.json sí (p. ej. ComfyUI reiniciado). El uso del equipo solo sale del historial.
function comfyKpi(hist, jobs) {
  const h = isObj(hist) && isObj(hist.app) ? hist : null;
  const equipo = h && isObj(h.equipo)
    ? { trabajos: num(h.equipo.trabajos), segundosGpu: num(h.equipo.segundosGpu), porFlujo: isObj(h.equipo.porFlujo) ? h.equipo.porFlujo : {} }
    : null;
  if (h && (num(h.app.trabajos) > 0 || !jobs.length)) {
    const a = h.app;
    return {
      trabajos: num(a.trabajos), segundosGpu: num(a.segundosGpu), fuente: COMFY_FUENTE.HISTORIAL, cacheados: num(a.cacheados),
      porFlujo: isObj(a.porFlujo) ? a.porFlujo : {}, porEntrada: isObj(a.porEntrada) ? a.porEntrada : {}, equipo,
    };
  }
  return {
    trabajos: jobs.length, segundosGpu: round(jobs.reduce((s, j) => s + num(j?.seconds), 0)), fuente: COMFY_FUENTE.PIPELINE,
    cacheados: null, porFlujo: null, porEntrada: null, equipo,
  };
}

export function latestRun(runs, run) {
  const list = [...(Array.isArray(runs) ? runs : []), ...(run ? [run] : [])].filter((r) => r && typeof r === 'object');
  list.sort((a, b) => String(b.started_at ?? '').localeCompare(String(a.started_at ?? '')));
  return list[0] ?? null;
}

// comfyHistory: resumen de summarizeHistory (comfy-history.js) o null si no se pudo leer el historial.
export function computeDashboard({ assets = [], metrics = {}, env = {}, catalog = null, comfyHistory = null } = {}) {
  const perId = metrics.perAsset ?? {};
  const comfy = metrics.comfyui ?? null;
  const runsRaw = Array.isArray(metrics.runs) ? metrics.runs : [];
  const stats = computeStats(assets);

  const perAsset = assets.map((a) => {
    const m = perId[a.id];
    const det = a.veredicto?.veredicto ?? null;
    return {
      id: a.id, tipo: a.tipo, esperada: a.etiqueta_esperada ?? null, detectada: det,
      acierto: det == null ? null : det === a.etiqueta_esperada,
      confianza: a.veredicto?.confianza ?? null,
      model_id: m?.model_id ?? null, tokens: m ? tokensOf(m) : null,
      latency_ms: m && m.latency_ms != null ? num(m.latency_ms) : null, frames: m && m.frames != null ? num(m.frames) : null,
    };
  });

  const labeled = perAsset.filter((p) => p.esperada && p.detectada);
  const aciertos = labeled.filter((p) => p.acierto).length;
  const withTokens = perAsset.filter((p) => p.tokens != null);
  const byTipo = (t) => withTokens.filter((p) => p.tipo === t).map((p) => p.tokens);
  const metricList = Object.values(perId);
  const jobs = Array.isArray(comfy?.jobs) ? comfy.jobs : [];
  const conf = perAsset.map((p) => p.confianza).filter((c) => typeof c === 'number');
  const lat = perAsset.map((p) => p.latency_ms).filter((n) => n != null);

  const matrix = LABELS.map((e) => LABELS.map((d) => perAsset.filter((p) => p.esperada === e && p.detectada === d).length));

  const kpis = {
    activos: { total: assets.length, imagenes: assets.filter((a) => a.tipo === 'imagen').length, videos: assets.filter((a) => a.tipo === 'video').length },
    precisionEtiquetada: { aciertos, total: labeled.length, porcentaje: labeled.length ? round((aciertos / labeled.length) * 100) : 0 },
    precisionGlobal: { aciertos: stats.aciertos, validados: stats.validados, porcentaje: stats.precision, objetivo: stats.objetivo },
    falsosNegativos: { total: stats.falsosNegativos.length, ids: stats.falsosNegativos },
    confianzaMedia: round(avg(conf), 3),
    porVeredicto: stats.porDetectada,
    tiempoMedioVerificacionMs: Math.round(avg(lat)),
    tokens: {
      entrada: metricList.reduce((s, m) => s + num(m?.input_tokens), 0),
      salida: metricList.reduce((s, m) => s + num(m?.output_tokens), 0),
      total: metricList.reduce((s, m) => s + tokensOf(m), 0),
      medioPorActivo: Math.round(avg(withTokens.map((p) => p.tokens))),
      medioPorImagen: Math.round(avg(byTipo('imagen'))),
      medioPorVideo: Math.round(avg(byTipo('video'))),
    },
    llamadas: metricList.reduce((s, m) => s + num(m?.calls), 0),
    comfyui: comfyKpi(comfyHistory, jobs),
  };

  // Modelos
  const last = latestRun(runsRaw, metrics.run);
  const currentModel = last?.model_id || env.BRAND_MODEL_ID || DEFAULT_MODEL_ID;
  const usage = metrics.models && typeof metrics.models === 'object' ? metrics.models : {};
  const models = [];
  const seen = new Set();
  const addBedrock = (id, u) => {
    seen.add(id);
    models.push({
      model_id: id, servicio: u?.service || 'Amazon Bedrock Converse — visión / texto', region: 'us-east-1',
      llamadas: num(u?.calls), tokens_entrada: num(u?.input_tokens), tokens_salida: num(u?.output_tokens),
      actual: id === currentModel, uso: id === currentModel ? 'Verificación de marca (actual)' : 'Visión / texto',
    });
  };
  if (currentModel) addBedrock(currentModel, usage[currentModel]);
  for (const [id, u] of Object.entries(usage)) if (!seen.has(id)) addBedrock(id, u);
  models.push({ model_id: 'stable-audio', servicio: 'Stability AI Stable Audio', region: 'us-east-1', llamadas: 0, actual: false, uso: 'Cortinas sonoras de los vídeos' });
  const wf = (slug) => (catalog?.workflows ?? []).find((w) => w.slug === slug);
  const pshot = wf('product-shot'); const i2v = wf('image-to-video');
  models.push({ model_id: 'FLUX.2', servicio: `ComfyUI workflow FLUX.2 ${pshot?.slug ?? 'product-shot'}`, region: 'us-east-2', llamadas: 0, actual: false, uso: pshot?.summary ?? 'Generación de imágenes de producto' });
  models.push({ model_id: 'Wan2.2', servicio: `ComfyUI workflow Wan2.2 ${i2v?.slug ?? 'image-to-video'}`, region: 'us-east-2', llamadas: 0, actual: false, uso: i2v?.summary ?? 'Imagen a vídeo' });

  const runs = [...runsRaw, ...(metrics.run && !runsRaw.some((r) => r?.run_id === metrics.run.run_id) ? [metrics.run] : [])]
    .filter((r) => r && typeof r === 'object')
    .sort((a, b) => String(b.started_at ?? '').localeCompare(String(a.started_at ?? '')))
    .slice(0, 10)
    .map((r) => ({
      run_id: r.run_id ?? null, started_at: r.started_at ?? null, finished_at: r.finished_at ?? null, model_id: r.model_id ?? null,
      assets_verified: num(r.assets_verified), total_tokens: num(r.total_tokens) || num(r.input_tokens) + num(r.output_tokens),
      duration_s: num(r.duration_s),
      stages: (Array.isArray(r.stages) ? r.stages : []).map((s) => ({ name: String(s?.name ?? ''), status: s?.status ?? null, seconds: num(s?.seconds) })),
    }));

  return {
    kpis, perAsset, matrix: { labels: LABELS, filas: 'esperada', columnas: 'detectada', valores: matrix },
    models, currentModel, runs,
    comfyJobs: jobs.slice(0, 30).map((j) => ({ id: j?.id ?? null, step: j?.step ?? null, workflow: j?.workflow ?? null, status: j?.status ?? null, seconds: num(j?.seconds) })),
  };
}
