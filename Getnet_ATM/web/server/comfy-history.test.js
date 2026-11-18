import test from 'node:test';
import assert from 'node:assert/strict';
import { summarizeHistory, FLUJO, ENTRADA, MAX_TRABAJOS, PROMPT_MARKERS } from './comfy-history.js';
import { loadComfyHistory, HISTORY_PATH, HISTORY_TIMEOUT } from './dashboard-sources.js';

// ---- Historial falso con la forma de GET /history ----
const T0 = Date.UTC(2026, 10, 4, 12, 0, 0);
const n = (class_type, inputs = {}) => ({ class_type, inputs });
const productShot = (image, prompt) => ({
  1: n('PrimitiveStringMultiline', { value: prompt }), 2: n('LoadImage', { image }),
  6: n('UNETLoader', { unet_name: 'flux-2-klein-4b.safetensors' }), 9: n('CLIPTextEncode', { text: ['1', 0] }),
  18: n('EmptyFlux2LatentImage', { batch_size: 1 }), 24: n('SaveImage', { filename_prefix: 'product-shot' }),
});
const imageToVideo = (image, prompt) => ({
  1: n('LoadImage', { image }), 2: n('PrimitiveStringMultiline', { value: prompt }),
  16: n('WanImageToVideo', { batch_size: 1 }), 21: n('SaveVideo', { filename_prefix: 'video/image-to-video' }),
});
const adMultishot = (prompt) => ({
  1: n('PrimitiveStringMultiline', { value: prompt }), 5: n('LoadImage', { image: 'remangu-placeholder.png' }),
  40: n('WanImageToVideo', {}), 97: n('SaveVideo', { filename_prefix: 'ads/ad' }),
});
const music = () => ({ 1: n('PrimitiveStringMultiline', { value: 'Upbeat indie pop' }), 10: n('SaveAudioMP3', {}) });

let seq = 0;
// Entrada de historial: start (ms), ms de duración, mensaje final, nodos cacheados, salidas pedidas.
function job(graph, { start = T0 + seq * 60_000, ms = 1000, end = 'execution_success', cached = [], outputs, status_str } = {}) {
  const id = `${String(seq).padStart(8, '0')}-aaaa-bbbb-cccc-${'d'.repeat(12)}`;
  const outs = outputs === undefined ? Object.keys(graph).filter((k) => /^Save/.test(graph[k].class_type)) : outputs;
  const e = {
    prompt: [seq, id, graph, { client_id: 'cliente-secreto', extra_pnginfo: { workflow: 'x' } }, outs],
    status: {
      status_str: status_str ?? (end === 'execution_success' ? 'success' : 'error'), completed: end === 'execution_success',
      messages: [
        ['execution_start', { prompt_id: id, timestamp: start }],
        ['execution_cached', { nodes: cached, prompt_id: id, timestamp: start + 1 }],
        ...(end ? [[end, { prompt_id: id, timestamp: start + ms }]] : []),
      ],
    },
    outputs: {},
  };
  seq += 1;
  return [id, e];
}

const MUG = 'Professional product photo of a white ceramic coffee mug on a wooden desk, with the attached company logo clearly printed on the mug, soft daylight, sharp and legible logo';
const NO_LOGO = 'Professional product photo of a plain white ceramic coffee mug on a wooden desk, soft daylight, no logo, no text, no lettering anywhere';
const MOTION = ' Locked-off static camera, no camera movement, only very subtle ambient motion. The logo stays perfectly static, sharp and fully legible, including the small word below it; no morphing, no warping, no flicker, and no new text appears.';
const CAMERA = 'Fixed wall-mounted security camera, high angle, wide shot of a street ATM built into a bank facade at night, sodium street lights. The camera does not move. No text, no logos.';
const BOTTLE = 'A glass bottle of cold brew coffee on a marble counter, morning light, premium product photography';

