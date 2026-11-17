# Our team

**Team name:**
**Members:**
**Use case:** Verificador de marca: Ayesa Digital (correcto) frente a Ayesa (incorrecto) en imágenes y vídeos.

## Before you build

1. **The problem.** Las imágenes y vídeos corporativos mezclan el logotipo Ayesa (incorrecto, sin "digital") con Ayesa Digital (correcto). Esta inconsistencia de marca es difícil de detectar a mano, sobre todo en vídeo, donde basta un fotograma incorrecto para incumplir la norma. Revisar cada pieza manualmente es lento y propenso a errores.
2. **Who has it.** El equipo de marca, marketing y cumplimiento. Hoy revisan cada pieza a ojo, fotograma a fotograma en vídeo. La línea base manual es un valor a medir antes de la demo (minutos por activo, hoy sin medir); no tenemos todavía un dato real.
3. **Rules or AI?** Las reglas fijas no reconocen un logotipo en una escena variable, con ángulos, tamaños y movimiento. Un agente con visión (Amazon Bedrock, `us-east-1`) compara cada imagen o fotograma con los dos logotipos de referencia, decide entre CORRECTO, INCORRECTO, SIN_LOGO o AMBIGUO y explica la evidencia con caja y marca de tiempo. Las reglas solo agregan: un fotograma INCORRECTO hace INCORRECTO el vídeo.
4. **Data.** Logotipos de referencia en `assets/brand/` y en S3 `brand/reference/`. Imágenes y vídeos de prueba (logo correcto, incorrecto y sin logo) generados con ComfyUI, no con modelos de vídeo de Bedrock, y registrados en un manifiesto con etiqueta esperada y validación humana. Sin datos personales ni de tarjeta.
5. **Success metric.** Precision_Global mayor o igual que 90 % sobre los activos de prueba validados, y menos de 60 segundos de verificación por activo. Se compara con la línea base manual, minutos por activo, pendiente de medir (valor a medir, no un hecho). Un vídeo con un solo fotograma incorrecto cuenta como INCORRECTO.

## Architecture

- **Verificador (Python, `brand_verifier`):** comprueba las referencias, genera o reutiliza el dataset, verifica imágenes y fotogramas (1 por segundo) con Bedrock multimodal, guarda veredictos en S3 y emite el informe con la precisión.
- **Generación:** ComfyUI, mediante `comfyui/client.py` contra `AgentUrl`; el token se lee de Secrets Manager o de variables de entorno, nunca del repositorio.
- **Web de visualización (`web/`):** cliente React (Vite) y API Node.js/Express. Redis guarda los activos; sin `REDIS_URL` o si Redis no responde, usa un almacén en memoria. Muestra galería, filtros, estadísticas y detalle con evidencias, y permite validar etiquetas.
- **S3 (`us-east-1`):** referencias, activos generados, veredictos e informes.

## Demo plan

1. Comprobar los logotipos de referencia.
2. Generar o reutilizar el dataset de ComfyUI (incluye un vídeo de ATM de calle con la marca en pantalla).
3. Ejecutar un único comando de verificación.
4. Mostrar el informe: tabla esperado frente a detectado, evidencias y precisión global.
5. Abrir la web de visualización: galería de imágenes y vídeos, filtros, resumen de Precision_Global, tiempo medio y falsos negativos.
