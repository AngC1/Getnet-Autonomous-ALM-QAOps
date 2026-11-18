import test from 'node:test';
import assert from 'node:assert/strict';
import { computeDashboard, sanitize, COMFY_FUENTE } from './dashboard.js';
import { summarizeHistory, FLUJO, ENTRADA } from './comfy-history.js';
import { createApp } from './app.js';
import { MemoryStore } from './store.js';

const v = (veredicto, confianza = 0.9) => ({ veredicto, confianza, evidencias: [] });
const assets = [
  { id: 'i1', tipo: 'imagen', etiqueta_esperada: 'CORRECTO', etiqueta_validada: true, veredicto: v('CORRECTO', 0.8) },
  { id: 'i2', tipo: 'imagen', etiqueta_esperada: 'INCORRECTO', etiqueta_validada: true, veredicto: v('CORRECTO', 0.6) },
  { id: 'v1', tipo: 'video', etiqueta_esperada: 'SIN_LOGO', etiqueta_validada: false, veredicto: v('SIN_LOGO', 1) },
  { id: 'v2', tipo: 'video', etiqueta_esperada: 'CORRECTO', etiqueta_validada: true },
];
const metrics = {
  perAsset: {
    i1: { id: 'i1', tipo: 'imagen', model_id: 'm1', calls: 1, frames: 1, input_tokens: 100, output_tokens: 20, total_tokens: 120, latency_ms: 1000 },
    i2: { id: 'i2', tipo: 'imagen', model_id: 'm1', calls: 2, frames: 1, input_tokens: 80, output_tokens: 20, latency_ms: 3000 },
    v1: { id: 'v1', tipo: 'video', model_id: 'm1', calls: 3, frames: 8, input_tokens: 800, output_tokens: 100, total_tokens: 900, latency_ms: 5000 },
  },
  comfyui: { jobs: [{ id: 'a', seconds: 10.5 }, { id: 'b', seconds: 4 }] },
  runs: [{ run_id: 'r1', started_at: '2025-01-01T00:00:00Z', model_id: 'old' }, { run_id: 'r2', started_at: '2025-02-01T00:00:00Z', model_id: 'new', stages: [{ name: 's', status: 'ok', seconds: 2 }] }],
  models: { new: { service: 'Amazon Bedrock Converse — visión / texto', calls: 6, input_tokens: 980, output_tokens: 140 } },
};

test('KPIs con datos falsos', () => {
  const d = computeDashboard({ assets, metrics, env: {} });
  const k = d.kpis;
  assert.deepEqual(k.activos, { total: 4, imagenes: 2, videos: 2 });
  assert.equal(k.precisionEtiquetada.aciertos, 2);
  assert.equal(k.precisionEtiquetada.total, 3);
  assert.equal(k.precisionGlobal.validados, 2);
  assert.equal(k.precisionGlobal.aciertos, 1);
  assert.deepEqual(k.falsosNegativos.ids, ['i2']);
  assert.equal(k.porVeredicto.CORRECTO, 2);
  assert.equal(k.tiempoMedioVerificacionMs, 3000);
  assert.equal(k.tokens.entrada, 980);
  assert.equal(k.tokens.salida, 140);
  assert.equal(k.tokens.total, 120 + 100 + 900);
  assert.equal(k.tokens.medioPorImagen, 110);
  assert.equal(k.tokens.medioPorVideo, 900);
  assert.equal(k.llamadas, 6);
  assert.deepEqual(k.comfyui, { trabajos: 2, segundosGpu: 14.5, fuente: COMFY_FUENTE.PIPELINE, cacheados: null, porFlujo: null, porEntrada: null, equipo: null });
  assert.equal(d.matrix.valores[0][0], 1); // CORRECTO/CORRECTO
  assert.equal(d.matrix.valores[1][0], 1); // INCORRECTO esperado, CORRECTO detectado
  assert.equal(d.currentModel, 'new');
  assert.equal(d.models.find((m) => m.actual).model_id, 'new');
  assert.equal(d.runs[0].run_id, 'r2');
  assert.equal(d.perAsset.find((p) => p.id === 'v2').tokens, null);
});