test('atribución: solo los trabajos que cumplen las reglas del generador son de la app', () => {
  seq = 0;
  const h = Object.fromEntries([
    job(productShot('logo-ayesa-boletin.webp', MUG), { ms: 3700 }), // app: correcto
    job(productShot('logo-vector_ayesa.webp', MUG), { ms: 2400 }), // app: incorrecto
    job(productShot('remangu-placeholder.png', NO_LOGO), { ms: 1500 }), // app: sin logo
    job(productShot('remangu-placeholder.png', NO_LOGO + MOTION), { ms: 900 }), // app: imagen base de vid-sinlogo-01
    job(imageToVideo('product-shot_00016_.png', MUG + MOTION), { ms: 30_720 }), // app: imagen base
    job(imageToVideo('base.png', CAMERA), { ms: 40_769 }), // equipo: base.png es de demo/generate_clips.py
    job(productShot('remangu-placeholder.png', BOTTLE), { ms: 451 }), // equipo: prompt por defecto
    job(productShot('remangu-placeholder.png', CAMERA), { ms: 1764 }), // equipo: prompt ajeno a generator.py
    job(productShot('logo-ayesa-boletin (1).webp', MUG)), // equipo: otro archivo subido con el mismo nombre
    job(productShot('base.png', MUG)), // equipo: base.png no es una entrada del generador
    job(imageToVideo('remangu-sample-image.jpg', 'Slow cinematic push-in')), // equipo
    job(imageToVideo('logo-ayesa-boletin.webp', MUG)), // equipo: el logo solo cuenta en product-shot
    job(imageToVideo('product-shot_16.png', MUG)), // equipo: no es una salida de SaveImage
    job(adMultishot(NO_LOGO), { ms: 38_831 }), // equipo: imagen por defecto fuera de product-shot
    job(music(), { ms: 1367 }), // equipo: otro
  ]);
  const s = summarizeHistory(h);
  assert.equal(s.equipo.trabajos, 15);
  assert.deepEqual(s.equipo.porFlujo[FLUJO.OTRO], { trabajos: 1, segundosGpu: 1.4 });
  assert.equal(s.equipo.porFlujo[FLUJO.PRODUCT_SHOT].trabajos, 8);
  assert.equal(s.equipo.porFlujo[FLUJO.IMAGE_TO_VIDEO].trabajos, 6);
  assert.equal(s.app.trabajos, 5);
  assert.deepEqual(s.app.porFlujo, {
    [FLUJO.PRODUCT_SHOT]: { trabajos: 4, segundosGpu: 8.5 },
    [FLUJO.IMAGE_TO_VIDEO]: { trabajos: 1, segundosGpu: 30.7 },
    [FLUJO.OTRO]: { trabajos: 0, segundosGpu: 0 },
  });
  assert.deepEqual(Object.fromEntries(Object.entries(s.app.porEntrada).map(([k, v]) => [k, v.trabajos])), {
    [ENTRADA.CORRECTO]: 1, [ENTRADA.INCORRECTO]: 1, [ENTRADA.BASE]: 1, [ENTRADA.SIN_LOGO]: 2,
  });
  assert.equal(s.trabajos.length, 5);
  assert.deepEqual(s.trabajos.map((t) => t.entrada), [ENTRADA.BASE, ENTRADA.SIN_LOGO, ENTRADA.SIN_LOGO, ENTRADA.INCORRECTO, ENTRADA.CORRECTO]);
  assert.ok(s.trabajos.every((t) => t.prompt_id.length === 8 && t.estado === 'completado'));
  // Sin prompts, nombres de archivo ni extra_data en la salida.
  const txt = JSON.stringify(s);
  for (const leak of ['coffee mug', 'security camera', 'logo-ayesa', 'remangu-placeholder', 'base.png', 'cliente-secreto', 'extra_pnginfo']) {
    assert.ok(!txt.includes(leak), `filtrado: ${leak}`);
  }
});

test('atribución: marcadores normalizados, configurables y nunca demasiado cortos', () => {
  seq = 0;
  const h = Object.fromEntries([
    job(productShot('remangu-placeholder.png', '  PROFESSIONAL product photo of a Plain  White ceramic coffee mug on a wooden desk')),
    job(productShot('remangu-placeholder.png', 'Cajero automático de calle por la noche, plano medio realista, pantalla encendida')),
    job(productShot('remangu-placeholder.png', BOTTLE)),
  ]);
  assert.equal(summarizeHistory(h).app.trabajos, 2); // mayúsculas, espacios y tildes no importan
  assert.equal(summarizeHistory(h, { markers: [] }).app.trabajos, 0);
  assert.equal(summarizeHistory(h, { markers: ['a', 'coffee', '', null, 42] }).app.trabajos, 0); // cortos o no texto: ignorados
  assert.equal(summarizeHistory(h, { markers: ['glass bottle of cold brew coffee'] }).app.trabajos, 1);
  assert.equal(summarizeHistory(h, { markers: 'no es una lista' }).app.trabajos, 0);
  assert.ok(PROMPT_MARKERS.length > 0);
});

