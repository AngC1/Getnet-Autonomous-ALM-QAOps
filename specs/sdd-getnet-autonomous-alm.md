# Especificación SDD — Ciclo ALM Autónomo en Producción Sin Human-in-the-Loop, Conectores MCP (Dynatrace + CloudWatch) y Motor RAG

## 1. Máquina de Estados del Ciclo Autónomo (8 Estados) y Orquestación de 5 Agentes

| Orden | Estado (`stateId`) | Agente Responsable | Herramientas MCP Invocadas | Transición de Salida |
| :--- | :--- | :--- | :--- | :--- |
| **1** | `S1_TELEMETRY_STREAM` | `Getnet-ATM-Vision-Agent` + `Observability-MCP-Agent` | `atm_kiro_inspect_incident`, `dynatrace_get_davis_problems`, `cloudwatch_get_alarms` | Ingesta de vídeo ATM + Spans PurePath Dynatrace + Alarmas CloudWatch |
| **2** | `S2_ANOMALY_DETECTION` | `Getnet-ATM-Vision-Agent` | `validate_incident`, `redact_pan` | PAN enmascarado (`4548 **** **** 9012`) y apertura de `GTN-INC-ATM-001` y `GTN-INC-SYS-002` |
| **3** | `S3_MCP_CORRELATION` | `Observability-MCP-Agent` | `dynatrace_execute_dql`, `cloudwatch_query_logs_insights`, `prometheus_query_metrics` | Correlación de `DT-PROB-2026-8841` (Dynatrace) con `CW-ALARM-GTN-CARDLOCK-P99` (CloudWatch) |
| **4** | `S4_RAG_KNOWLEDGE_LOOKUP` | `RAG-Knowledge-Architect-Agent` | `rag_retrieve_incident_playbook` | Recuperación de Playbooks `RAG-PB-ATM-001` (`99%`) y `RAG-PB-SYS-002` (`99%`) |
| **5** | `S5_RCA_TRIAGE_SYNTHESIS` | `RAG-Knowledge-Architect-Agent` + `Getnet-ATM-Vision-Agent` | `process_incident`, `assemble_report` | Síntesis de plan Zero-Touch: reverso `MTI 0420` + `redis_lock_ttl_ms=3000` |
| **6** | `S6_SELF_HEALING_HOTFIX` | `Self-Healing-Patch-Agent` | `alm_autonomous_zero_touch_cycle` | Aplicación en caliente de `PATCH-GTN-ATM-0420` y `PATCH-GTN-SYS-REDIS` |
| **7** | `S7_CANARY_QAOPS_GATE` | `QAOps-Xray-Certifier-Agent` | `selenium_execute_tarjetas_flow`, `ai_jmeter_assistant` | Release `v2026.11.2-AUTONOMOUS-PRO` validada con 12 tests Selenium + 2 tests JMeter IA |
| **8** | `S8_ALM_XRAY_CLOSED` | `QAOps-Xray-Certifier-Agent` | `alm_sync_test_result` | `14/14` casos `PASSED` y `2/2` incidencias `RESOLVED` en Jira Xray |

## 2. Conectores MCP Server (`POST /api/v1/mcp/connect`)
- **Dynatrace Davis AI & Grail DQL (`getnet-dynatrace-davis-mcp`)**: Inspección de `DT-PROB-2026-8841`, topología Smartscape (`SERVICE-GETNET-CARD-BLOCKER`, `PROCESS_GROUP-REDIS-CARD-MUTEX`, `CUSTOM_DEVICE-ATM-MAD-0042`) y consultas DQL en vivo.
- **AWS CloudWatch (`getnet-aws-cloudwatch-mcp`)**: Inspección de alarma `CW-ALARM-GTN-CARDLOCK-P99` y ejecución de consultas en CloudWatch Logs Insights (`/aws/ecs/getnet-card-blocker-svc`).
- **Getnet ATM ATM Sentinel (`getnet-atm-edge-mcp`)**: Validación de eventos de cajero `ATM-GTN-MAD-0042` y redacción de PAN según PCI-DSS 4.0.
- **Prometheus & OpenTelemetry (`getnet-prometheus-otel-mcp`)**: Scraping OpenMetrics en `/api/v1/observability/prometheus`.
