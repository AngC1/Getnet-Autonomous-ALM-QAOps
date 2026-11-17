# AGENTS.md — Blueprint de Ingeniería Agéntica QAOps & Autonomous Production ALM (Ayesa Digital · Getnet Grupo Santander)

Este documento define las directrices operativas de **SDD (Spec-Driven Development)**, **Multi-Agent Orchestration**, **MCP Server Integration (Dynatrace + AWS CloudWatch + Prometheus + AWS Kiro)**, **Motor RAG de Incidencias Bancarias** y **Autonomous Closed-Loop ALM (Zero Human-in-the-Loop)** sobre el ecosistema de **Tarjetas Bancarias de Getnet (`/servicios-para-clientes` y `/alm-dashboard`)**.

---

## 1. SDD — Specification-Driven Development (Dominio Exclusivo: Tarjetas Bancarias)

1. **Especificación de Dominio de Tarjetas, Incidentes PRO y Backlog (`alm-backlog/jira-xray/backlog_xray_export.json`)**:
   - Define Épicas (`GTN-EP-01`..`06`), Historias de Usuario (`GTN-US-101`..`106`), Casos de Prueba de Tarjetas Bancarias (`GTN-TC-001`..`014`) e Incidentes de Producción (`GTN-INC-ATM-001` y `GTN-INC-SYS-002`).
2. **Contratos de Interfaz, Conectores MCP y Motor RAG (`specs/sdd-getnet-tarjetas-bancarias.md`, `specs/sdd-getnet-autonomous-alm.md` y `rag-knowledge-base/`)**:
   - **Incidencia Funcional de Tarjeta en ATM (`POST /api/v1/tarjetas/bloqueo` · Motor `AWS_Kiro-main` + `RAG-PB-ATM-001`)**:
     - Valida la incidencia con `validate_incident`, enmascara el PAN según PCI-DSS (`redact_pan`), ejecuta triaje (`TARJETA_RETENIDA`) y verifica la emisión del reverso EMV `ISO-8583 MTI 0420` (`REV-EMV-2026-XXXXX`).
   - **Incidencia de Sistemas en Producción (`GET /api/v1/observability/status` · `Dynatrace + AWS CloudWatch + Prometheus MCP` + `RAG-PB-SYS-002`)**:
     - Conecta vía MCP con Dynatrace Davis AI (`DT-PROB-2026-8841`), AWS CloudWatch (`CW-ALARM-GTN-CARDLOCK-P99`) y Prometheus (`getnet_card_block_latency_p95_ms`), aplicando auto-remediación (`redis_lock_ttl_ms=3000` + Circuit Breaker) y Canary Re-Deploy (`v2026.11.2-AUTONOMOUS-PRO`).

---

## 2. Comandos del Arnés de Verificación (Verification Loop)

| Nivel del Arnés | Comando de Ejecución | Qué Verifica (Quality Gate) |
| :--- | :--- | :--- |
| **Arnés Completo Zero-Touch** | `python run_qaops_suite.py` | Levanta Portal Tarjetas Getnet + MCP Observabilidad (Dynatrace/CloudWatch/Prometheus/RAG/Kiro) + Ciclo Autónomo ALM + MCP Selenium + 12 Tests Pytest + JMeter IA (14/14 casos en Jira Xray) |
| **Arnés Motor RAG** | `python rag-knowledge-base/rag_engine.py --selftest` | Verifica indexación TF-IDF + BM25 de los 6 Playbooks de incidencias de tarjetas bancarias y síntesis agéntica |
| **Arnés MCP Observabilidad** | `python mcp-observability-server/server.py --selftest` | Verifica Dynatrace Davis AI MCP, AWS CloudWatch MCP, Prometheus MCP, Motor RAG, triaje ATM `AWS_Kiro-main` y auto-remediación |
| **Arnés MCP Selenium** | `python mcp-selenium-server/server.py --selftest` | Verifica sesión Headless, DOM Pruning, flujos de Tarjetas Bancarias Getnet (`parque_tarjetas`, `autorizacion`, `bloqueo_atm`) y captura PNG |
| **Arnés E2E Funcional Tarjetas** | `pytest selenium-qaops/tests/test_servicios_clientes_e2e.py -v` | Verifica `GTN-TC-001`..`010`, `GTN-TC-013` y `GTN-TC-014` y publica resultados en Jira Xray |
| **Arnés de Rendimiento IA** | `python jmeter-ai/ai_jmeter_assistant.py --vus 12 --iterations 5` | Verifica `GTN-TC-011` y `GTN-TC-012` sobre endpoints de tarjetas, genera `.jtl`, calcula Apdex/P95 y publica informe en Jira Xray |