test('segundos: fin (éxito, error o interrupción) menos execution_start, en ms', () => {
  seq = 0;
  const g = () => productShot('logo-ayesa-boletin.webp', MUG);
  const h = Object.fromEntries([
    job(g(), { start: T0, ms: 3700 }),
    job(g(), { start: T0 + 10_000, ms: 2500, end: 'execution_error' }),
    job(g(), { start: T0 + 20_000, ms: 1200, end: 'execution_interrupted' }),
    job(g(), { start: T0 + 30_000, end: null, status_str: 'success' }), // sin mensaje final
  ]);
  const [, bad] = job(g(), { start: T0 + 40_000, ms: 5000 });
  bad.status.messages[2][1].timestamp = T0 + 39_000; // fin antes del inicio
  h.malo = bad;
  const s = summarizeHistory(h);
  const byStart = Object.fromEntries(s.trabajos.map((t) => [t.inicio, t]));
  assert.deepEqual(byStart[new Date(T0).toISOString()], {
    prompt_id: '00000000', flujo: FLUJO.PRODUCT_SHOT, entrada: ENTRADA.CORRECTO, estado: 'completado', segundos: 3.7,
    inicio: '2026-11-04T12:00:00.000Z', cacheado: false,
  });
  assert.equal(byStart[new Date(T0 + 10_000).toISOString()].segundos, 2.5);
  assert.equal(byStart[new Date(T0 + 10_000).toISOString()].estado, 'error');
  assert.equal(byStart[new Date(T0 + 20_000).toISOString()].segundos, 1.2);
  assert.equal(byStart[new Date(T0 + 20_000).toISOString()].estado, 'interrumpido');
  assert.equal(byStart[new Date(T0 + 30_000).toISOString()].segundos, null);
  assert.equal(byStart[new Date(T0 + 40_000).toISOString()].segundos, null);
  assert.equal(s.app.trabajos, 5);
  assert.equal(s.app.segundosGpu, 7.4); // los trabajos sin tiempos válidos suman 0
  assert.equal(s.equipo.segundosGpu, 7.4);
});

test('cacheados: todas las salidas pedidas vienen de la caché', () => {
  seq = 0;
  const g = () => productShot('logo-vector_ayesa.webp', MUG);
  const all = Object.keys(g());
  const h = Object.fromEntries([
    job(g(), { ms: 4, cached: all }), // re-encolado idéntico: todo cacheado
    job(g(), { ms: 3, cached: ['1', '6', '24'] }), // la salida está en caché aunque haya nodos perezosos sin evaluar
    job(g(), { ms: 2400, cached: ['6', '9', '18'] }), // solo los loaders: hubo GPU
    job(g(), { ms: 5, cached: all, outputs: null }), // sin prompt[4]: se usan los nodos Save*/Preview*
    job(music(), { ms: 1, cached: ['1', '10'] }), // del equipo: no cuenta en la app
  ]);
  const s = summarizeHistory(h);
  assert.equal(s.app.trabajos, 4);
  assert.equal(s.app.cacheados, 3);
  assert.deepEqual(s.trabajos.map((t) => t.cacheado), [true, false, true, true]);
});

test('últimos 50 de la app, del más reciente al más antiguo', () => {
  seq = 0;
  const entries = [];
  for (let i = 0; i < 60; i++) entries.push(job(productShot('logo-ayesa-boletin.webp', MUG), { start: T0 + i * 1000 }));
  const [noTime, e] = job(productShot('logo-ayesa-boletin.webp', MUG));
  e.status.messages = [];
  entries.push([noTime, e]);
  entries.reverse(); // el orden de las claves no importa
  const s = summarizeHistory(Object.fromEntries(entries));
  assert.equal(s.app.trabajos, 61);
  assert.equal(s.trabajos.length, MAX_TRABAJOS);
  assert.equal(s.trabajos[0].inicio, new Date(T0 + 59_000).toISOString());
  assert.equal(s.trabajos.at(-1).inicio, new Date(T0 + 10_000).toISOString());
  assert.ok(s.trabajos.every((t, i, a) => i === 0 || t.inicio <= a[i - 1].inicio));
});

