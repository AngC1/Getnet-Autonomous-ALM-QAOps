// E/S del Dashboard: métricas en S3 y comprobaciones en vivo de AWS (cada una con timeout ≤5 s, nunca lanza;
// el historial de ComfyUI, 8 s).
import fs from 'node:fs';
import { latestRun, DEFAULT_MODEL_ID } from './dashboard.js';
import { summarizeHistory } from './comfy-history.js';
import { S3Client, GetObjectCommand, ListObjectsV2Command } from '@aws-sdk/client-s3';
import { STSClient, GetCallerIdentityCommand } from '@aws-sdk/client-sts';
import { BedrockClient, GetInferenceProfileCommand, GetFoundationModelCommand } from '@aws-sdk/client-bedrock';
import { CloudFormationClient, DescribeStacksCommand, ListStackResourcesCommand } from '@aws-sdk/client-cloudformation';
import { SecretsManagerClient, GetSecretValueCommand, ListSecretsCommand } from '@aws-sdk/client-secrets-manager';

const TIMEOUT = 5000;
export const HISTORY_PATH = '/history?max_items=1000';
export const HISTORY_TIMEOUT = 8000;
const REGION = () => process.env.AWS_REGION || 'us-east-1';
const IDE_REGION = () => process.env.IDE_REGION || 'us-east-2';
const SECRET_NAME = /(secret|password|passwd|api[_-]?key|token|credential)/i;
const safeName = (k) => !SECRET_NAME.test(k);
const opts = () => ({ abortSignal: AbortSignal.timeout(TIMEOUT) });
const msg = (e) => String(e?.name || e?.code || 'Error').slice(0, 60);

async function check(name, region, fn) {
  const t0 = Date.now();
  try { return { name, region, status: 'ok', ms: Date.now() - t0, ...(await fn()) }; }
  catch (e) { return { name, region, status: 'error', ms: Date.now() - t0, detail: msg(e) }; }
}

// ---- Métricas en S3 (todo tolerante a ausencias) ----
export async function loadMetrics(bucket) {
  const empty = { perAsset: {}, comfyui: null, run: null, runs: [], models: {} };
  if (!bucket) return empty;
  const s3 = new S3Client({ region: REGION() });
  const get = async (Key) => {
    try {
      const { Body } = await s3.send(new GetObjectCommand({ Bucket: bucket, Key }), opts());
      return JSON.parse(await Body.transformToString());
    } catch { return null; }
  };
  let keys = [];
  try {
    const r = await s3.send(new ListObjectsV2Command({ Bucket: bucket, Prefix: 'brand/metrics/', MaxKeys: 300 }), opts());
    keys = (r.Contents ?? []).map((c) => c.Key).filter((k) => k.endsWith('.json'));
  } catch { return empty; }
  const special = new Set(['comfyui', 'run', 'runs', 'models']);
  const base = (k) => k.slice('brand/metrics/'.length, -5);
  const data = await Promise.all(keys.map(async (k) => [base(k), await get(k)]));
  const out = { ...empty };
  for (const [id, v] of data) {
    if (v == null) continue;
    if (id === 'comfyui') out.comfyui = v;
    else if (id === 'run') out.run = v;
    else if (id === 'runs') out.runs = Array.isArray(v) ? v : [];
    else if (id === 'models') out.models = v;
    else if (!special.has(id) && typeof v === 'object') out.perAsset[v.id ?? id] = v;
  }
  return out;
}

export function loadCatalog() {
  try { return JSON.parse(fs.readFileSync(new URL('../../comfyui/catalog.json', import.meta.url), 'utf8')); } catch { return null; }
}

// Resumen del historial de ComfyUI (get = GET autenticado contra AgentUrl). Nunca lanza: si falla,
// historial es null y el Dashboard sigue con brand/metrics/comfyui.json.
export async function loadComfyHistory(get) {
  try { return { historial: summarizeHistory(await get(HISTORY_PATH, HISTORY_TIMEOUT)) }; }
  catch (e) { return { historial: null, historialError: msg(e) }; }
}

