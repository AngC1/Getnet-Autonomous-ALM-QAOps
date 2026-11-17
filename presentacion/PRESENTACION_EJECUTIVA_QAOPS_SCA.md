# Presentación Ejecutiva CIO Getnet — ALM en Producción Sin Human-in-the-Loop & QAOps

- **Audiencia**: **CIO y Comité de Dirección de Tecnología — Getnet Europe (Grupo Santander)**
- **Unidad**: **Ayesa Digital · Ingeniería Agéntica QAOps & Autonomous Production ALM**
- **Objetivo de la Demo**: Demostrar en vivo un ciclo completo de **Detección → Triage → Análisis RCA → Re-Fixing → Re-Deploy → Certificación en Jira Xray** sin intervención humana (*Zero Human-in-the-Loop*) resolviendo simultáneamente:
  1. **Una incidencia funcional desde un Cajero ATM (`GTN-INC-ATM-001`)** construida con **`AWS_Kiro-main`** (`atm_sentinel.py` + `brand_verifier/incident.py`) sobre una aplicación de **bloqueo y retención de tarjetas**.
  2. **Una incidencia de sistemas en Producción (`GTN-INC-SYS-002`)** detectada desde **AWS CloudWatch** y un **Servidor MCP de Monitor OpenSource (Prometheus / OpenTelemetry)**.

---

## 1. Guion de la Demo en Vivo para el CIO de Getnet

1. **Estado Inicial Saludable (`/alm-dashboard`)**:
   - Mostrar el Cuadro de Mando Ejecutivo en Jira Xray con **14/14 Test Cases PASSED** (`GTN-TC-001` a `GTN-TC-014`) y release activa `v2026.11.2-AUTONOMOUS-PRO`.
2. **Inyección de Fallos Reales en Producción (`🔥 1. Simular Fallo PRO`)**:
   - **Fallo Funcional ATM (`GTN-INC-ATM-001`)**: En el cajero `ATM-GTN-MAD-0042` (Gran Vía 28, Madrid), una tarjeta (`4548 1234 5678 9012`) sufre bloqueo preventivo sin emitir la trama de reverso `ISO-8583 MTI 0420` (`enable_emv_reversal_0420=False`), quedando retenida (`HTTP 409`).
   - **Fallo de Sistemas (`GTN-INC-SYS-002`)**: En `getnet-card-blocker-svc`, un lock distribuido en Redis sin TTL (`redis_lock_ttl_ms=0`) agota el pool HikariCP (`98.5%`) y dispara la alarma `CW-ALARM-GTN-CARDLOCK-P99` en AWS CloudWatch y Prometheus (`P95 = 1840 ms`).
3. **Resolución Autónoma Sin Human-in-the-Loop (`🤖 2. Ciclo ALM Sin Human-in-the-Loop`)**:
   - **Detección y Triage**: `AWS_Kiro-main` enmascara el PAN (`4548 **** **** 9012`), analiza los fotogramas del cajero y clasifica la incidencia (`TARJETA_RETENIDA / ALTA`). El servidor MCP `mcp-observability-server` correlaciona CloudWatch Logs Insights y Prometheus.
   - **RCA, Re-Fixing y Re-Deploy**: El agente aplica en caliente los parches `PATCH-GTN-ATM-0420` y `PATCH-GTN-SYS-REDIS`, despliega la versión `v2026.11.2-AUTONOMOUS-PRO`, ejecuta la regresión Selenium MCP + Pytest + JMeter IA y cierra ambos tickets en **Jira Xray** en menos de 7 segundos.