test('entradas malformadas: nunca lanza y no inventa trabajos de la app', () => {
  for (const bad of [null, undefined, [], 'x', 42, true]) {
    const s = summarizeHistory(bad);
    assert.equal(s.equipo.trabajos, 0);
    assert.equal(s.app.trabajos, 0);
    assert.deepEqual(s.trabajos, []);
  }
  seq = 0;
  const [okId, ok] = job(productShot('logo-ayesa-boletin.webp', MUG), { ms: 2000 });
  const h = {
    a: null, b: 'texto', c: 7, d: [], e: {}, f: { prompt: 'x' }, // sin prompt[]: se ignoran
    g: { prompt: [] }, // sin grafo ni estado: equipo, flujo "otro"
    h: { prompt: [1, 'h', null, null, null], status: 'roto' },
    i: { prompt: [1, 'i', { 1: null, 2: 'x', 3: { class_type: 5, inputs: 'no' }, 4: { class_type: 'LoadImage', inputs: { image: ['9', 0] } } }] },
    j: { prompt: [1, 'j', productShot('logo-ayesa-boletin.webp', MUG)], status: { messages: 'roto' } },
    k: { prompt: [1, 'k', productShot('logo-ayesa-boletin.webp', MUG)], status: { messages: [null, [], [1, {}], ['execution_start', null], ['execution_start', { timestamp: 'x' }], ['execution_success', { timestamp: NaN }], ['execution_cached', { nodes: 'x' }]] } },
    l: { prompt: [1, 'l', productShot('logo-ayesa-boletin.webp', MUG)], status: { messages: [['execution_start', { timestamp: 1e20 }], ['execution_success', { timestamp: 1e20 + 5000 }]] } },
    [okId]: ok,
  };
  const s = summarizeHistory(h);
  assert.equal(s.equipo.trabajos, 7); // g, h, i, j, k, l y el válido
  assert.equal(s.equipo.porFlujo[FLUJO.OTRO].trabajos, 3);
  assert.equal(s.app.trabajos, 4); // j, k, l y el válido: el grafo cumple la regla aunque falten tiempos
  assert.equal(s.app.segundosGpu, 2);
  const l = s.trabajos.find((t) => t.prompt_id === 'l');
  assert.equal(l.inicio, null); // timestamps fuera del rango de Date: se descartan
  assert.equal(l.segundos, null);
  assert.equal(s.trabajos.find((t) => t.prompt_id === 'j').estado, 'desconocido'); // sin mensajes legibles
  assert.equal(s.trabajos.find((t) => t.prompt_id === 'k').estado, 'completado'); // hay execution_success, aunque sin hora
  assert.equal(s.trabajos.find((t) => t.prompt_id === 'k').segundos, null);
  assert.equal(s.trabajos[0].prompt_id, okId.slice(0, 8)); // el único con inicio queda primero
});

test('loadComfyHistory: pide /history con 8 s y, si falla, deja la fuente anterior sin lanzar', async () => {
  seq = 0;
  const h = Object.fromEntries([job(productShot('logo-ayesa-boletin.webp', MUG), { ms: 2000 })]);
  const calls = [];
  const ok = await loadComfyHistory(async (path, ms) => { calls.push([path, ms]); return h; });
  assert.deepEqual(calls, [[HISTORY_PATH, HISTORY_TIMEOUT]]);
  assert.equal(HISTORY_PATH, '/history?max_items=1000');
  assert.equal(HISTORY_TIMEOUT, 8000);
  assert.equal(ok.historial.app.trabajos, 1);
  assert.equal(ok.historialError, undefined);
  const timeout = await loadComfyHistory(async () => { throw Object.assign(new Error('Bearer abc'), { name: 'TimeoutError' }); });
  assert.deepEqual(timeout, { historial: null, historialError: 'TimeoutError' });
  const http = await loadComfyHistory(async () => { throw Object.assign(new Error(), { name: 'HTTP401' }); });
  assert.deepEqual(http, { historial: null, historialError: 'HTTP401' });
});