// ---- Comprobaciones en vivo ----
async function stackInfo(cf, StackName) {
  const { Stacks } = await cf.send(new DescribeStacksCommand({ StackName }), opts());
  const s = Stacks?.[0];
  return { status: s?.StackStatus ?? 'UNKNOWN', outputs: s?.Outputs ?? [], s };
}

export async function liveChecks({ bucket, modelId }) {
  const region = REGION();
  const ide = IDE_REGION();
  const cfIde = new CloudFormationClient({ region: ide });
  const secretsToHide = [];
  const result = { region, account: null, services: [], comfyui: null, mediaToolkit: null, secrets: secretsToHide };

  const sts = check('AWS STS', region, async () => {
    const r = await new STSClient({ region }).send(new GetCallerIdentityCommand({}), opts());
    result.account = r.Account ?? null;
    return { detail: 'GetCallerIdentity' };
  });

  const bedrock = check('Amazon Bedrock', 'us-east-1', async () => {
    if (!modelId) throw Object.assign(new Error(), { name: 'SinModelo' });
    const c = new BedrockClient({ region: 'us-east-1' });
    try {
      const r = await c.send(new GetInferenceProfileCommand({ inferenceProfileIdentifier: modelId }), opts());
      return { detail: `perfil ${r.status ?? 'ACTIVE'}: ${modelId}` };
    } catch (e) {
      if (e?.name === 'AbortError' || e?.name === 'TimeoutError') throw e;
      await c.send(new GetFoundationModelCommand({ modelIdentifier: modelId }), opts());
      return { detail: `modelo disponible: ${modelId}` };
    }
  });

  const s3 = check('Amazon S3', 'us-east-1', async () => {
    if (!bucket) throw Object.assign(new Error(), { name: 'SinBucket' });
    const c = new S3Client({ region });
    let n = 0; let token; let pages = 0;
    do {
      const r = await c.send(new ListObjectsV2Command({ Bucket: bucket, Prefix: 'brand/', ContinuationToken: token }), opts());
      n += r.KeyCount ?? 0; token = r.IsTruncated ? r.NextContinuationToken : undefined; pages += 1;
    } while (token && pages < 5);
    return { detail: `${bucket}: ${n}${token ? '+' : ''} objetos bajo brand/`, bucket, objects: n, truncated: !!token };
  });

  const secretsSvc = check('AWS Secrets Manager', ide, async () => {
    await new SecretsManagerClient({ region: ide }).send(new ListSecretsCommand({ MaxResults: 1 }), opts());
    return { detail: 'ListSecrets' };
  });

  const comfyStack = (async () => {
    try { return await stackInfo(cfIde, 'remangu-comfyui'); } catch (e) { return { error: e }; }
  })();

  const cfn = check('AWS CloudFormation', ide, async () => {
    const r = await comfyStack;
    if (r.error) throw r.error;
    return { detail: `remangu-comfyui: ${r.status}`, stacks: ['remangu-comfyui'], outputs: r.outputs.map((o) => o.OutputKey).filter(safeName) };
  });

  const comfy = (async () => {
    const t0 = Date.now();
    const base = { name: 'ComfyUI', region: ide };
    let history = null;
    try {
      const r = await comfyStack;
      if (r.error) throw r.error;
      const out = Object.fromEntries(r.outputs.map((o) => [o.OutputKey, o.OutputValue]));
      const agentUrl = out.AgentUrl;
      if (!agentUrl) throw Object.assign(new Error(), { name: 'SinAgentUrl' });
      let token = process.env.COMFY_AGENT_TOKEN;
      if (!token && out.AgentTokenSecret) {
        const sv = await new SecretsManagerClient({ region: ide }).send(new GetSecretValueCommand({ SecretId: out.AgentTokenSecret }), opts());
        token = sv.SecretString ?? '';
        try { const j = JSON.parse(token); token = typeof j === 'string' ? j : (j.token ?? j.AgentToken ?? Object.values(j).find((v) => typeof v === 'string') ?? ''); } catch { /* texto plano */ }
      }
      if (token) secretsToHide.push(token.trim());
      const host = new URL(agentUrl).host;
      const headers = token ? { Authorization: `Bearer ${token.trim()}` } : {};
      const get = async (p, ms = TIMEOUT) => {
        const resp = await fetch(agentUrl.replace(/\/$/, '') + p, { headers, signal: AbortSignal.timeout(ms) });
        if (!resp.ok) throw Object.assign(new Error(), { name: `HTTP${resp.status}` });
        return resp.json();
      };
      history = loadComfyHistory(get); // en paralelo con system_stats y queue
      const [stats, queue] = await Promise.all([get('/system_stats'), get('/queue')]);
      const dev = (stats.devices ?? []).map((d) => ({ nombre: d.name, tipo: d.type, vram_total: d.vram_total, vram_libre: d.vram_free }));
      const ms = Date.now() - t0;
      return { ...base, status: 'ok', ms, host, version: stats.system?.comfyui_version ?? null, gpus: dev,
        cola: { en_curso: (queue.queue_running ?? []).length, pendiente: (queue.queue_pending ?? []).length }, ...(await history) };
    } catch (e) { return { ...base, status: 'error', ms: Date.now() - t0, detail: msg(e), ...(history ? await history : {}) }; }
  })();

  const toolkit = (async () => {
    const t0 = Date.now();
    const base = { name: 'Unified Media Toolkit', region: 'us-east-1', stack: 'unified-media-toolkit' };
    try {
      const cf = new CloudFormationClient({ region: 'us-east-1' });
      const { status, outputs } = await stackInfo(cf, 'unified-media-toolkit');
      let resources = []; let token;
      for (let i = 0; i < 3; i++) {
        const r = await cf.send(new ListStackResourcesCommand({ StackName: 'unified-media-toolkit', NextToken: token }), opts());
        resources = resources.concat((r.StackResourceSummaries ?? []).map((x) => ({ id: x.LogicalResourceId, tipo: x.ResourceType })));
        token = r.NextToken; if (!token) break;
      }
      const porTipo = {};
      for (const r of resources) porTipo[r.tipo] = (porTipo[r.tipo] ?? 0) + 1;
      return { ...base, status: /FAILED|ROLLBACK/.test(status) ? 'error' : 'ok', ms: Date.now() - t0, stackStatus: status,
        recursos: resources.length, porTipo, nombres: resources.map((r) => r.id).filter(safeName).slice(0, 40),
        outputs: outputs.map((o) => o.OutputKey).filter(safeName) };
    } catch (e) { return { ...base, status: 'error', ms: Date.now() - t0, detail: msg(e) }; }
  })();

  const [stsR, bR, s3R, smR, cfR, comfyR, tkR] = await Promise.all([sts, bedrock, s3, secretsSvc, cfn, comfy, toolkit]);
  result.services = [bR, s3R, smR, cfR, stsR];
  result.comfyui = comfyR;
  result.mediaToolkit = tkR;
  return result;
}

export async function defaultSources({ bucket, env = process.env }) {
  const metrics = await loadMetrics(bucket).catch(() => ({ perAsset: {}, comfyui: null, run: null, runs: [], models: {} }));
  const modelId = latestRun(metrics.runs, metrics.run)?.model_id || env.BRAND_MODEL_ID || DEFAULT_MODEL_ID;
  const live = await liveChecks({ bucket, modelId }).catch(() => ({ region: REGION(), account: null, services: [], comfyui: null, mediaToolkit: null, secrets: [] }));
  return { metrics, live, catalog: loadCatalog() };
}
