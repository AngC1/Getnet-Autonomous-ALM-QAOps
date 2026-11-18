# Implementation Plan: Verificador de marca (Ayesa Digital vs Ayesa)

## Overview

Implementación en Python 3.11+ del paquete `brand_verifier/` según `design.md`. Se construye primero el núcleo puro (esquemas, agregación, redacción, métricas), luego los adaptadores de E/S (Bedrock, S3, ComfyUI, Secrets Manager), después el orquestador/CLI y, por último, la documentación (`TEAM.md`, `Agent.md`). Las pruebas basadas en propiedades usan `hypothesis` con `pytest` (mínimo 100 ejemplos por propiedad) y cada test lleva el comentario `# Feature: atm-card-incident-video-simulation, Property N: <texto>`. Ningún archivo, test ni documento puede contener secretos o datos sensibles: solo se referencian nombres de Outputs, secretos y variables de entorno.

## Tasks

- [x] 1. Estructura del proyecto y modelos de datos
  - [x] 1.1 Crear la estructura del proyecto y el entorno de pruebas
    - Crear el paquete `brand_verifier/` (`__init__.py`, `__main__.py`), `tests/`, `scripts/` y `assets/brand/` (con `.gitkeep`)
    - Crear `requirements.txt` con versiones fijadas (`boto3`, `Pillow`, `opencv-python-headless`, `pytest`, `hypothesis`) y `pytest.ini`
    - Verificar que `.gitignore` excluye `.env`, `__pycache__` y archivos locales de salida
    - _Requirements: 1.1, 10.5_

  - [x] 1.2 Implementar modelos y validación del Veredicto (`models.py`)
    - Dataclasses `Verdict`, `Evidence`, `FrameVerdict`, `VerifyError`
    - `validate_verdict(obj) -> list[str]` pura (valores, confianza, recomendación 1–500, cajas normalizadas, reglas por veredicto)
    - `verdict_to_json` / `verdict_from_json` y `is_valid_asset_id` (`^[A-Za-z0-9_-]{1,64}$`), `verdict_s3_key(id)`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [x] 1.3 Escribir test de propiedad para validación del esquema del Veredicto
    - **Property 5: Validación del esquema del Veredicto**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.8**
    - Archivo `tests/test_prop_verdict_schema.py`

  - [x] 1.4 Escribir test de propiedad de ida y vuelta del Veredicto
    - **Property 6: Ida y vuelta del Veredicto**
    - **Validates: Requirements 4.7**
    - Archivo `tests/test_prop_verdict_roundtrip.py`

  - [x] 1.5 Escribir test de propiedad para la validez del identificador de activo
    - **Property 7: Validez del identificador de activo**
    - **Validates: Requirements 4.6**
    - Archivo `tests/test_prop_asset_id.py`

- [x] 2. Gestión de secretos y logs seguros
  - [x] 2.1 Implementar `Gestor_Secretos` y filtro de redacción (`secrets.py`)
    - `get_agent_url()` (Output `AgentUrl` con `--region us-east-2` → `COMFY_URL`), `get_agent_token()` (Secrets Manager `AgentTokenSecret` en `us-east-2` → `COMFY_AGENT_TOKEN`), `get_optional(name)` sin escribir a disco
    - Timeout total de 30 s y `SecretNotFound(nombre)` con solo el nombre del secreto
    - `logging.Filter` global que sustituye valores de secretos cargados por `[REDACTED]`
    - _Requirements: 5.1, 5.6, 10.1, 10.2, 10.3, 10.4, 10.7_

  - [x] 2.2 Escribir test de propiedad para redacción en logs
    - **Property 22: Redacción en logs**
    - **Validates: Requirements 10.7**
    - Archivo `tests/test_prop_log_redaction.py`

  - [x] 2.3 Escribir tests unitarios del Gestor_Secretos
    - Orden de fuentes con clientes falsos, mensaje de error solo con el nombre, timeout de 30 s
    - Usar valores ficticios generados en el test, nunca valores reales
    - _Requirements: 5.6, 10.1, 10.2, 10.4_

