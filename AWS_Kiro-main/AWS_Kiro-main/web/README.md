# Web del verificador de marca

React (Vite) + Node.js (Express) + Redis. Muestra imágenes y vídeos de prueba, veredicto del verificador
(Ayesa Digital correcto / Ayesa incorrecto), evidencias con cajas delimitadoras y Precision_Global.

## Por qué Redis
Es un catálogo pequeño de lectura intensiva con filtros por etiqueta. Redis lo sirve desde memoria con latencia
de microsegundos: un JSON por activo (`asset:{id}`), un sorted set de orden (`assets:all`) y sets de índice
(`idx:tipo:*`, `idx:esperada:*`, `idx:detectada:*`) que se combinan con `SINTER`. Sin `REDIS_URL` el servidor usa
un almacén en memoria con la misma interfaz, así que la demo funciona igualmente.

## Arranque
```bash
cd web/server && npm install && cd ../client && npm install && npm run build
docker compose -f ../docker-compose.yml up -d   # opcional
cd ../server && REDIS_URL=redis://localhost:6379 npm start   # http://localhost:3001
```
Desarrollo con recarga: `npm start` en `server/` y `npm run dev` en `client/` (puerto 5173).

## Datos
- Sin configuración: datos de demostración (`server/seed.js`). Los medios aparecen si copias los archivos a `web/media/`
  (`img-correcto-01.png`, `vid-correcto-01.mp4`, ...; los `.mp4` no se versionan).
- Datos reales: `MEDIA_BUCKET=<MediaToolkitIngestBucket>` y credenciales AWS estándar. Lee
  `brand/generated/manifest.json` y `brand/verdicts/<id>.json`, y sirve medios con URL prefirmada de 3600 s (`s3_key`).
- Sin secretos en el repositorio: solo variables de entorno (`REDIS_URL`, `MEDIA_BUCKET`, `PORT`, `MEDIA_DIR`).

## Permiso IAM del API_Visor
El rol del API_Visor solo necesita lectura: `s3:GetObject` sobre `arn:aws:s3:::<MEDIA_BUCKET>/brand/*`
(manifiesto, veredictos y medios prefirmados). No requiere `s3:PutObject`. La sentencia `ViewerReadOnlyBrandObjects`
está en `infra/iam-policy.json`. Sin credenciales en el repositorio.
## API
`GET /api/health` · `GET /api/assets?tipo=&esperada=&detectada=` · `GET /api/assets/:id` · `GET /api/stats` ·
`POST /api/assets/:id/validate` `{label?}`. Tests: `cd server && npm test`.