test('tolera métricas ausentes', () => {
  const d = computeDashboard({ assets, metrics: {}, env: { BRAND_MODEL_ID: 'envm' } });
  assert.equal(d.kpis.tokens.total, 0);
  assert.equal(d.kpis.llamadas, 0);
  assert.equal(d.kpis.comfyui.trabajos, 0);
  assert.equal(d.kpis.comfyui.fuente, COMFY_FUENTE.PIPELINE);
  assert.equal(d.currentModel, 'envm');
  assert.deepEqual(d.runs, []);
  const e = computeDashboard({});
  assert.equal(e.kpis.activos.total, 0);
  assert.equal(e.kpis.confianzaMedia, 0);
});

const FAKE = {
  token: 'Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdoaWprbG1ub3A', // nosecret: valor ficticio de test
  aws: 'AKIAABCDEFGHIJKLMNOP', // nosecret: valor ficticio de test
  short: 'hunter2hunter2',
};

async function fetchDash(sources, env = {}) {
  const store = new MemoryStore();
  for (const a of assets) await store.upsert(a);
  const app = createApp(store, { getSources: async () => sources, env });
  const server = app.listen(0);
  try {
    const port = server.address().port;
    const r = await fetch(`http://127.0.0.1:${port}/api/dashboard?refresh=1`);
    return { status: r.status, text: await r.text() };
  } finally { server.close(); }
}

test('/api/dashboard nunca incluye secretos', async () => {
  const sources = {
    metrics: { ...metrics, comfyui: { agent_url_host: 'x.example', AgentToken: FAKE.token, jobs: [{ id: FAKE.aws, step: `Bearer ${FAKE.token}`, seconds: 1 }] } },
    live: {
      region: 'us-east-1', account: '123456789012', secrets: [FAKE.short],
      services: [{ name: 'S3', status: 'ok', detail: `clave ${FAKE.aws} y ${FAKE.short}`, CanvasPassword: 'pw', StabilityAIApiKey: 'sk-abcdefghijklmnopqrstuv' }], // nosecret: valor ficticio de test
      comfyui: { status: 'ok', version: '1', token: FAKE.token },
      mediaToolkit: { status: 'ok', nombres: ['A', `sk-${'a'.repeat(30)}`] },
    },
  };
  const { status, text } = await fetchDash(sources, { COMFY_AGENT_TOKEN: 'envtokenvalue99' });
  assert.equal(status, 200);
  for (const s of [FAKE.token, FAKE.aws, FAKE.short, 'sk-abcdefghijklmnopqrstuv', 'CanvasPassword', 'StabilityAIApiKey', 'envtokenvalue99']) { // nosecret: valor ficticio de test
    assert.ok(!text.includes(s), `filtrado: ${s}`);
  }
  assert.ok(text.includes('123456789012'));
  assert.ok(JSON.parse(text).kpis);
});

// ---- KPI de ComfyUI desde el historial (GET /history) ----
const LONG_PROMPT = 'Professional product photo of a plain white ceramic coffee mug on a wooden desk, soft daylight, no logo, no text, '
  + 'no lettering anywhere. Locked-off static camera, no camera movement, only very subtle ambient motion. The logo stays perfectly static.';
const hjob = (id, image, prompt, start, ms, wan = false) => [id, {
  prompt: [0, id, {
    1: { class_type: 'PrimitiveStringMultiline', inputs: { value: prompt } },
    2: { class_type: 'LoadImage', inputs: { image } },
    3: { class_type: wan ? 'WanImageToVideo' : 'EmptyFlux2LatentImage', inputs: {} },
    4: { class_type: wan ? 'SaveVideo' : 'SaveImage', inputs: {} },
  }, { client_id: 'c', auth_token_comfy_org: FAKE.token }, ['4']],
  status: { status_str: 'success', completed: true, messages: [['execution_start', { timestamp: start }], ['execution_success', { timestamp: start + ms }]] },
}];
const HIST = Object.fromEntries([
  hjob('aaaaaaaa-1111', 'logo-ayesa-boletin.webp', LONG_PROMPT, 1_790_000_000_000, 2500),
  hjob('bbbbbbbb-2222', 'product-shot_00016_.png', LONG_PROMPT, 1_790_000_010_000, 30_000, true),
  hjob('cccccccc-3333', 'remangu-sample-image.jpg', 'Team clip', 1_790_000_050_000, 12_000, true),
]);