- [x] 3. Adaptador S3 y referencias de marca
  - [x] 3.1 Implementar el adaptador S3 (`s3io.py`)
    - `put/get/exists` con reintentos de 1, 2 y 4 s; al fallar el tercero marcar la operación fallida, notificar operación y activo y conservar datos locales pendientes
    - Región `us-east-1`; solo prefijos `brand/` e `incidents/` del `Bucket_Medios`
    - _Requirements: 7.1, 7.4, 7.6_

  - [x] 3.2 Implementar el comprobador de referencias (`references.py`)
    - `check_local_refs(dir)`: existencia, tamaño ≤ 1 MB y WebP legible con Pillow; error con ruta y motivo
    - `sync_refs_to_s3(s3, bucket)`: sube a `brand/reference/` solo los ausentes
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 7.1_

  - [x] 3.3 Escribir tests unitarios de S3 y referencias
    - Reintentos con espera creciente (reloj simulado), referencia ausente, no WebP, > 1 MB, subida si falta
    - _Requirements: 1.3, 1.4, 1.5, 7.6_

- [x] 4. Núcleo y adaptador del Verificador_Marca
  - [x] 4.1 Implementar el núcleo puro del verificador (`core.py`)
    - `aggregate_frames(frame_verdicts)` con la tabla de prioridad
    - `sample_timestamps(duration_s)` a 1 fps (máx. 60 s)
    - `select_video_evidence(frames)` (todos los `INCORRECTO`/`AMBIGUO` y al menos un `CORRECTO`)
    - `normalize_model_output(raw)` (ambos logos → `INCORRECTO`; `SIN_LOGO` → evidencias vacías)
    - `is_supported_image(fmt, size_bytes)` (PNG/JPEG/WebP, ≤ 5 MB)
    - _Requirements: 2.6, 2.7, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.9, 4.4_

  - [x] 4.2 Escribir test de propiedad para agregación por prioridad
    - **Property 1: Agregación de vídeo por reglas de prioridad**
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.5**
    - Archivo `tests/test_prop_aggregate_priority.py`

  - [x] 4.3 Escribir test de propiedad para agregación independiente del orden
    - **Property 2: Agregación independiente del orden**
    - **Validates: Requirements 3.9**
    - Archivo `tests/test_prop_aggregate_order.py`

  - [x] 4.4 Escribir test de propiedad para selección de evidencias de vídeo
    - **Property 3: Selección de evidencias de vídeo**
    - **Validates: Requirements 3.6**
    - Archivo `tests/test_prop_video_evidence.py`

  - [x] 4.5 Escribir test de propiedad para muestreo a 1 fps
    - **Property 4: Muestreo a 1 fotograma por segundo**
    - **Validates: Requirements 3.1**
    - Archivo `tests/test_prop_sampling.py`

  - [x] 4.6 Escribir test de propiedad para ambos logos implican INCORRECTO
    - **Property 8: Ambos logos implican INCORRECTO**
    - **Validates: Requirements 2.6**
    - Archivo `tests/test_prop_both_logos.py`

  - [x] 4.7 Implementar el adaptador Bedrock del verificador (`verifier.py`)
    - `verify_image`: rechazo previo sin invocar Bedrock, petición Converse en `us-east-1` con muestra + ambos Activos_Referencia, modelo desde `BRAND_MODEL_ID`, timeout 30 s, un reintento y `VerifyError` si vuelve a fallar
    - `verify_video`: extracción a 1 fps con OpenCV/ffmpeg, verificación por fotograma, agregación y evidencias; `VerifyError` si el vídeo no se puede leer
    - Guardado del Veredicto válido en `brand/verdicts/<id_activo>.json`; rechazo sin guardar si el esquema no se cumple
    - Opción `--pegasus` opcional que añade evidencia complementaria desde el `Bucket_Medios` sin alterar el veredicto
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.7, 2.8, 3.1, 3.7, 3.8, 4.6, 4.8, 7.4_

  - [x] 4.8 Escribir test de propiedad para rechazo de imágenes no soportadas
    - **Property 9: Rechazo de imágenes no soportadas**
    - **Validates: Requirements 2.7**
    - Archivo `tests/test_prop_image_rejection.py` (verificar con cliente Bedrock falso que no se invoca)

  - [x] 4.9 Escribir tests unitarios del verificador con Bedrock falso
    - La petición contiene muestra y ambos logos, un fallo → reintento, dos fallos → error, vídeo ilegible → error
    - _Requirements: 2.1, 2.8, 3.7_

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Manifiesto y Generador_ComfyUI
  - [x] 6.1 Implementar el Manifiesto (`manifest.py`)
    - `load/save` con escritura atómica local y subida a `brand/generated/manifest.json`; si falla la subida se conserva la última escritura exitosa
    - `register_asset(...)` con `etiqueta_validada=false` y sin secretos en `ajustes`
    - `validate_asset(id, confirmed, corrected_label)` y subcomando `brand_verifier validate <id> [--label X]`
    - _Requirements: 6.6, 6.7, 6.8, 7.2, 7.7_

  - [x] 6.2 Escribir test de propiedad para validación manual de etiquetas
    - **Property 12: Validación manual de etiquetas**
    - **Validates: Requirements 6.7**
    - Archivo `tests/test_prop_manifest_validate.py`

  - [x] 6.3 Implementar el Generador_ComfyUI (`generator.py`)
    - Plan por defecto de ≥ 12 activos (3+2 correcto, 3+2 incorrecto, 1+1 sin logo), vídeo ATM de calle con logotipo en pantalla (prompt sin personas, tarjetas ni bancos reales) y vídeo `INCORRECTO` mixto concatenado con ffmpeg
    - `select_input_logo(spec)`: solo el Activo_Referencia de la marca esperada, ninguno para `SIN_LOGO`
    - Uso de `comfyui/client.py` contra `AgentUrl` con token del Gestor_Secretos, sondeo previo de 10 s, `timeout_s=900`, cancelación con `/interrupt`, `GENERACION_FALLIDA` sin reintentos
    - Un solo trabajo a la vez y estado en consola (en cola, en curso, completado, fallido) en ≤ 1 s; ajustes mínimos de `catalog.json` para vídeos de 3 a 10 s
    - Subida a `brand/generated/<id_activo>/` y registro en el Manifiesto
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.7, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.9, 7.2_

  - [x] 6.4 Escribir test de propiedad para entrada de generación según etiqueta
    - **Property 10: Entrada de generación según etiqueta**
    - **Validates: Requirements 6.3**
    - Archivo `tests/test_prop_generation_input.py`

  - [x] 6.5 Escribir test de propiedad para registro nuevo en el Manifiesto
    - **Property 11: Registro nuevo en el Manifiesto**
    - **Validates: Requirements 6.6**
    - Archivo `tests/test_prop_manifest_record.py`

  - [x] 6.6 Escribir tests unitarios del generador con `run_workflow` falso
    - Timeout → `GENERACION_FALLIDA` y continúa, ejecución secuencial (máx. 1 trabajo), sin Nova Reel
    - _Requirements: 5.4, 5.5, 6.1_

