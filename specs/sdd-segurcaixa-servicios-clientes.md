# Especificación SDD (Spec-Driven Development) — Getnet Autonomous ALM & QAOps (`/servicios-para-clientes` · `/getnet-portal`)

- **ID de Especificación**: `SDD-GTN-2026-001`
- **Estado**: `APPROVED & VERIFIED (14/14 Tests Passing · Zero Human-in-the-Loop)`
- **Cliente / Ecosistema**: **Getnet Europe (Grupo Santander)** — Servicios para Comercios, Tarjetas, Pasarela ISO-8583 y Red de Cajeros ATM
- **Propietario**: Unidad de Ingeniería Agéntica QAOps & Autonomous ALM — Ayesa Digital

---

## 1. Contratos de Dominio y API REST (Portal Getnet & Motor de Tarjetas/ATM)

### 1.1 Buscador de Red de Cajeros ATM, Terminales TPV y Centros de Soporte Getnet (`GET /api/v1/cuadro-medico`)
- **Parámetros Query**:
  - `provincia` (`string`, opcional): `Madrid | Barcelona | Sevilla | Valencia | Bilbao | Todas`
  - `especialidad` (`string`, opcional): `Cajeros ATM & Cash-In | Terminales TPV SmartPOS | Pasarela E-Commerce | Cripto & Antifraude | Soporte Urgencias 24h | Oficinas Getnet | Todas` (compatible con alias legacy `Cardiología`, `Urgencias 24h`, etc.)
  - `poliza` (`string`, opcional): `Getnet Pro Commerce | Getnet SmartPOS Vital | Getnet Corporate | Getnet Premier Enterprise | Red Santander / Euro6000 | Todas`
  - `q` (`string`, opcional): Búsqueda textual sobre nombre del nodo ATM/centro, responsable técnico o dirección.
- **Invariante de Respuesta (`HTTP 200`)**:
  - Devuelve `{"filtros": {...}, "total": <int>, "resultados": [...]}`.
- **Trazabilidad Jira Xray**: `GTN-TC-002` (`TL-GTN-102`), `GTN-TC-003` (`TL-GTN-103`), `GTN-TC-011` (`TL-GTN-111`).

### 1.2 Autorizaciones ISO-8583 y Desbloqueo Operativo de Tarjetas (`POST /api/v1/autorizaciones`)
- **Payload JSON de Entrada**:
  - `numTarjeta`: PAN / Tarjeta Getnet de 12 a 16 dígitos (`^\d{12,16}$`).
  - `tipoActo`: Tipo de operación o autorización (`Autorización Previa TPV (RMN)`, `Desbloqueo PIN / Chip EMV`, `Ampliación Límite Diario POS`, `Auditoría Antifraude PCI-DSS / Estudio Genético`).
  - `codigoPrescripcion`: Referencia de operación / terminal (`OP-99281` / `RX-99281`).
  - `centroMedico`: Comercio o Nodo ATM solicitante.
- **Reglas de Negocio Verificables**:
  - **RN-AUT-01**: Si `numTarjeta` no cumple `^\d{12,16}$`, retorna `HTTP 400` con `errorCode: "INVALID_CARD_NUMBER"`.
  - **RN-AUT-02**: Si `tipoActo` corresponde a auditoría antifraude profunda (`antifraude`, `pci`, `genético`, `oncol`), retorna `HTTP 201` con `estado: "PENDIENTE_REVISION_MEDICA"` (Inspección de Riesgos / Fraude SLA 48h).
  - **RN-AUT-03**: En cualquier otra operación estándar válida, retorna `HTTP 201` con `estado: "AUTORIZADA"` y código `AUT-2026-XXXXX`.
- **Trazabilidad Jira Xray**: `GTN-TC-004` (`TL-GTN-104`), `GTN-TC-005` (`TL-GTN-105`), `GTN-TC-006` (`TL-GTN-106`), `GTN-TC-012` (`TL-GTN-112`).

### 1.3 Liquidaciones, Reembolsos de Transacciones y Chargebacks (`POST /api/v1/reembolsos`)
- **Payload JSON de Entrada**:
  - `nif`: Formato `^[0-9XYZ]\d{7}[A-Z]$`.
  - `modalidadPoliza`: `Getnet Premier (90%)` o `Getnet Extra (80%)` (compatible con alias `Adeslas Premier (90%)` / `Adeslas Extra (80%)`).
  - `importeFactura`: Importe de liquidación/disputa `> 0`.
  - `iban`: Formato español `^ES\d{22}$`.
- **Reglas de Negocio Verificables**:
  - **RN-RMB-01**: Abono inmediato del `90%` para modalidad `Premier` y `80%` para `Extra` (`importeEstimadoReembolso = round(importeFactura * cobertura, 2)`).
  - **RN-RMB-02**: Si el IBAN no cumple `^ES\d{22}$`, retorna `HTTP 400` con `errorCode: "INVALID_IBAN"`.
