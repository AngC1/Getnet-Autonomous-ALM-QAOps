# Getnet (Grupo Santander) — Autonomous Production ALM & QAOps de Tarjetas Bancarias (Zero Human-in-the-Loop)

Plataforma de demostración ejecutiva para el **CIO de Getnet (Grupo Santander)** que simula el ciclo completo **ALM en Producción sin Human-in-the-Loop (Zero-Touch)** aplicado exclusivamente al dominio de **Tarjetas Bancarias EMV y Cajeros ATM**:

1. **Flujo Visual de Máquina de 8 Estados (`S1` a `S8`) y Orquestación de 5 Agentes Autónomos**:
   - `AGT-01 · Getnet-ATM-Vision-Agent`: Detección visual de retención de tarjeta en ranura ATM (`Getnet_ATM`) y enmascarado PCI-DSS (`redact_pan`).
   - `AGT-02 · Observability-MCP-Agent`: Correlación en tiempo real vía **MCP Server** con **Dynatrace Davis AI (`DT-PROB-2026-8841`)**, **AWS CloudWatch (`CW-ALARM-GTN-CARDLOCK-P99`)** y **Prometheus OpenSource**.
   - `AGT-03 · RAG-Knowledge-Architect-Agent`: Consulta sobre el **Motor RAG de Comportamiento de Incidencias Bancarias (`rag-knowledge-base/`)** mediante similitud coseno TF-IDF + Boost BM25.
   - `AGT-04 · Self-Healing-Patch-Agent`: Inyección en caliente de parches (`enable_emv_reversal_0420=True` + emisión `ISO-8583 MTI 0420` y `redis_lock_ttl_ms=3000` + Circuit Breaker) y despliegue Canary (`v2026.11.2-AUTONOMOUS-PRO`).
   - `AGT-05 · QAOps-Xray-Certifier-Agent`: Ejecución autónoma de los **12 Tests E2E Selenium de Tarjetas Bancarias** y **2 Tests de Estrés JMeter IA**, cerrando las incidencias en el **Cuadro de Mando de Jira Xray**.
2. **Ventanas Interactivas de Conexión MCP Server (`Dynatrace` y `AWS CloudWatch`)**:
   - Configura endpoints, tokens API / IAM Roles, ejecuta consultas **DQL (Dynatrace)** y **CloudWatch Logs Insights** en vivo e inspecciona las tramas JSON-RPC 2.0 desde `/alm-dashboard`.
3. **Base de Conocimiento & Modelo RAG de Incidencias en Producción (`rag-knowledge-base/`)**:
   - 6 Playbooks detallados de tarjetas bancarias (`RAG-PB-ATM-001` a `RAG-PB-CHB-006`) con modelo de comportamiento, propagación del fallo, causa raíz (RCA) y remediación sin intervención humana.

---

## Ejecución Rápida de la Demo Completa

```bash
# 1. Ejecutar el arnés completo Zero-Touch (RAG + MCP Dynatrace/CloudWatch/Kiro + Selenium E2E + JMeter IA)
python run_qaops_suite.py

# 2. Iniciar el servidor web en http://127.0.0.1:8080
python portal-getnet/app.py
```

- **Cuadro de Mando CIO en Jira Xray**: `http://127.0.0.1:8080/alm-dashboard`
- **Portal Operativo de Tarjetas Bancarias y Red ATM**: `http://127.0.0.1:8080/servicios-para-clientes`
- **Presentación Ejecutiva CIO Getnet**: `http://127.0.0.1:8080/presentacion`