- [x] 7. Flujo de incidencia ATM (secundario)
  - [x] 7.1 Implementar el flujo de incidencia (`incident.py`)
    - `validate_incident`, `redact_pan` (13–19 dígitos, deja los últimos 4), `scene_prompt` sin nombres, tarjetas ni bancos
    - Persistencia en `incidents/<id>/incident.json` (≤ 5 s), triaje con Bedrock de texto en `us-east-1` a `triage.json`, un reintento y estado `TRIAJE_FALLIDO`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x] 7.2 Escribir test de propiedad para validación de Incidencia
    - **Property 17: Validación de Incidencia**
    - **Validates: Requirements 8.1, 8.2**
    - Archivo `tests/test_prop_incident_validation.py`

  - [x] 7.3 Escribir test de propiedad para redacción de números de tarjeta
    - **Property 18: Redacción de números de tarjeta**
    - **Validates: Requirements 8.3**
    - Archivo `tests/test_prop_redact_pan.py`

  - [x] 7.4 Escribir test de propiedad para prompt de escena sin datos sensibles
    - **Property 19: Prompt de escena sin datos sensibles**
    - **Validates: Requirements 8.6**
    - Archivo `tests/test_prop_scene_prompt.py`

  - [x] 7.5 Escribir test de propiedad de ida y vuelta de la Incidencia
    - **Property 20: Ida y vuelta de la Incidencia**
    - **Validates: Requirements 8.7**
    - Archivo `tests/test_prop_incident_roundtrip.py`

