// Dos implementaciones con la misma interfaz: Redis (producción/demo) y memoria (sin Redis).
// Modelo Redis: asset:{id} = JSON; zset assets:all (score = orden); sets idx:tipo:*, idx:esperada:*, idx:detectada:*.
import Redis from 'ioredis';

const idxKeys = (a) => [`idx:tipo:${a.tipo}`, `idx:esperada:${a.etiqueta_esperada}`, `idx:detectada:${a.veredicto?.veredicto ?? 'NONE'}`];

export class RedisStore {
  constructor(url, client) { this.name = 'redis'; this.r = client ?? new Redis(url, { maxRetriesPerRequest: 2, lazyConnect: true }); }
  async connect() { if (this.r.status === 'wait') await this.r.connect(); await this.r.ping(); }
  async clear() { await this.r.flushdb(); }
  async upsert(a) {
    const old = await this.get(a.id);
    const p = this.r.pipeline();
    if (old) idxKeys(old).forEach((k) => p.srem(k, a.id));
    p.set(`asset:${a.id}`, JSON.stringify(a)).zadd('assets:all', old ? (await this.r.zscore('assets:all', a.id)) : await this.r.incr('assets:seq'), a.id);
    idxKeys(a).forEach((k) => p.sadd(k, a.id));
    await p.exec();
  }
  async get(id) { const s = await this.r.get(`asset:${id}`); return s ? JSON.parse(s) : null; }
  async list({ tipo, esperada, detectada } = {}) {
    const keys = [];
    if (tipo) keys.push(`idx:tipo:${tipo}`);
    if (esperada) keys.push(`idx:esperada:${esperada}`);
    if (detectada) keys.push(`idx:detectada:${detectada}`);
    let ids = await this.r.zrange('assets:all', 0, -1);
    if (keys.length) { const set = new Set(await this.r.sinter(...keys)); ids = ids.filter((i) => set.has(i)); }
    if (!ids.length) return [];
    return (await this.r.mget(ids.map((i) => `asset:${i}`))).filter(Boolean).map((s) => JSON.parse(s));
  }
}

export class MemoryStore {
  constructor() { this.name = 'memory'; this.m = new Map(); }
  async connect() {}
  async clear() { this.m.clear(); }
  async upsert(a) { this.m.set(a.id, a); }
  async get(id) { return this.m.get(id) ?? null; }
  async list({ tipo, esperada, detectada } = {}) {
    return [...this.m.values()].filter((a) => (!tipo || a.tipo === tipo) && (!esperada || a.etiqueta_esperada === esperada)
      && (!detectada || a.veredicto?.veredicto === detectada));
  }
}

export async function createStore(url) {
  if (url) {
    const s = new RedisStore(url);
    try { await s.connect(); return s; } catch (e) { console.warn(`Redis no disponible (${e.message}); usando memoria.`); s.r.disconnect(); }
  }
  return new MemoryStore();
}
