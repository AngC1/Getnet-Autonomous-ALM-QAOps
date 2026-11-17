import express from 'express';
import compression from 'compression';
import { computeStats } from './stats.js';
import { computeDashboard, sanitize } from './dashboard.js';
import { defaultSources } from './dashboard-sources.js';
import fs from 'node:fs';
import { mediaUrl, audioUrl, MEDIA_DIR, s3Enabled, loadFromS3, loadAssetFromS3, reportUrl, LOCAL_REPORT } from './media.js';
import { createUploadHandler } from './uploads.js';
import { createJobs, JobConflict, ID_RE as JOB_ID_RE, MAX_ONLY, parseGenerateBody } from './jobs.js';

const LABELS = new Set(['CORRECTO', 'INCORRECTO', 'SIN_LOGO', 'AMBIGUO']);
const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

export function createApp(store, {
  distDir, getSources = () => defaultSources({ bucket: process.env.MEDIA_BUCKET }), env = process.env, now = Date.now,
  runRegister, jobs: jobsOpt, loadAsset = loadAssetFromS3, loadAll = loadFromS3, getReportUrl = reportUrl, localReport = LOCAL_REPORT,
} = {}) {
  const app = express();
  app.disable('x-powered-by');
  app.use(compression());
  app.use(express.json({ limit: '10kb' }));
  app.use((_, res, next) => { res.set('X-Content-Type-Options', 'nosniff'); next(); });
  app.use('/media', express.static(MEDIA_DIR, { maxAge: '1h' }));

  let cache = null; // caché del dashboard (30 s)
  const bad = (res, msg) => res.status(400).json({ error: msg });
  const cleanFilter = (q) => {
    const f = {};
    if (['imagen', 'video'].includes(q.tipo)) f.tipo = q.tipo;
    if (LABELS.has(q.esperada)) f.esperada = q.esperada;
    if (LABELS.has(q.detectada)) f.detectada = q.detectada;
    return f;
  };

  app.get('/api/health', (_, res) => res.json({ ok: true, store: store.name, s3: s3Enabled() }));

  app.get('/api/assets', async (req, res, next) => {
    try {
      const list = await store.list(cleanFilter(req.query));
      res.set('Cache-Control', 'public, max-age=5');
      // URL de miniatura/medio (prefirmada 3600 s o local); null si S3 falla o no hay medio.
      const thumbs = await Promise.all(list.map((a) => mediaUrl(a).catch(() => null)));
      res.json(list.map(({ veredicto, ...a }, i) => ({ ...a, thumbUrl: thumbs[i] ?? null, detectada: veredicto?.veredicto ?? null, confianza: veredicto?.confianza ?? null })));
    } catch (e) { next(e); }
  });

  app.get('/api/assets/:id', async (req, res, next) => {
    try {
      if (!ID_RE.test(req.params.id)) return bad(res, 'id inválido');
      const a = await store.get(req.params.id);
      if (!a) return res.status(404).json({ error: 'no encontrado' });
      const audio = await audioUrl(a);
      res.json({ ...a, mediaUrl: await mediaUrl(a), ...(audio ? { audioUrl: audio } : {}) });
    } catch (e) { next(e); }
  });

  app.get('/api/stats', async (_, res, next) => {
    try { res.set('Cache-Control', 'public, max-age=5'); res.json(computeStats(await store.list())); } catch (e) { next(e); }
  });

  // Dashboard de KPIs y operación: caché en memoria de 30 s; ?refresh=1 la fuerza.
  app.get('/api/dashboard', async (req, res, next) => {
    try {
      if (!(req.query.refresh === '1') && cache && now() - cache.at < 30_000) {
        res.set('Cache-Control', 'no-store'); return res.json({ ...cache.body, cached: true });
      }
      let src;
      try { src = (await getSources()) ?? {}; } catch { src = {}; }
      const live = src.live ?? {};
      const data = computeDashboard({ assets: await store.list(), metrics: src.metrics ?? {}, env, catalog: src.catalog, comfyHistory: live.comfyui?.historial ?? null });
      const { secrets = [], ...liveOut } = live;
      const body = sanitize({
        generatedAt: new Date(now()).toISOString(), cached: false, ...data,
        aws: {
          region: liveOut.region ?? env.AWS_REGION ?? 'us-east-1', account: liveOut.account ?? null, services: liveOut.services ?? [],
          comfyui: liveOut.comfyui ?? null, mediaToolkit: liveOut.mediaToolkit ?? null,
        },
        comfyui: { agent_url_host: src.metrics?.comfyui?.agent_url_host ?? null },
      }, [...secrets, env.COMFY_AGENT_TOKEN].filter(Boolean));
      cache = { at: now(), body };
      res.set('Cache-Control', 'no-store');
      res.json(body);
    } catch (e) { next(e); }
  });

  // Revisión humana: confirma o corrige la etiqueta esperada (Requirement 6.7)
  app.post('/api/assets/:id/validate', async (req, res, next) => {
    try {
      if (!ID_RE.test(req.params.id)) return bad(res, 'id inválido');
      const { label } = req.body ?? {};
      if (label !== undefined && !LABELS.has(label)) return bad(res, 'label inválido');
      const a = await store.get(req.params.id);
      if (!a) return res.status(404).json({ error: 'no encontrado' });
      await store.upsert({ ...a, etiqueta_esperada: label ?? a.etiqueta_esperada, etiqueta_validada: true });
      res.json({ ok: true });
    } catch (e) { next(e); }
  });

  // ---- Subidas y verificación ----
  const reloadAsset = async (id) => { const a = await loadAsset(id); if (a) await store.upsert(a); cache = null; };
  const reloadAll = async () => { for (const a of await loadAll()) await store.upsert(a); cache = null; };
  app.post('/api/uploads', createUploadHandler({ runRegister, onRegistered: reloadAsset }));

  const jobs = jobsOpt ?? createJobs({ env, onSuccess: reloadAll });
  app.post('/api/jobs/verify', async (req, res, next) => {
    try {
      const body = req.body ?? {};
      let only = null;
      if (body.only !== undefined && body.only !== null) {
        if (!Array.isArray(body.only) || body.only.length > MAX_ONLY || !body.only.every((i) => typeof i === 'string' && JOB_ID_RE.test(i))) return bad(res, 'only debe ser una lista de ids válidos');
        only = [...new Set(body.only)];
        if (!only.length) only = null;
      }
      if (only) for (const id of only) if (!(await store.get(id))) return bad(res, 'id desconocido: ' + id);
      try { res.status(202).json(jobs.start(only)); }
      catch (e) { if (e instanceof JobConflict) return res.status(409).json({ error: e.message }); throw e; }
    } catch (e) { next(e); }
  });
  // Generar un activo nuevo en ComfyUI (y verificarlo): mismo runner y mismo candado que la verificación.
  app.post('/api/jobs/generate', (req, res, next) => {
    try {
      const { params, error } = parseGenerateBody(req.body);
      if (error) return bad(res, error);
      try { res.status(202).json(jobs.startGenerate(params)); }
      catch (e) { if (e instanceof JobConflict) return res.status(409).json({ error: e.message }); throw e; }
    } catch (e) { next(e); }
  });
  app.get('/api/jobs/latest', (_, res) => {
    res.set('Cache-Control', 'no-store');
    const j = jobs.latest();
    return j ? res.json(j) : res.status(404).json({ error: 'sin verificaciones' });
  });
  app.get('/api/jobs/:id', (req, res) => {
    res.set('Cache-Control', 'no-store');
    const j = JOB_ID_RE.test(req.params.id) ? jobs.get(req.params.id) : null;
    return j ? res.json(j) : res.status(404).json({ error: 'no encontrado' });
  });

  // Informe de auditoría: S3 (URL prefirmada) o copia local.
  app.get('/api/report', async (_, res, next) => {
    try {
      res.set('Cache-Control', 'no-store');
      const url = await getReportUrl().catch(() => null);
      if (url) return res.redirect(302, url);
      if (fs.existsSync(localReport)) { res.type('html'); return res.sendFile(localReport); }
      res.status(404).json({ error: 'todavía no hay informe' });
    } catch (e) { next(e); }
  });

  if (distDir) {
    app.use(express.static(distDir, { maxAge: '1d', index: 'index.html' }));
    app.get(/^\/(?!api|media).*/, (_, res) => res.sendFile('index.html', { root: distDir }));
  }
  app.use((err, _req, res, _next) => { console.error(err.message); res.status(500).json({ error: 'error interno' }); });
  return app;
}