- [x] 8. Informe, CLI y orquestador
  - [x] 8.1 Implementar el generador de informe (`report.py`)
    - `compute_precision(rows)` solo sobre `etiqueta_validada=true`, tiempo medio de verificación
    - `render_report(rows, stats)` en HTML: tabla por activo, evidencia con caja dibujada (Pillow) o URL prefirmada de 3600 s, "OBJETIVO ALCANZADO"/"OBJETIVO NO ALCANZADO" (umbral 90 %), sección separada de falsos negativos, soporte de informe parcial
    - Guardado en `brand/reports/` sin Datos_Sensibles
    - _Requirements: 6.8, 7.3, 9.2, 9.3, 9.4, 9.5, 9.6, 9.8, 10.5_

  - [x] 8.2 Escribir test de propiedad para Precision_Global
    - **Property 13: Precision_Global solo sobre activos validados**
    - **Validates: Requirements 6.8, 9.4**
    - Archivo `tests/test_prop_precision.py`

  - [x] 8.3 Escribir test de propiedad para el indicador de objetivo
    - **Property 14: Indicador de objetivo**
    - **Validates: Requirements 9.5**
    - Archivo `tests/test_prop_target_indicator.py`

  - [x] 8.4 Escribir test de propiedad para falsos negativos separados
    - **Property 15: Falsos negativos separados**
    - **Validates: Requirements 9.6**
    - Archivo `tests/test_prop_false_negatives.py`

  - [x] 8.5 Escribir test de propiedad para el contenido del informe
    - **Property 16: Contenido del informe**
    - **Validates: Requirements 9.2, 9.3**
    - Archivo `tests/test_prop_report_content.py`

  - [x] 8.6 Implementar la CLI y el orquestador (`cli.py`, `__main__.py`)
    - `python -m brand_verifier run [--manifest ...] [--skip-generation]` con etapas `referencias` → `generacion` → `verificacion` → `informe` y estado en consola en ≤ 1 s
    - Manifiesto o ruta ilegible → código ≠ 0 sin etapas posteriores; etapa fallida → omitir dependientes, informe parcial y código ≠ 0
    - Verificación con pool de 4 hilos; subcomandos `validate` e `incident` (opcional)
    - _Requirements: 1.3, 9.1, 9.7, 9.8, 9.9, 9.10_

  - [x] 8.7 Escribir tests unitarios de la CLI
    - Manifiesto ausente → código ≠ 0, etapa fallida → informe parcial, orden de etapas
    - _Requirements: 9.7, 9.8, 9.9_

- [x] 9. Seguridad y permisos
  - [x] 9.1 Implementar el escáner de secretos y el hook de pre-commit (`scripts/check_secrets.py`)
    - Escanea archivos staged con patrones de claves, contraseñas y tokens; muestra ruta y línea sin el valor y devuelve código ≠ 0
    - Instalar `.git/hooks/pre-commit` o `.pre-commit-config.yaml` que lo invoque
    - _Requirements: 10.5, 10.6_

  - [x] 9.2 Escribir test de propiedad para detección de secretos sin revelarlos
    - **Property 21: Detección de secretos sin revelarlos**
    - **Validates: Requirements 10.6**
    - Archivo `tests/test_prop_secret_scanner.py`

  - [x] 9.3 Crear la política IAM de mínimo privilegio (`infra/iam-policy.json`)
    - `bedrock:InvokeModel`, `s3` en `brand/*` e `incidents/*` del `Bucket_Medios`, `secretsmanager:GetSecretValue` sobre `AgentTokenSecret` y `cloudformation:DescribeStacks` en `us-east-2`
    - _Requirements: 10.8_

