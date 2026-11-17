# Master Test Plan & Autonomous Production ALM — Getnet (Grupo Santander)

- **Código del Plan**: `GTN-TP-2026-PRO`
- **Organización**: Unidad de Ingeniería QAOps & Autonomous ALM — **Ayesa Digital**
- **Cliente**: **Getnet Europe (Grupo Santander)** — Demo Ejecutiva para el **CIO de Getnet**
- **Paradigma**: **ALM en Producción Sin Human-in-the-Loop** (Detección → Triage → Análisis RCA → Re-Fixing → Re-Deploy → Certificación en Jira Xray)

---

## 1. Alcance del Ciclo Autónomo en Producción

1. **Incidencia Funcional desde Cajero ATM (`GTN-INC-ATM-001`)**:
   - Construida sobre el motor **`AWS_Kiro-main`** (`atm_sentinel.py` y `brand_verifier/incident.py`).
   - Detecta el bloqueo y retención de una tarjeta en el cajero `ATM-GTN-MAD-0042`, enmascara el PAN conforme a PCI-DSS (`redact_pan`), ejecuta triaje automático (`TARJETA_RETENIDA`), repara la lógica de reverso EMV `ISO-8583 MTI 0420` y redespliega sin intervención humana.
2. **Incidencia de Sistemas en Producción (`GTN-INC-SYS-002`)**:
   - Detectada mediante **AWS CloudWatch Alarms / Logs Insights** y el **Servidor MCP de Monitor OpenSource (Prometheus / OpenTelemetry)** (`mcp-observability-server/server.py`).
   - Identifica saturación del pool de conexiones HikariCP y deadlock de mutex en Redis en el microservicio `getnet-card-blocker-svc`, aplica el parche de `redis_lock_ttl_ms=1500` + Circuit Breaker, redespliega en Canary y verifica el restablecimiento de SLAs con **JMeter AI**.

---

## 2. SLAs y Puertas de Calidad (Quality Gates)

| Métrica / Puerta de Calidad | Umbral Exigido en Producción (Getnet) | Estado Certificación |
| :--- | :--- | :--- |
| **Percentil 95 (P95)** | `< 450 ms` | `~45-75 ms` (PASSED) |
| **Tasa de Error Transaccional** | `<= 1.0%` | `0.0%` (PASSED) |
| **Índice Apdex ($T = 180\text{ ms}$)** | `>= 0.90` | `1.00` (PASSED) |
| **MTTD + MTTR (Zero Human-in-the-Loop)** | `< 30 segundos` | `~7.0 segundos` (PASSED) |
| **Cobertura E2E + Performance en Jira Xray** | `14 / 14 Casos Aprobados` | `14 / 14 PASSED` |
