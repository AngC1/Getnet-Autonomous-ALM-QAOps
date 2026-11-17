import fs from 'node:fs';
import { createStore } from './store.js';
import { createApp } from './app.js';
import { SEED } from './seed.js';
import { loadFromS3, s3Enabled } from './media.js';

const store = await createStore(process.env.REDIS_URL);
let assets = [];
if (s3Enabled()) {
  try { assets = await loadFromS3(); console.log(`Cargados ${assets.length} activos desde S3`); }
  catch (e) { console.warn(`No se pudo leer S3 (${e.name}); se usan datos de demostración.`); }
}
if (!assets.length) assets = SEED;
await store.clear();
for (const a of assets) await store.upsert(a);

const distDir = new URL('../client/dist', import.meta.url).pathname;
const app = createApp(store, { distDir: fs.existsSync(distDir) ? distDir : undefined });
const port = Number(process.env.PORT || 3001);
app.listen(port, () => console.log(`API en http://localhost:${port} (store: ${store.name}, activos: ${assets.length})`));