- [x] 10. Web de visualización de resultados (Web_Visor y API_Visor, Requirement 13)
  - [x] 10.1 Implementar la API REST del Visor (`web/server/app.js`, `web/server/index.js`)
    - Endpoints `GET /api/health`, `GET /api/assets`, `GET /api/assets/:id`, `GET /api/stats` y `POST /api/assets/:id/validate`
    - Filtros `tipo`, `esperada` y `detectada` con descarte de valores inválidos, validación de id y etiqueta (400/404), límite de cuerpo de 10 KB y configuración solo por `REDIS_URL`, `MEDIA_BUCKET`, `PORT` y `MEDIA_DIR`
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.17, 13.18, 13.19, 13.20, 13.32, 13.33_

  - [x] 10.2 Implementar los almacenes `MemoryStore` y `RedisStore` (`web/server/store.js`)
    - Misma interfaz (`upsert`, `get`, `list`, `clear`), índices `idx:tipo`, `idx:esperada` e `idx:detectada` con intersección (`SINTER`), orden de `assets:all` y reindexado al actualizar
    - Selección de Redis con `REDIS_URL` y fallback a memoria con aviso si la conexión falla
    - _Requirements: 13.23, 13.24, 13.25, 13.26, 13.38_

  - [x] 10.3 Implementar el cálculo de estadísticas (`web/server/stats.js`)
    - `computeStats`: Precision_Global sobre validados, aciertos, tiempo medio, recuentos, falsos negativos y objetivo (umbral 90 %)
    - _Requirements: 13.8, 13.9, 13.10, 13.37_

  - [x] 10.4 Implementar la resolución de medios y los datos semilla (`web/server/media.js`, `web/server/seed.js`)
    - Carga desde S3 (`brand/generated/manifest.json` y `brand/verdicts/<id>.json`) con URL prefirmada de 3600 s, ruta `/media/<archivo>` desde `MEDIA_DIR` y `mediaUrl` nulo si no hay medio
    - Datos semilla cuando no hay `MEDIA_BUCKET` o S3 falla o devuelve cero activos
    - _Requirements: 13.27, 13.28, 13.29, 13.30, 13.31_

  - [x] 10.5 Implementar el cliente React (`web/client/src/App.jsx`, `api.js`, `styles.css`)
    - Galería por secciones, filtros etiquetados, resumen de métricas, diálogo de detalle (`role="dialog"`, `aria-modal`, Escape), cajas de Evidencias, salto a marca de tiempo, validación de etiquetas, errores con `role="alert"` y aviso "Sin medio disponible."
    - _Requirements: 13.5, 13.6, 13.7, 13.11, 13.12, 13.13, 13.14, 13.15, 13.16, 13.21, 13.22, 13.31, 13.34, 13.35, 13.36_

  - [x] 10.6 Documentar y empaquetar la web (`web/README.md`, `web/docker-compose.yml`)
    - README con arranque, variables `REDIS_URL`, `MEDIA_BUCKET`, `PORT`, `MEDIA_DIR` y `docker-compose` con Redis local, sin secretos ni URL con credenciales
    - _Requirements: 13.26, 13.32_

  - [x] 10.7 Escribir los tests existentes con `node:test` (`web/server/app.test.js`)
    - Estadísticas (precisión solo sobre validados y falsos negativos) y API (listado con filtros, detalle, validación e id inválido) con `createApp(new MemoryStore())` en puerto efímero
    - _Requirements: 13.3, 13.8, 13.9, 13.17, 13.19_

  - [x] 10.8 Extraer `bboxToStyle` y `visibleEvidences` a `web/client/src/bbox.js`
    - Módulo puro sin dependencias de React: `bboxToStyle([x_min, y_min, x_max, y_max])` devuelve `left`, `top`, `width` y `height` en porcentaje; `visibleEvidences(evidencias, tipo, t)` devuelve todas para imagen y las de `|timestamp_s - t| <= 0.5` para vídeo
    - Sustituir en `App.jsx` el cálculo en línea (componente `Media`) por llamadas a `bbox.js`, sin cambiar el comportamiento visible
    - _Requirements: 13.13, 13.14_

  - [x] 10.9 Escribir test de propiedad para Precision_Global solo sobre validados, en rango
    - **Property 23: Precision_Global solo sobre validados, en rango**
    - **Validates: Requirements 13.8, 13.37**
    - Archivo `web/server/prop_stats_precision.test.js` con `fast-check` (añadido como devDependency con versión fija) y `numRuns: 100`

  - [x] 10.10 Escribir test de propiedad para la coherencia del resto de estadísticas
    - **Property 24: Coherencia del resto de estadísticas**
    - **Validates: Requirements 13.9, 13.10, 13.37**
    - Archivo `web/server/prop_stats_coherence.test.js`

  - [x] 10.11 Escribir test de propiedad para consistencia de filtros entre RedisStore y MemoryStore
    - **Property 25: Consistencia de filtros entre RedisStore y MemoryStore**
    - **Validates: Requirements 13.3, 13.24, 13.25, 13.26**
    - Archivo `web/server/prop_store_filters.test.js`; `MemoryStore` como modelo y `RedisStore` sobre Redis real (menos ejecuciones, `clear()` entre casos) o `ioredis-mock`; `skip` con aviso si no hay Redis

  - [x] 10.12 Escribir test de propiedad para ida y vuelta de upsert y get en los almacenes
    - **Property 29: Ida y vuelta de upsert y get en los almacenes**
    - **Validates: Requirements 13.38**
    - Archivo `web/server/prop_store_roundtrip.test.js`

  - [x] 10.13 Escribir test de propiedad para filtros inválidos ignorados
    - **Property 26: Filtros inválidos se ignoran**
    - **Validates: Requirements 13.4**
    - Archivo `web/server/prop_api_filters.test.js` con `createApp(new MemoryStore())` y `listen(0)`

  - [x] 10.14 Escribir test de propiedad para validación de identificador y etiqueta
    - **Property 27: Validación de identificador y etiqueta**
    - **Validates: Requirements 13.19, 13.20**
    - Archivo `web/server/prop_api_validation.test.js`

  - [x] 10.15 Escribir test de propiedad para la validación manual de un activo en la API
    - **Property 28: Validación manual de un activo en la API**
    - **Validates: Requirements 13.17, 13.18**
    - Archivo `web/server/prop_api_validate.test.js`

  - [x] 10.16 Escribir test de propiedad para el mapeo de caja normalizada a porcentajes CSS
    - **Property 30: Mapeo de caja normalizada a porcentajes CSS**
    - **Validates: Requirements 13.13**
    - Archivo `web/client/src/bbox.prop.test.js` (`fast-check` como devDependency del cliente), sin renderizar React

  - [x] 10.17 Escribir test de propiedad para evidencias visibles de un vídeo según el instante
    - **Property 31: Evidencias visibles de un vídeo según el instante**
    - **Validates: Requirements 13.14**
    - Mismo archivo `web/client/src/bbox.prop.test.js`

  - [x] 10.18 Escribir test de integración de `RedisStore` contra Redis real o `ioredis-mock`
    - Archivo `web/server/store.redis.test.js`: claves `asset:{id}`, `assets:all`, `idx:*` (con `NONE` sin Veredicto), intersección de filtros, reindexado al actualizar y fallback a memoria si la conexión falla
    - Usar el Redis de `web/docker-compose.yml` (vía `REDIS_URL` de entorno) o `ioredis-mock` con versión fija; `skip` con aviso si no hay Redis
    - _Requirements: 13.23, 13.24, 13.25, 13.26_

  - [x] 10.19 Documentar el permiso de lectura S3 del API_Visor en la política IAM
    - Añadir a `infra/iam-policy.json` (tarea 9.3) la sentencia `s3:GetObject` sobre `brand/*` del `Bucket_Medios` para el API_Visor, solo lectura y sin `s3:PutObject`
    - Añadir una nota en `web/README.md` con el permiso necesario, sin ARN de cuentas reales ni credenciales
    - _Requirements: 13.28, 13.29, 13.32, 10.8_