test('kpis.comfyui: trabajos de la app desde el historial de ComfyUI', () => {
  const c = computeDashboard({ assets, metrics, env: {}, comfyHistory: summarizeHistory(HIST) }).kpis.comfyui;
  assert.equal(c.fuente, COMFY_FUENTE.HISTORIAL);
  assert.equal(c.trabajos, 2); // el historial gana a comfyui.json (2 trabajos falsos)
  assert.equal(c.segundosGpu, 32.5);
  assert.equal(c.cacheados, 0);
  assert.deepEqual(c.porFlujo[FLUJO.PRODUCT_SHOT], { trabajos: 1, segundosGpu: 2.5 });
  assert.deepEqual(c.porFlujo[FLUJO.IMAGE_TO_VIDEO], { trabajos: 1, segundosGpu: 30 });
  assert.equal(c.porEntrada[ENTRADA.CORRECTO].trabajos, 1);
  assert.equal(c.porEntrada[ENTRADA.BASE].trabajos, 1);
  assert.equal(c.equipo.trabajos, 3);
  assert.equal(c.equipo.segundosGpu, 44.5);
});

test('kpis.comfyui: sin historial, o sin trabajos de la app en él, usa comfyui.json', () => {
  const none = computeDashboard({ assets, metrics, comfyHistory: null }).kpis.comfyui;
  assert.deepEqual([none.fuente, none.trabajos, none.equipo], [COMFY_FUENTE.PIPELINE, 2, null]);
  const teamOnly = computeDashboard({ assets, metrics, comfyHistory: summarizeHistory({ x: HIST['cccccccc-3333'] }) }).kpis.comfyui;
  assert.deepEqual([teamOnly.fuente, teamOnly.trabajos, teamOnly.equipo.trabajos], [COMFY_FUENTE.PIPELINE, 2, 1]);
  const empty = computeDashboard({ assets, metrics: {}, comfyHistory: summarizeHistory({}) }).kpis.comfyui;
  assert.deepEqual([empty.fuente, empty.trabajos], [COMFY_FUENTE.HISTORIAL, 0]);
  const junk = computeDashboard({ assets, metrics, comfyHistory: { app: 'x' } }).kpis.comfyui;
  assert.deepEqual([junk.fuente, junk.trabajos], [COMFY_FUENTE.PIPELINE, 2]);
});

test('/api/dashboard con historial: sin token ni prompts de más de 120 caracteres', async () => {
  const sources = {
    metrics: {},
    live: { region: 'us-east-1', account: '123456789012', secrets: [FAKE.token], services: [],
      comfyui: { name: 'ComfyUI', status: 'ok', historial: summarizeHistory(HIST) } },
  };
  const { status, text } = await fetchDash(sources, { COMFY_AGENT_TOKEN: FAKE.token });
  assert.equal(status, 200);
  const body = JSON.parse(text);
  assert.equal(body.kpis.comfyui.fuente, COMFY_FUENTE.HISTORIAL);
  assert.equal(body.kpis.comfyui.trabajos, 2);
  assert.equal(body.aws.comfyui.historial.trabajos.length, 2);
  assert.equal(body.aws.comfyui.historial.trabajos[0].prompt_id, 'bbbbbbbb');
  for (const leak of [FAKE.token, 'auth_token_comfy_org', 'client_id']) assert.ok(!text.includes(leak), `filtrado: ${leak}`);
  for (let i = 0; i + 121 <= LONG_PROMPT.length; i++) assert.ok(!text.includes(LONG_PROMPT.slice(i, i + 121)), 'prompt de más de 120 caracteres');
});

test('/api/dashboard responde sin fuentes ni métricas', async () => {
  const { status, text } = await fetchDash({});
  assert.equal(status, 200);
  assert.equal(JSON.parse(text).kpis.tokens.total, 0);
  const r2 = await fetchDash(undefined);
  assert.equal(r2.status, 200);
});

test('sanitize elimina claves secretas pero conserva *_tokens', () => {
  const o = sanitize({ input_tokens: 5, total_tokens: 7, agent_token: 'x', nested: { password: 'p', ok: 1 } });
  assert.deepEqual(o, { input_tokens: 5, total_tokens: 7, nested: { ok: 1 } });
});