- **Trazabilidad Jira Xray**: `GTN-TC-007` (`TL-GTN-107`), `GTN-TC-008` (`TL-GTN-108`).

### 1.4 Área Cliente / Comercio, Tarjeta Digital Corporativa y Soporte 24h (`POST /api/v1/auth/login` y `POST /api/v1/citas`)
- **Reglas de Negocio Verificables**:
  - **RN-CLI-01**: Login válido con `12345678Z` / `Getnet2026!` (o `Adeslas2026!`) despliega contrato `MRC-GTN-908122` (`POL-SCA-908122`) y Tarjeta Digital Corporativa Getnet `8000123456789012`.
  - **RN-CIT-01**: Solicitud de soporte técnico remoto / videoconsulta 24h con motivo válido retorna `HTTP 201`, estado `CONFIRMADA` y código `CIT-2026-XXXXX`.
- **Trazabilidad Jira Xray**: `GTN-TC-009` (`TL-GTN-109`), `GTN-TC-010` (`TL-GTN-110`).

---

## 2. Especificación del Ciclo ALM en Producción Sin Human-in-the-Loop (Demo CIO Getnet)

### 2.1 Incidencia 1: Funcional desde Cajero ATM (`GTN-INC-ATM-001` · Motor `AWS_Kiro-main`)
- **Endpoint de Simulación**: `POST /api/v1/tarjetas/bloqueo`
- **Origen**: Cajero `ATM-GTN-MAD-0042` (`AWS_Kiro-main/atm_sentinel.py` + `brand_verifier/incident.py`).
- **Comportamiento en Estado Degradado (Incidencia Activa)**:
  - Cuando se reporta un evento de bloqueo preventivo en ranura de cajero para una tarjeta (`4548 1234 5678 9012`), el flag defectuoso `enable_emv_reversal_0420 = False` provoca que la tarjeta quede en estado `ERROR_TARJETA_RETENIDA_SIN_REVERSO` (`HTTP 409`), sin emitir reverso ISO-8583 `MTI 0420` ni liberar el plástico.
- **Detección, Triaje, Análisis, Re-Fixing y Re-Deploy Autónomo**:
  1. `AWS_Kiro-main` valida la incidencia (`validate_incident`), enmascara el PAN según PCI-DSS (`redact_pan` -> `**** **** **** 9012`), construye el prompt de escena seguro (`scene_prompt`) y ejecuta el triaje (`TARJETA_RETENIDA`, severidad `ALTA`, riesgo `CRITICO`).
  2. El motor ALM registra `GTN-INC-ATM-001` en Jira Xray, identifica la regresión en `card_lock_engine`, aplica el hotfix (`enable_emv_reversal_0420 = True`, `eject_or_digital_token = True`), redespliega en PRO y certifica el test `GTN-TC-013` (`HTTP 200`, estado `BLOQUEO_PREVENTIVO_CON_REVERSO_EMV_0420` y código `REV-EMV-2026-XXXXX`).

### 2.2 Incidencia 2: Sistemas en Producción desde AWS CloudWatch y Monitor OpenSource MCP (`GTN-INC-SYS-002`)
- **Endpoints de Observabilidad y Remediación**:
  - `GET /api/v1/observability/status`
  - `GET /api/v1/observability/prometheus`
  - `POST /api/v1/alm/inject-incidents`
  - `POST /api/v1/alm/autonomous-cycle`
- **Origen**: Alarma crítica en **AWS CloudWatch** (`CW-ALARM-GTN-CARDLOCK-P99` en `/aws/ecs/getnet-card-blocker-svc`) y alerta en el **Servidor MCP de Monitor OpenSource (Prometheus / OpenTelemetry)** (`mcp-observability-server/server.py`).
- **Comportamiento en Estado Degradado (Incidencia Activa)**:
  - Ausencia de TTL en lock distribuido Redis (`redis_lock_ttl_ms = 0`) + agotamiento del pool HikariCP (`db_pool_usage_pct = 98.5%`, `P95 = 1840 ms > 450 ms SLA`), disparando errores `HTTP 503` y estado `ALARM`.
- **Detección, Triaje, Análisis, Re-Fixing y Re-Deploy Autónomo**:
  1. El servidor MCP `mcp-observability-server` correlaciona las métricas de Prometheus y los logs de CloudWatch Logs Insights.
  2. El motor ALM abre `GTN-INC-SYS-002` en Jira Xray, inyecta el parche de infraestructura/código (`redis_lock_ttl_ms = 1500`, `circuit_breaker_enabled = True`, `redis_cache_enabled = True`), realiza Canary Rollout (`v2026.11.2-AUTO-HOTFIX`), restablece las alarmas CloudWatch/Prometheus a `OK` (`P95 < 80 ms`) y certifica `GTN-TC-014`.