- [x] 11. Documentación: TEAM.md y Agent.md
  - [x] 11.1 Actualizar `TEAM.md` para que coincida con lo construido
    - Secciones problema, usuario, justificación del agente frente a reglas, datos y métrica de éxito (1–150 palabras cada una)
    - Problema: inconsistencia Ayesa vs Ayesa Digital; usuario: marca, marketing y cumplimiento; métrica: Precision_Global ≥ 90 %, < 60 s por activo y línea base manual en minutos por activo
    - Sin Datos_Sensibles
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 10.5_

  - [x] 11.2 Crear `/workshop/Agent.md` consolidando las especificaciones, en español
    - Máximo 1.000 líneas y exactamente ocho secciones `##` no vacías: contexto, requisitos, arquitectura, flujo del agente, esquemas de datos, gestión de secretos, plan de demo, criterios de aceptación
    - Incluir íntegros los 13 requisitos de `requirements.md` (mismo número, título y criterios), Verificador_Marca, regla de vídeo, Activos_Referencia (`assets/brand/` y `brand/reference/`), `AgentUrl` (API) y `CanvasUrl` (solo navegador)
    - Describir la web (Web_Visor React/Vite, API_Visor Express, Almacen_Redis con fallback a memoria) en la sección de arquitectura, y su arranque y recorrido en el plan de demo
    - Documentar las variables de la web `REDIS_URL`, `MEDIA_BUCKET`, `PORT` y `MEDIA_DIR` (solo nombres y función, sin valores) en la sección de gestión de secretos/configuración
    - Listar las nueve salidas del evento (`AgentUrl`, `AgentTokenSecret`, `CanvasUrl`, `AudienceDataURI`, `HackathonAssetsBucketName`, `MediaToolkitIngestBucket`, `MediaToolkitRegion`, `MediaToolkitStackName`, `TestVideosURI`) con descripción de una línea, y `bash media-toolkit/connect.sh`
    - Para valores secretos referenciar solo el nombre y cómo leerlos (variable de entorno o Secrets Manager); nunca valores
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 10.5, 13.32_

  - [x] 11.3 Escribir smoke tests de documentación (`tests/test_docs.py`)
    - `Agent.md`: ≤ 1.000 líneas, ocho secciones `##`, contiene cada uno de los 13 requisitos de `requirements.md`, las nueve salidas, `connect.sh`, la descripción de la web y las variables `REDIS_URL`, `MEDIA_BUCKET`, `PORT` y `MEDIA_DIR`
    - `TEAM.md`: secciones presentes con 1–150 palabras; ambos archivos pasan el escáner de secretos
    - _Requirements: 11.1, 12.1, 12.2, 12.4, 12.7, 12.8, 10.5_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Las tareas marcadas con `*` son opcionales y se pueden omitir para un MVP más rápido
