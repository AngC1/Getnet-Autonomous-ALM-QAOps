# AGENTS.md — Blueprint de Ingeniería Agéntica QAOps & Autonomous Production ALM (Ayesa Digital · Getnet Grupo Santander)

Este documento define las directrices operativas de **SDD (Spec-Driven Development)**, **Prompt Engineering**, **Context Engineering**, **Harness Engineering** y **Autonomous Closed-Loop ALM (Zero Human-in-the-Loop)** para todos los agentes de IA que operan sobre el ecosistema de **Getnet (`/servicios-para-clientes` y `/alm-dashboard`)**.

---

## 1. SDD — Specification-Driven Development (Desarrollo Guiado por Especificaciones)

En el modelo **QAOps & Autonomous ALM de Ayesa Digital para Getnet**, ningún código de aplicación, hotfix autónomo ni script de prueba se ejecuta sin una especificación verificable previa:

1. **Especificación de Dominio, Incidentes PRO y Backlog (`alm-backlog/jira-xray/backlog_xray_export.json`)**:
   - Define Épicas (`GTN-EP-01`..`06`), Historias de Usuario (`GTN-US-101`..`108`), Casos de Prueba (`GTN-TC-001`..`014`) e Incidentes de Producción (`GTN-INC-ATM-001` y `GTN-INC-SYS-002`).
2. **Contratos de Interfaz y Ciclo ALM Sin Human-in-the-Loop (`specs/sdd-segurcaixa-servicios-clientes.md` y `specs/sdd-getnet-autonomous-alm.md`)**:
   - **Incidencia Funcional ATM (`POST /api/v1/tarjetas/bloqueo` · Motor `AWS_Kiro-main`)**:
     - Valida la incidencia con `validate_incident`, enmascara el PAN según PCI-DSS (`redact_pan`), ejecuta triaje (`TARJETA_RETENIDA`) y verifica la emisión del reverso EMV `ISO-8583 MTI 0420` (`REV-EMV-2026-XXXXX`).
   - **Incidencia de Sistemas en Producción (`GET /api/v1/observability/status` · `AWS CloudWatch + Prometheus MCP`)**:
     - Monitoriza alarmas CloudWatch (`CW-ALARM-GTN-CARDLOCK-P99`) y métricas Prometheus (`getnet_card_block_latency_p95_ms`, `getnet_redis_mutex_deadlocks_total`), aplicando auto-remediación (`redis_lock_ttl_ms=1500` + Circuit Breaker) y Canary Re-Deploy (`v2026.11.2-AUTONOMOUS-PRO`).

---

## 2. Comandos del Arnés de Verificación (Verification Loop)

| Nivel del Arnés | Comando de Ejecución | Qué Verifica (Quality Gate) |
| :--- | :--- | :--- |
| **Arnés Completo Zero-Touch** | `python run_qaops_suite.py` | Levanta SUT Getnet + MCP Observabilidad (CloudWatch/Prometheus/Kiro) + Ciclo Autónomo ALM + MCP Selenium + 12 Tests Pytest + JMeter IA (14/14 casos en Jira Xray) |
| **Arnés MCP Observabilidad** | `python mcp-observability-server/server.py --selftest` | Verifica alarmas AWS CloudWatch, métricas Prometheus OpenSource, triaje ATM `AWS_Kiro-main` y auto-remediación sin Human-in-the-Loop |
| **Arnés MCP Selenium** | `python mcp-selenium-server/server.py --selftest` | Verifica sesión Headless, DOM Pruning, flujos Getnet (Red ATM, Autorizaciones, Bloqueo ATM) y captura PNG |
| **Arnés E2E Funcional** | `pytest selenium-qaops/tests/test_servicios_clientes_e2e.py -v` | Verifica `GTN-TC-001`..`010`, `GTN-TC-013` y `GTN-TC-014` y publica resultados en Jira Xray |
| **Arnés de Rendimiento IA** | `python jmeter-ai/ai_jmeter_assistant.py --vus 12 --iterations 5` | Verifica `GTN-TC-011` y `GTN-TC-012`, genera `.jtl`, calcula Apdex/P95 y publica informe en Jira Xray |