- Cada tarea referencia requisitos concretos para trazabilidad
- Los checkpoints aseguran validación incremental
- Los tests de propiedad validan propiedades universales del núcleo puro (Hypothesis, ≥ 100 ejemplos)
- Los tests unitarios validan ejemplos, bordes e integración con adaptadores falsos
- La salida del modelo multimodal, ComfyUI y S3 reales se evalúan en la demo con la Precision_Global, no con PBT
- La web (grupo 10) ya existe en `/workshop/web`: las tareas marcadas `[x]` están implementadas y solo quedan pendientes la extracción de `bbox.js`, los tests de propiedad opcionales (`fast-check`, Properties 23-31), el test de integración de `RedisStore` y la nota IAM de lectura `s3:GetObject` sobre `brand/*`
- Los tests de la web usan `node:test` y `fast-check` (≥ 100 ejecuciones, menos con Redis real) y llevan el comentario `// Feature: atm-card-incident-video-simulation, Property N: <texto>`
- No se escriben secretos en código, tests, logs, manifiestos ni documentos

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "10.8"] },
    { "id": 1, "tasks": ["1.2", "2.1", "3.1", "9.1", "9.3", "11.1", "10.9", "10.16"] },
    { "id": 2, "tasks": ["1.3", "1.4", "1.5", "2.2", "2.3", "3.2", "4.1", "6.1", "7.1", "9.2", "10.10", "10.17", "10.19"] },
    { "id": 3, "tasks": ["3.3", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "6.2", "6.3", "7.2", "7.3", "7.4", "7.5", "8.1", "10.11", "10.13"] },
    { "id": 4, "tasks": ["4.8", "4.9", "6.4", "6.5", "6.6", "8.2", "8.3", "8.4", "8.5", "8.6", "10.12", "10.14", "10.18"] },
    { "id": 5, "tasks": ["8.7", "10.15", "11.2"] },
    { "id": 6, "tasks": ["11.3"] }
  ]
}
```
