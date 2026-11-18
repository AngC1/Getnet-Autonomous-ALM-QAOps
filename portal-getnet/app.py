"""
Simulador del Portal Getnet (Grupo Santander) — Operativa de Tarjetas Bancarias y Red ATM (/servicios-para-clientes)
+ Aplicativo de Sistema de Bloqueo Preventivo de Tarjetas Bancarias en ATM (Getnet_ATM)
+ Conectores MCP Server en Vivo con Dynatrace (Davis AI / PurePath) y AWS CloudWatch (Alarms / Logs Insights)
+ Motor RAG y Base de Conocimiento de Comportamiento de Incidencias Bancarias en Producción (rag-knowledge-base/)
+ Flujo Visual de Máquina de Estados y Orquestación Multi-Agente ALM Sin Human-in-the-Loop (Jira Xray).
Desarrollado para la Demo Ejecutiva con el CIO de Getnet — Ayesa Digital QAOps.
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, Response, jsonify, redirect, render_template, request, send_file

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
ALM_JSON_PATH = PROJECT_ROOT / "alm-backlog" / "jira-xray" / "backlog_xray_export.json"
TESTLINK_XML_PATH = PROJECT_ROOT / "alm-backlog" / "testlink" / "getnet_tarjetas_testplan_testlink.xml"
REDMINE_CSV_PATH = PROJECT_ROOT / "alm-backlog" / "redmine" / "redmine_issues_backlog.csv"

GETNET_ATM_DIR = PROJECT_ROOT / "Getnet_ATM"
RAG_DIR = PROJECT_ROOT / "rag-knowledge-base"
for p in (GETNET_ATM_DIR, RAG_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from brand_verifier.incident import (  # noqa: E402
    redact_pan,
    scene_prompt,
    validate_incident,
    validate_triage,
)
import atm_sentinel  # noqa: E402
from rag_engine import IncidentRAGEngine  # noqa: E402

app = Flask(__name__, template_folder="templates", static_folder="static")
RAG_ENGINE = IncidentRAGEngine()

# ---------------------------------------------------------------------------
# Estado en Vivo del Sistema de Tarjetas Bancarias, MCP Connectors y Ciclo ALM
# ---------------------------------------------------------------------------

SYSTEM_INCIDENT_STATE: Dict[str, Any] = {
    "environment": "PRODUCTION (eu-west-1 · Zero Human-in-the-Loop)",
    "currentRelease": "v2026.11.2-AUTONOMOUS-PRO",
    "atm_functional_bug_active": False,
    "systems_cloudwatch_bug_active": False,
    "enable_emv_reversal_0420": True,
    "auto_issue_digital_token": True,
    "redis_lock_ttl_ms": 3000,
    "circuit_breaker_enabled": True,
    "redis_cache_enabled": True,
    "lastAutonomousRun": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "autonomousCyclesCount": 4,
}

MCP_CONNECTIONS_STATE: Dict[str, Dict[str, Any]] = {
    "dynatrace": {
        "provider": "Dynatrace Davis AI & OneAgent Smartscape MCP",
        "serverName": "getnet-dynatrace-davis-mcp",
        "transport": "JSON-RPC 2.0 over stdio / SSE",
        "endpointUrl": "https://getnet-prod.live.dynatrace.com/api/v2",
        "apiTokenMasked": "dt0c01.GETNET_PRO_CARDS.****************8841",
        "status": "CONNECTED",
        "latencyMs": 18,
        "monitoredEntities": [
            "SERVICE-GETNET-CARD-BLOCKER",
            "SERVICE-GETNET-ISO8583-AUTH",
            "PROCESS_GROUP-REDIS-CARD-MUTEX",
            "CUSTOM_DEVICE-ATM-MAD-0042",
        ],
        "lastSync": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    },
    "cloudwatch": {
        "provider": "AWS CloudWatch Alarms, Logs Insights & X-Ray MCP",
        "serverName": "getnet-aws-cloudwatch-mcp",
        "transport": "JSON-RPC 2.0 over stdio",
        "region": "eu-west-1 (Irlanda · Core Tarjetas Getnet)",
        "iamRoleArn": "arn:aws:iam::904211884210:role/Getnet-Autonomous-ALM-MCP-Role",
        "logGroup": "/aws/ecs/getnet-card-blocker-svc",
        "status": "CONNECTED",
        "latencyMs": 22,
        "lastSync": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    },
    "prometheus": {
        "provider": "Prometheus + OpenTelemetry Collector MCP (OpenSource)",
        "serverName": "getnet-prometheus-otel-mcp",
        "transport": "JSON-RPC 2.0 over stdio",
        "endpointUrl": "http://127.0.0.1:8080/api/v1/observability/prometheus",
        "status": "CONNECTED",
        "latencyMs": 9,
        "lastSync": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    },
    "getnet_atm": {
        "provider": "Getnet ATM Sentinel Vision & PCI-DSS Edge MCP",
        "serverName": "getnet-atm-edge-mcp",
        "transport": "JSON-RPC 2.0 over stdio",
        "atmNode": "ATM-GTN-MAD-0042 (Gran Vía 28, Madrid)",
        "s3Bucket": "s3://getnet-atm-incidents-pro",
        "status": "CONNECTED",
        "latencyMs": 14,
        "lastSync": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    },
}
MCP_CONNECTIONS_STATE["kiro_atm"] = MCP_CONNECTIONS_STATE["getnet_atm"]

# ---------------------------------------------------------------------------
# Máquina de Estados Visual (8 Estados) y Orquestación de 5 Agentes Autónomos
# ---------------------------------------------------------------------------

STATE_MACHINE_FLOW: List[Dict[str, Any]] = [
    {
        "stateId": "S1_TELEMETRY_STREAM",
        "order": 1,
        "name": "Ingesta de Telemetría",
        "badge": "TELEMETRÍA",
        "agent": "Getnet-ATM-Vision-Agent + Observability-MCP-Agent",
        "mcpTools": ["getnet_atm_inspect_incident", "dynatrace_get_davis_problems", "cloudwatch_get_alarms"],
        "status": "COMPLETED",
        "durationMs": 320,
        "inputSignal": "Stream de vídeo ATM-GTN-MAD-0042 + Spans PurePath Dynatrace + Métricas CloudWatch",
        "outputTransition": "Detectada anomalía funcional en ranura de tarjeta o degradación P99 en microservicio",
        "inspectorDetail": "{\n  \"state\": \"S1_TELEMETRY_STREAM\",\n  \"atmNode\": \"ATM-GTN-MAD-0042\",\n  \"dynatraceProblem\": \"DT-PROB-2026-8841\",\n  \"cloudwatchAlarm\": \"CW-ALARM-GTN-CARDLOCK-P99\",\n  \"prometheusMetric\": \"getnet_card_block_latency_p95_ms = 1840.0\"\n}",
    },
    {
        "stateId": "S2_ANOMALY_DETECTION",
        "order": 2,
        "name": "Detección & Redacción PCI-DSS",
        "badge": "DETECCIÓN",
        "agent": "Getnet-ATM-Vision-Agent",
        "mcpTools": ["brand_verifier.incident.validate_incident", "brand_verifier.incident.redact_pan"],
        "status": "COMPLETED",
        "durationMs": 410,
        "inputSignal": "PAN 4548 1234 5678 9012 retenido en obturador + Alarma CW-ALARM-GTN-CARDLOCK-P99",
        "outputTransition": "PAN enmascarado (4548 **** **** 9012) y apertura de GTN-INC-ATM-001 + GTN-INC-SYS-002",
        "inspectorDetail": "{\n  \"state\": \"S2_ANOMALY_DETECTION\",\n  \"engine\": \"Getnet_ATM (brand_verifier.incident)\",\n  \"rawPan\": \"[REDACTED_BY_PCI_DSS_4_0]\",\n  \"maskedPan\": \"4548 **** **** 9012\",\n  \"incidentsCreated\": [\"GTN-INC-ATM-001\", \"GTN-INC-SYS-002\"]\n}",
    },
    {
        "stateId": "S3_MCP_CORRELATION",
        "order": 3,
        "name": "Correlación MCP (Dynatrace + CloudWatch)",
        "badge": "CORRELACIÓN MCP",
        "agent": "Observability-MCP-Agent",
        "mcpTools": ["dynatrace_execute_dql", "cloudwatch_query_logs_insights", "prometheus_query_metrics"],
        "status": "COMPLETED",
        "durationMs": 540,
        "inputSignal": "Problema Davis AI DT-PROB-2026-8841 + CloudWatch Logs Insights (/aws/ecs/getnet-card-blocker-svc)",
        "outputTransition": "Huella confirmada: EMV_LOCK_RACE_CONDITION (ATM) + REDIS_LOCK_TTL_MISSING (HikariCP 98.5%)",
        "inspectorDetail": "{\n  \"state\": \"S3_MCP_CORRELATION\",\n  \"dqlQuery\": \"fetch spans | filter dt.entity.service == 'SERVICE-GETNET-CARD-BLOCKER'\",\n  \"davisRootCause\": \"PROCESS_GROUP-REDIS-CARD-MUTEX (redis_lock_ttl_ms=0)\",\n  \"cloudwatchException\": \"DeadlockDetectedException: HikariPool-1 timeout (98.5%)\"\n}",
    },
    {
        "stateId": "S4_RAG_KNOWLEDGE_LOOKUP",
        "order": 4,
        "name": "Consulta Motor RAG de Incidencias",
        "badge": "RAG LOOKUP",
        "agent": "RAG-Knowledge-Architect-Agent",
        "mcpTools": ["rag_retrieve_incident_playbook"],
        "status": "COMPLETED",
        "durationMs": 290,
        "inputSignal": "Query vectorial TF-IDF + BM25 sobre incident_knowledge_base.json (6 Playbooks Bancarios)",
        "outputTransition": "Recuperados Playbooks RAG-PB-ATM-001 (Score 0.99) y RAG-PB-SYS-002 (Score 0.99)",
        "inspectorDetail": "{\n  \"state\": \"S4_RAG_KNOWLEDGE_LOOKUP\",\n  \"engine\": \"getnet-banking-incident-hybrid-v3 (TF-IDF + BM25)\",\n  \"matchedPlaybooks\": [\n    {\"id\": \"RAG-PB-ATM-001\", \"score\": 0.99, \"incident\": \"GTN-INC-ATM-001\"},\n    {\"id\": \"RAG-PB-SYS-002\", \"score\": 0.99, \"incident\": \"GTN-INC-SYS-002\"}\n  ]\n}",
    },
    {
        "stateId": "S5_RCA_TRIAGE_SYNTHESIS",
        "order": 5,
        "name": "Triaje Cognitivo & Síntesis RCA",
        "badge": "TRIAGE & RCA",
        "agent": "RAG-Knowledge-Architect-Agent + Getnet-ATM-Vision-Agent",
        "mcpTools": ["brand_verifier.incident.process_incident", "atm_sentinel.assemble_report"],
        "status": "COMPLETED",
        "durationMs": 680,
        "inputSignal": "Playbooks RAG + Telemetría de fotogramas S3 (frame_01, frame_03, frame_06)",
        "outputTransition": "Plan Zero-Touch sintetizado: habilitar reverso ISO-8583 MTI 0420 e inyectar TTL Redis = 3000ms",
        "inspectorDetail": "{\n  \"state\": \"S5_RCA_TRIAGE_SYNTHESIS\",\n  \"categoria\": \"TARJETA_RETENIDA\",\n  \"severidad\": \"ALTA\",\n  \"synthesizedRemediation\": [\n    \"enable_emv_reversal_0420 = True (Emitir MTI 0420 + Token Wallet)\",\n    \"redis_lock_ttl_ms = 3000 + Circuit Breaker Resilience4j\"\n  ]\n}",
    },
    {
        "stateId": "S6_SELF_HEALING_HOTFIX",
        "order": 6,
        "name": "Re-Fixing Autónomo en Caliente",
        "badge": "RE-FIXING",
        "agent": "Self-Healing-Patch-Agent",
        "mcpTools": ["alm_autonomous_zero_touch_cycle"],
        "status": "COMPLETED",
        "durationMs": 890,
        "inputSignal": "Parches PATCH-GTN-ATM-0420 (enable_emv_reversal_0420=True) y PATCH-GTN-SYS-REDIS (TTL=3000ms)",
        "outputTransition": "Reverso REV-EMV-2026 emitido, plástico liberado, token Wallet creado y pool HikariCP en 18.4%",
        "inspectorDetail": "--- a/card_lock_engine.py\n+++ b/card_lock_engine.py\n@@ -42,3 +42,3 @@\n-enable_emv_reversal_0420 = False\n-redis_lock_ttl_ms = 0\n+enable_emv_reversal_0420 = True  # PATCH-GTN-ATM-0420\n+redis_lock_ttl_ms = 3000         # PATCH-GTN-SYS-REDIS",
    },
    {
        "stateId": "S7_CANARY_QAOPS_GATE",
        "order": 7,
        "name": "Re-Deploy Canary & Quality Gate Tarjetas",
        "badge": "RE-DEPLOY & GATE",
        "agent": "QAOps-Xray-Certifier-Agent",
        "mcpTools": ["selenium_execute_tarjetas_flow", "jmeter_ai_card_stress_gate"],
        "status": "COMPLETED",
        "durationMs": 1450,
        "inputSignal": "Release v2026.11.2-AUTONOMOUS-PRO + 12 Tests Selenium E2E Tarjetas + 2 Tests JMeter IA",
        "outputTransition": "14/14 Casos de Prueba de Tarjetas Bancarias PASSED (Latencia P95 = 42.5ms, Apdex = 1.0)",
        "inspectorDetail": "{\n  \"state\": \"S7_CANARY_QAOPS_GATE\",\n  \"deployedRelease\": \"v2026.11.2-AUTONOMOUS-PRO\",\n  \"seleniumE2E\": \"12/12 PASSED (DOM Pruning -93.1% tokens)\",\n  \"jmeterAiGate\": \"2/2 PASSED (P95 = 42.5ms, Apdex = 1.0)\"\n}",
    },
    {
        "stateId": "S8_ALM_XRAY_CLOSED",
        "order": 8,
        "name": "Certificación & Cierre en Jira Xray",
        "badge": "CERRADO EN XRAY",
        "agent": "QAOps-Xray-Certifier-Agent",
        "mcpTools": ["alm_sync_test_result"],
        "status": "COMPLETED",
        "durationMs": 240,
        "inputSignal": "Evidencias PNG, trazas PurePath Dynatrace, alarmas CloudWatch OK y matriz Xray",
        "outputTransition": "GTN-INC-ATM-001 y GTN-INC-SYS-002 cerradas en estado RESOLVED (Zero Human-in-the-Loop)",
        "inspectorDetail": "{\n  \"state\": \"S8_ALM_XRAY_CLOSED\",\n  \"xrayTestPlan\": \"GTN-TP-2026-TARJETAS (14/14 PASSED)\",\n  \"incidentsClosed\": [\"GTN-INC-ATM-001\", \"GTN-INC-SYS-002\"],\n  \"humanInterventionRequired\": false\n}",
    },
]

AUTONOMOUS_AGENTS_ROSTER: List[Dict[str, Any]] = [
    {
        "agentId": "AGT-01-GETNET-ATM-VISION",
        "name": "Getnet-ATM-Vision-Agent",
        "role": "Especialista Funcional en Cajeros ATM & Privacidad PCI-DSS (Getnet_ATM)",
        "currentState": "S2_ANOMALY_DETECTION -> S5_RCA_TRIAGE_SYNTHESIS",
        "status": "ACTIVE_READY",
        "model": "Claude Sonnet 4.5 (Bedrock Converse API) + OpenCV Frame Extractor",
        "mcpServer": "getnet-atm-edge-mcp",
        "responsibilities": [
            "Extrae fotogramas clave del cajero ATM-GTN-MAD-0042 y detecta retención mecánica de tarjeta (CARD_TRAPPING).",
            "Aplica enmascaramiento determinista de PAN (redact_pan -> 4548 **** **** 9012) antes de persistir en S3.",
            "Valida el contrato JSON de incidencia ATM y coordina la orden de reverso EMV ISO-8583 MTI 0420.",
        ],
        "lastAction": "Tarjeta 4548 **** **** 9012 protegida bajo PCI-DSS y triaje TARJETA_RETENIDA emitido.",
    },
    {
        "agentId": "AGT-02-OBS-MCP",
        "name": "Observability-MCP-Agent",
        "role": "Correlador de Telemetría Híbrida (Dynatrace Davis AI + AWS CloudWatch + Prometheus)",
        "currentState": "S1_TELEMETRY_STREAM -> S3_MCP_CORRELATION",
        "status": "ACTIVE_READY",
        "model": "Getnet SRE Telemetry Correlator v2.0",
        "mcpServer": "getnet-dynatrace-davis-mcp + getnet-aws-cloudwatch-mcp",
        "responsibilities": [
            "Conecta vía MCP con Dynatrace para inspeccionar problemas Davis AI (DT-PROB-2026-8841) y trazas PurePath.",
            "Interroga AWS CloudWatch Alarms (CW-ALARM-GTN-CARDLOCK-P99) y ejecuta consultas en Logs Insights.",
            "Cruza métricas Prometheus (getnet_redis_mutex_deadlocks_total) con fallos de bloqueo de tarjetas.",
        ],
        "lastAction": "Correlacionado deadlock Redis (TTL=0) entre Dynatrace PurePath y CloudWatch Logs Insights.",
    },
    {
        "agentId": "AGT-03-RAG-BRAIN",
        "name": "RAG-Knowledge-Architect-Agent",
        "role": "Motor de Recuperación Aumentada (RAG) de Comportamiento de Incidencias Bancarias",
        "currentState": "S4_RAG_KNOWLEDGE_LOOKUP -> S5_RCA_TRIAGE_SYNTHESIS",
        "status": "ACTIVE_READY",
        "model": "getnet-banking-incident-hybrid-v3 (TF-IDF Cosine + BM25 Telemetry Fingerprint)",
        "mcpServer": "getnet-observability-dynatrace-cloudwatch-atm-mcp (rag_retrieve_incident_playbook)",
        "responsibilities": [
            "Indexa y consulta los 6 Playbooks de producción de tarjetas bancarias (incident_knowledge_base.json).",
            "Explica el modelo de propagación del fallo desde el lector EMV o pool HikariCP hasta el impacto en negocio.",
            "Sintetiza el parche exacto de configuración y los casos de prueba Jira Xray requeridos para el cierre.",
        ],
        "lastAction": "Playbooks RAG-PB-ATM-001 (99%) y RAG-PB-SYS-002 (99%) entregados al agente de remediación.",
    },
    {
        "agentId": "AGT-04-SELF-HEAL",
        "name": "Self-Healing-Patch-Agent",
        "role": "Ingeniero Autónomo de Hotfixing & Canary Re-Deploy en Producción",
        "currentState": "S6_SELF_HEALING_HOTFIX -> S7_CANARY_QAOPS_GATE",
        "status": "ACTIVE_READY",
        "model": "Getnet Autonomous Patch Synthesizer (Zero-Touch)",
        "mcpServer": "getnet-observability-dynatrace-cloudwatch-atm-mcp (alm_autonomous_zero_touch_cycle)",
        "responsibilities": [
            "Inyecta en caliente enable_emv_reversal_0420=True y emite el reverso financiero ISO-8583 MTI 0420.",
            "Aplica redis_lock_ttl_ms=3000 y activa Circuit Breaker Resilience4j para drenar el pool HikariCP al 18.4%.",
            "Promociona la release Canary v2026.11.2-AUTONOMOUS-PRO sin intervención humana.",
        ],
        "lastAction": "Parches PATCH-GTN-ATM-0420 y PATCH-GTN-SYS-REDIS aplicados en v2026.11.2-AUTONOMOUS-PRO.",
    },
    {
        "agentId": "AGT-05-QAOPS-XRAY",
        "name": "QAOps-Xray-Certifier-Agent",
        "role": "Auditor Autónomo de Calidad Funcional (Selenium MCP), Rendimiento (JMeter IA) y Jira Xray",
        "currentState": "S7_CANARY_QAOPS_GATE -> S8_ALM_XRAY_CLOSED",
        "status": "ACTIVE_READY",
        "model": "Getnet QAOps Verification Harness",
        "mcpServer": "getnet-selenium-qaops",
        "responsibilities": [
            "Ejecuta los 12 tests E2E de tarjetas bancarias con Selenium Headless y DOM Pruning (-92.8% tokens).",
            "Lanza el test de estrés JMeter IA sobre los endpoints de bloqueo y autorización de tarjetas.",
            "Publica la matriz 14/14 PASSED en Jira Xray, TestLink y Redmine cerrando el ciclo ALM.",
        ],
        "lastAction": "14/14 Test Cases de Tarjetas Bancarias certificados PASSED en el Cuadro de Mando Jira Xray.",
    },
]

TARJETAS_BLOQUEADAS_LOG: List[Dict[str, Any]] = [
    {
        "operacionId": "BLK-GTN-2026-90411",
        "atmId": "ATM-GTN-MAD-0042",
        "ubicacion": "Sucursal Getnet Gran Vía 28, Madrid",
        "panEnmascarado": "4548 **** **** 9012",
        "motivo": "SOSPECHA_SKIMMING_RANURA (Detectado por Getnet ATM Sentinel)",
        "estado": "BLOQUEO_PREVENTIVO_CON_REVERSO_EMV_0420",
        "codigoReverso": "REV-EMV-2026-88412",
        "tokenDigitalReemplazo": "TOK-GTN-WALLET-9012",
        "cardEjected": True,
        "resolvedBy": "Self-Healing-Patch-Agent (Hotfix PATCH-GTN-ATM-0420)",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
]

AUTONOMOUS_ALM_STATE: Dict[str, Any] = {
    "mode": "ZERO_HUMAN_IN_THE_LOOP",
    "overallStatus": "HEALTHY · 2/2 INCIDENCIAS DE TARJETAS RESUELTAS Y REDESPLEGADAS EN PRO",
    "mttdSeconds": 0.8,
    "mttaSeconds": 1.2,
    "mttrSeconds": 5.8,
    "deployedRelease": "v2026.11.2-AUTONOMOUS-PRO",
    "lastCycleTimestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "stateMachineFlow": STATE_MACHINE_FLOW,
    "agentsRoster": AUTONOMOUS_AGENTS_ROSTER,
    "pipelineStages": [
        {
            "step": "1. DETECCIÓN EN PRO (GETNET ATM + DYNATRACE + CLOUDWATCH)",
            "actor": "Getnet-ATM-Vision-Agent + Observability-MCP-Agent",
            "status": "COMPLETED",
            "durationMs": 730,
            "detail": (
                "Detectada retención funcional de tarjeta bancaria en ATM-GTN-MAD-0042 (PAN 4548 **** **** 9012), "
                "problema Davis AI DT-PROB-2026-8841 en Dynatrace y alarma CW-ALARM-GTN-CARDLOCK-P99 en CloudWatch."
            ),
        },
        {
            "step": "2. CONSULTA MOTOR RAG & PROTECCIÓN PCI-DSS",
            "actor": "RAG-Knowledge-Architect-Agent + Getnet-ATM-Vision-Agent",
            "status": "COMPLETED",
            "durationMs": 700,
            "detail": (
                "PAN truncado bajo PCI-DSS 4.0 (redact_pan). El motor RAG recupera los playbooks "
                "RAG-PB-ATM-001 (Similitud 99%) y RAG-PB-SYS-002 (Similitud 99%)."
            ),
        },
        {
            "step": "3. ANÁLISIS CAUSA RAÍZ (RCA) VÍA MCP",
            "actor": "Observability-MCP-Agent + RAG-Knowledge-Architect-Agent",
            "status": "COMPLETED",
            "durationMs": 1220,
            "detail": (
                "RCA #1 (Getnet ATM): Flag enable_emv_reversal_0420=False en card_lock_engine omite reverso MTI 0420. "
                "RCA #2 (Sistemas): Mutex Redis en bloqueo de tarjetas con redis_lock_ttl_ms=0 agota HikariCP al 98.5%."
            ),
        },
        {
            "step": "4. RE-FIXING AUTÓNOMO (HOTFIX ZERO-TOUCH)",
            "actor": "Self-Healing-Patch-Agent",
            "status": "COMPLETED",
            "durationMs": 1340,
            "detail": (
                "Inyectados parches PATCH-GTN-ATM-0420 (enable_emv_reversal_0420=True + Token Wallet) y "
                "PATCH-GTN-SYS-REDIS (redis_lock_ttl_ms=3000 + Circuit Breaker Resilience4j)."
            ),
        },
        {
            "step": "5. RE-DEPLOY CANARY & QUALITY GATES TARJETAS",
            "actor": "QAOps-Xray-Certifier-Agent (Selenium MCP + JMeter IA)",
            "status": "COMPLETED",
            "durationMs": 1590,
            "detail": (
                "Desplegada release v2026.11.2-AUTONOMOUS-PRO. Certificados 14/14 casos funcionales y de estrés "
                "de tarjetas bancarias (GTN-TC-001 a GTN-TC-014 PASSED). Latencia P95 = 42.5ms."
            ),
        },
        {
            "step": "6. CIERRE EN CUADRO DE MANDO CIO JIRA XRAY",
            "actor": "QAOps-Xray-Certifier-Agent",
            "status": "COMPLETED",
            "durationMs": 240,
            "detail": (
                "Incidencias GTN-INC-ATM-001 y GTN-INC-SYS-002 cerradas automáticamente en estado "
                "RESOLVED (AUTO-REDEPLOYED) sin intervención humana."
            ),
        },
    ],
    "atmDetail": {
        "incidentKey": "GTN-INC-ATM-001",
        "atmId": "ATM-GTN-MAD-0042",
        "location": "Sucursal Getnet Gran Vía 28, Madrid",
        "engine": "Getnet_ATM (atm_sentinel.py + brand_verifier/incident.py)",
        "ragPlaybookId": "RAG-PB-ATM-001",
        "rawEvent": "Tarjeta bancaria Getnet 4548 1234 5678 9012 retenida en ranura tras bloqueo preventivo sin reverso EMV.",
        "panRedacted": "Tarjeta bancaria Getnet **** **** **** 9012 retenida en ranura tras bloqueo preventivo sin reverso EMV.",
        "scenePrompt": (
            "Cajero automatico de calle por la noche, plano medio realista, pantalla encendida mostrando el logotipo, "
            "sin personas identificables, sin texto legible y sin numeros. Contexto de la escena: Tarjeta bancaria Getnet "
            "retenida en ranura tras bloqueo preventivo sin reverso EMV."
        ),
        "triage": {
            "categoria": "TARJETA_RETENIDA",
            "severidad": "ALTA",
            "causa_probable": "Regresión en card_lock_engine: enable_emv_reversal_0420=False impide emitir reverso MTI 0420 y liberar obturador.",
            "accion_recomendada": "Activar reverso automático ISO-8583 0420, desbloquear eyección segura y emitir token digital en Wallet Getnet.",
        },
        "sentinelRisk": "CRITICO",
        "sentinelThreat": "CARD_TRAPPING",
        "confidence": 0.96,
        "framesAnalyzed": [
            {"frame": "frame_01_0.50s.jpg", "time_s": 0.5, "obs": "Inserción de tarjeta bancaria EMV en lector híbrido ATM-GTN-MAD-0042"},
            {"frame": "frame_03_4.20s.jpg", "time_s": 4.2, "obs": "Activación de bloqueo preventivo; tarjeta retenida en ranura"},
            {"frame": "frame_06_9.80s.jpg", "time_s": 9.8, "obs": "Hotfix aplicado: Reverso MTI 0420 emitido y plástico liberado"},
        ],
        "status": "RESOLVED (AUTO-REDEPLOYED)",
    },
    "cloudwatchSysDetail": {
        "incidentKey": "GTN-INC-SYS-002",
        "service": "getnet-card-blocker-svc (ECS Cluster prod-eu-west-1)",
        "alarmName": "CW-ALARM-GTN-CARDLOCK-P99",
        "dynatraceProblemId": "DT-PROB-2026-8841",
        "ragPlaybookId": "RAG-PB-SYS-002",
        "mcpServer": "getnet-observability-dynatrace-cloudwatch-atm-mcp v2.0.0",
        "logGroup": "/aws/ecs/getnet-card-blocker-svc",
        "errorSignature": "DeadlockDetectedException: Redis mutex lock on CARD_BLOCK_STATE acquired with lock_ttl_ms=0; HikariPool-1 connection timeout (3000ms)",
        "metricsBeforeFix": {
            "p95LatencyMs": 1840.0,
            "errorRatePct": 14.8,
            "hikariPoolUsagePct": 98.5,
            "redisMutexDeadlocks": 27,
            "alarmState": "ALARM",
            "dynatraceStatus": "OPEN (CRITICAL)",
        },
        "metricsAfterFix": {
            "p95LatencyMs": 42.5,
            "errorRatePct": 0.0,
            "hikariPoolUsagePct": 18.4,
            "redisMutexDeadlocks": 0,
            "alarmState": "OK",
            "dynatraceStatus": "CLOSED (RESOLVED)",
        },
        "hotfixCommit": "fix(card-blocker-svc): set redis_lock_ttl_ms=3000, enable circuit breaker & Redis rule cache",
        "status": "RESOLVED (AUTO-REDEPLOYED)",
    },
}
AUTONOMOUS_ALM_STATE["atmKiroDetail"] = AUTONOMOUS_ALM_STATE["atmDetail"]

# ---------------------------------------------------------------------------
# Catálogo de Servicios Exclusivos de Tarjetas Bancarias Getnet
# ---------------------------------------------------------------------------

SERVICIOS_TARJETAS_CATALOGO: List[Dict[str, Any]] = [
    {
        "id": "srv-parque-tarjetas",
        "codigo": "PARQUE_TARJETAS_EMV",
        "titulo": "Parque de Tarjetas Bancarias EMV y Red de Cajeros ATM",
        "descripcion": "Consulta e inventario en tiempo real de tarjetas Visa/Mastercard Débito, Crédito y Corporativas y nodos ATM monitorizados con Getnet ATM.",
        "icono": "💳",
        "sla_respuesta_ms": 150,
        "destacado": True,
        "tab_target": "tab-cuadro",
    },
    {
        "id": "srv-autorizaciones",
        "codigo": "AUTORIZACIONES_ISO8583",
        "titulo": "Autorización Online de Tarjetas ISO-8583 y 3D-Secure 2.2",
        "descripcion": "Emisión de autorizaciones MTI 0100/0110 para operaciones con tarjeta bancaria, ampliación de límite diario y control antifraude.",
        "icono": "🔐",
        "sla_respuesta_ms": 220,
        "destacado": True,
        "tab_target": "tab-autorizaciones",
    },
    {
        "id": "srv-disputas",
        "codigo": "DISPUTAS_CONTRACARGOS",
        "titulo": "Disputas, Contracargos (Chargebacks) y Fraude en Tarjetas",
        "descripcion": "Reclamación de cargos no reconocidos o efectivo no dispensado en cajero ATM con abono provisional inmediato de hasta el 90% en IBAN.",
        "icono": "🛡️",
        "sla_respuesta_ms": 240,
        "destacado": True,
        "tab_target": "tab-disputas",
    },
    {
        "id": "srv-wallet-titular",
        "codigo": "WALLET_TARJETA_DIGITAL",
        "titulo": "Área Titular y Tarjeta Bancaria Digital Tokenizada",
        "descripcion": "Consulta tus contratos de tarjeta bancaria, límites EMV y gestiona el token digital Apple Pay / Google Pay de reemplazo inmediato.",
        "icono": "📲",
        "sla_respuesta_ms": 180,
        "destacado": True,
        "tab_target": "tab-area-cliente",
    },
    {
        "id": "srv-soporte-tarjetas",
        "codigo": "SOPORTE_CRIPTO_HSM",
        "titulo": "Soporte Criptográfico EMV, PIN Block HSM y 3DS2 24h",
        "descripcion": "Asistencia técnica remota 24h con especialistas en criptografía EMV (ARQC/ARPC), desbloqueo de PIN y pasarela de tarjetas.",
        "icono": "🛠️",
        "sla_respuesta_ms": 200,
        "destacado": False,
        "tab_target": "tab-videoconsulta",
    },
    {
        "id": "srv-bloqueo-atm",
        "codigo": "BLOQUEO_TARJETA_ATM",
        "titulo": "Bloqueo Preventivo de Tarjetas en ATM (Getnet ATM + CloudWatch + Dynatrace)",
        "descripcion": "Simulador en vivo de retención de tarjeta bancaria en ranura ATM, reverso ISO-8583 MTI 0420 y auto-remediación ALM sin Human-in-the-Loop.",
        "icono": "🚨",
        "sla_respuesta_ms": 120,
        "destacado": True,
        "tab_target": "tab-bloqueo-atm",
    },
]

PARQUE_TARJETAS_DB: List[Dict[str, Any]] = [
    {
        "id": "GTN-TRJ-MAD-001",
        "nombre": "Nodo Emisor & Cajero ATM-GTN-MAD-0042 · Tarjeta Visa Corporate Infinite",
        "responsable": "Ing. Alejandro Vega Martín (Custodio EMV & ATM Sentinel)",
        "provincia": "Madrid",
        "tipo_tarjeta": "Visa Débito EMV",
        "servicio_getnet": "Emisión Instantánea, Bloqueo ATM & Reverso MTI 0420",
        "direccion": "Gran Vía 28, 28013 Madrid (BIN 454881 · Chip EMV DDA)",
        "telefono": "913 875 000",
        "programas": ["Getnet Corporate Premier", "Santander One Tarjetas", "Visa Infinite Business", "Red Euro6000 ATM"],
        "tokenizacion_activa": True,
        "guardia_24h": True,
        "comision": "0 € Emisión (Getnet Corporate Premier)",
    },
    {
        "id": "GTN-TRJ-MAD-002",
        "nombre": "Centro Autorizador Tarjetas Madrid Castellana · Visa & Mastercard EMV",
        "responsable": "Ing. Elena Soriano Ruiz (Especialista ISO-8583 & 3DS2)",
        "provincia": "Madrid",
        "tipo_tarjeta": "Visa Débito EMV",
        "servicio_getnet": "Autorizaciones MTI 0100 y Tokenización Wallet",
        "direccion": "Paseo de la Castellana 89, 28046 Madrid (BIN 454812)",
        "telefono": "915 643 210",
        "programas": ["Getnet Corporate Premier", "Santander One Tarjetas", "Mastercard Gold Corporate", "Red Euro6000 ATM"],
        "tokenizacion_activa": True,
        "guardia_24h": False,
        "comision": "0 € Mantenimiento Anual",
    },
    {
        "id": "GTN-TRJ-MAD-003",
        "nombre": "Unidad de Guardia 24h Bloqueo Preventivo de Tarjetas & Cajeros Madrid",
        "responsable": "Centro de Control 24h · Monitorización ATM Sentinel & Dynatrace Davis AI",
        "provincia": "Madrid",
        "tipo_tarjeta": "Guardia ATM 24h",
        "servicio_getnet": "Bloqueo Inmediato por Retención en Ranura y Reverso 0420",
        "direccion": "Avenida de Cantabria s/n (Ciudad Grupo Santander), 28660 Boadilla, Madrid",
        "telefono": "917 567 800",
        "programas": ["Getnet Corporate Premier", "Santander One Tarjetas", "Visa Infinite Business", "Red Euro6000 ATM"],
        "tokenizacion_activa": True,
        "guardia_24h": True,
        "comision": "SLA Reverso < 5 seg",
    },
    {
        "id": "GTN-TRJ-MAD-004",
        "nombre": "Hub de Tarjetas Prepago y Virtuales E-Commerce Madrid Goya",
        "responsable": "Ing. Javier Mendoza Ortiz (Arquitecto Tokenización PCI-DSS)",
        "provincia": "Madrid",
        "tipo_tarjeta": "Mastercard Prepago Tokenizada",
        "servicio_getnet": "Tarjetas Virtuales de Uso Único & Control de Límites",
        "direccion": "Calle de Goya 115, 28009 Madrid (BIN 541275)",
        "telefono": "900 229 922",
        "programas": ["Getnet Corporate Premier", "Mastercard Business Virtual", "Red Euro6000 ATM"],
        "tokenizacion_activa": True,
        "guardia_24h": False,
        "comision": "0 € Tokenización",
    },
    {
        "id": "GTN-TRJ-BCN-001",
        "nombre": "Hub Mediterráneo de Tarjetas Corporativas Barcelona Diagonal",
        "responsable": "Ing. Montserrat Puigvert Bosch (Responsable Criptografía HSM)",
        "provincia": "Barcelona",
        "tipo_tarjeta": "Mastercard Crédito Corporativa",
        "servicio_getnet": "Tarjetas Crédito Empresas & Liquidación EMV",
        "direccion": "Avinguda Diagonal 520, 08006 Barcelona (BIN 548910)",
        "telefono": "932 906 200",
        "programas": ["Getnet Corporate Premier", "Santander One Tarjetas", "Mastercard Gold Corporate"],
        "tokenizacion_activa": True,
        "guardia_24h": True,
        "comision": "0 € (Getnet Corporate)",
    },
    {
        "id": "GTN-TRJ-BCN-002",
        "nombre": "Centro de Respuesta 24h Incidencias de Tarjetas en Cajeros Barcelona",
        "responsable": "Unidad de Guardia 24h · Red ATM & Bloqueo Preventivo Cataluña",
        "provincia": "Barcelona",
        "tipo_tarjeta": "Guardia ATM 24h",
        "servicio_getnet": "Guardia 24h Retención de Tarjetas y Fraude Skimming",
        "direccion": "Passeig de Gràcia 54, 08007 Barcelona",
        "telefono": "932 554 000",
        "programas": ["Getnet Corporate Premier", "Santander One Tarjetas", "Red Euro6000 ATM"],
        "tokenizacion_activa": True,
        "guardia_24h": True,
        "comision": "0 €",
    },
    {
        "id": "GTN-TRJ-SEV-001",
        "nombre": "Centro Regional de Tarjetas Bancarias Andalucía - Sevilla",
        "responsable": "Ing. Manuel Domínguez Romero",
        "provincia": "Sevilla",
        "tipo_tarjeta": "Visa Platinum Contactless",
        "servicio_getnet": "Tarjetas Contactless EMV & Cajeros ATM Sur",
        "direccion": "Avenida de la Constitución 24, 41004 Sevilla (BIN 454890)",
        "telefono": "954 937 676",
        "programas": ["Getnet Corporate Premier", "Santander One Tarjetas", "Red Euro6000 ATM"],
        "tokenizacion_activa": True,
        "guardia_24h": True,
        "comision": "0 €",
    },
    {
        "id": "GTN-TRJ-VAL-001",
        "nombre": "Centro Operativo de Tarjetas y Disputas Levante - Valencia",
        "responsable": "Ing. Carmen Albornoz Gil",
        "provincia": "Valencia",
        "tipo_tarjeta": "Mastercard Crédito Corporativa",
        "servicio_getnet": "Gestión de Chargebacks Visa/Mastercard y Autorización 3DS2",
        "direccion": "Calle Pintor Sorolla 8, 46002 València (BIN 541299)",
        "telefono": "963 179 100",
        "programas": ["Getnet Corporate Premier", "Santander One Tarjetas", "Red Euro6000 ATM"],
        "tokenizacion_activa": True,
        "guardia_24h": True,
        "comision": "0 €",
    },
    {
        "id": "GTN-TRJ-BIL-001",
        "nombre": "Centro de Emisión y Seguridad de Tarjetas Zona Norte - Bilbao",
        "responsable": "Ing. Iñaki Etxebarria Goikoetxea",
        "provincia": "Bilbao",
        "tipo_tarjeta": "Visa Débito EMV",
        "servicio_getnet": "Cajeros ATM & Pasarela de Tarjetas ISO-8583",
        "direccion": "Gran Vía de Don Diego López de Haro 12, 48001 Bilbao",
        "telefono": "944 755 000",
        "programas": ["Getnet Corporate Premier", "Visa Infinite Business", "Red Euro6000 ATM"],
        "tokenizacion_activa": True,
        "guardia_24h": True,
        "comision": "0 €",
    },
]

TITULARES_TARJETAS_DB: Dict[str, Dict[str, Any]] = {
    "12345678Z": {
        "nif": "12345678Z",
        "passwords_validos": ["Getnet2026!"],
        "nombre": "Carlos Martínez Gómez",
        "contrato_tarjeta": "CTR-GTN-908122",
        "num_contrato": "CTR-GTN-908122",
        "num_tarjeta": "4548123456789012",
        "modalidad": "Getnet Corporate Premier · Visa Infinite EMV (Protección Fraude 90%)",
        "fecha_alta": "15/01/2022",
        "estado_tarjeta": "ACTIVA - TARJETA EMV & WALLET TOKENIZADO EN PRO",
        "copago_acumulado_anual": "0,00 € Comisión (Programa Getnet Corporate Premier)",
        "beneficiarios": [
            {"nombre": "Tarjeta Titular Principal · Visa Corporate EMV", "tarjeta": "4548123456789012"},
            {"nombre": "Tarjeta Digital Tokenizada (Apple Pay / Google Pay)", "tarjeta": "4548810099887766"},
        ],
    },
    "87654321X": {
        "nif": "87654321X",
        "passwords_validos": ["Getnet2026!"],
        "nombre": "Marta Sánchez Alcázar",
        "contrato_tarjeta": "CTR-GTN-774510",
        "num_contrato": "CTR-GTN-774510",
        "num_tarjeta": "5412751234567890",
        "modalidad": "Mastercard Gold Corporate · Red Santander / Euro6000",
        "fecha_alta": "01/02/2021",
        "estado_tarjeta": "ACTIVA - TARJETA CORPORATIVA VERIFICADA",
        "copago_acumulado_anual": "0,00 €",
        "beneficiarios": [
            {"nombre": "Marta Sánchez Alcázar (Mastercard Gold EMV)", "tarjeta": "5412751234567890"},
        ],
    },
}

AUTORIZACIONES_REGISTRADAS: List[Dict[str, Any]] = []
DISPUTAS_REGISTRADAS: List[Dict[str, Any]] = []
SOPORTE_SESIONES_REGISTRADAS: List[Dict[str, Any]] = []

JMETER_LATEST_REPORT: Dict[str, Any] = {
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "scenario": "Pico Transaccional de Tarjetas Bancarias Getnet & Bloqueo ATM (12 VUs / 60 muestras)",
    "totalSamples": 60,
    "throughputRps": 48.6,
    "avgResponseMs": 27.4,
    "p90Ms": 44.0,
    "p95Ms": 51.2,
    "p99Ms": 74.8,
    "errorRatePct": 0.0,
    "apdex": 1.0,
    "slaStatus": "PASSED",
    "aiInsights": [
        "Cumplimiento SLA Global Tarjetas Getnet: APROBADO (P95 = 51.2 ms frente al umbral SLA < 450.0 ms; Error Rate = 0.0%).",
        "Índice de satisfacción transaccional Apdex = 1.0 con caudal sostenido de 48.6 req/s tras aplicar Hotfix PATCH-GTN-SYS-REDIS.",
        "Certificación Post-Redeploy (GTN-INC-SYS-002): El mutex Redis con TTL=3000ms y Circuit Breaker eliminó los deadlocks en getnet-card-blocker-svc.",
    ],
    "endpoints": [
        {"label": "GET /api/v1/tarjetas/parque", "samples": 20, "avgMs": 12.4, "p95Ms": 22.0, "errorPct": 0.0},
        {"label": "POST /api/v1/tarjetas/bloqueo (Getnet ATM)", "samples": 16, "avgMs": 19.8, "p95Ms": 34.5, "errorPct": 0.0},
        {"label": "POST /api/v1/tarjetas/autorizaciones (ISO-8583)", "samples": 12, "avgMs": 48.2, "p95Ms": 61.0, "errorPct": 0.0},
        {"label": "POST /api/v1/tarjetas/disputas (Chargebacks)", "samples": 12, "avgMs": 15.1, "p95Ms": 25.8, "errorPct": 0.0},
    ],
}

SELENIUM_LATEST_REPORT: Dict[str, Any] = {
    "runId": "XRAY-EXEC-GTN-2026-105",
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "browser": "Google Chrome Headless 1440x950 (Selenium WebDriver 4.52)",
    "mcpServer": "getnet-selenium-qaops v2.0.0 + getnet-observability-dynatrace-cloudwatch-atm-mcp v2.0.0",
    "domLocatorsExtracted": 46,
    "domPruningSavingPct": 93.1,
    "selfHealingEventsCount": 0,
    "selfHealingStatus": "ACTIVE · 46/46 Selectores de Tarjetas Bancarias Verificados (0 Roturas)",
    "totalDurationMs": 5740,
    "passed": 12,
    "failed": 0,
    "total": 12,
    "screenshotUrl": "/api/v1/qaops/screenshot/mcp_selftest_servicios_clientes.png",
    "mcpToolRuns": [
        {
            "tool": "getnet_atm_inspect_incident (Getnet_ATM)",
            "target": "ATM-GTN-MAD-0042 · PAN 4548 **** **** 9012",
            "durationMs": 115,
            "status": "PASSED",
            "output": "Triaje TARJETA_RETENIDA (CRITICO) + PAN Redacted PCI-DSS + Hotfix EMV 0420",
        },
        {
            "tool": "dynatrace_get_davis_problems + cloudwatch_get_alarms",
            "target": "DT-PROB-2026-8841 & CW-ALARM-GTN-CARDLOCK-P99",
            "durationMs": 92,
            "status": "PASSED",
            "output": "Deadlock Redis resuelto (TTL=3000ms) · Dynatrace CLOSED & CloudWatch OK",
        },
        {
            "tool": "rag_retrieve_incident_playbook (Motor RAG)",
            "target": "rag-knowledge-base/incident_knowledge_base.json",
            "durationMs": 38,
            "status": "PASSED",
            "output": "Playbooks RAG-PB-ATM-001 (99%) y RAG-PB-SYS-002 (99%) sintetizados",
        },
        {
            "tool": "selenium_start_session & inspect_dom_locators",
            "target": "http://127.0.0.1:8080/servicios-para-clientes",
            "durationMs": 620,
            "status": "PASSED",
            "output": "46 selectores de tarjetas extraídos (-93.1% ahorro de tokens vía DOM Pruning)",
        },
        {
            "tool": "selenium_execute_tarjetas_flow (parque_tarjetas, bloqueo_atm & autorizacion)",
            "target": "Provincia=Madrid, Tarjeta=4548123456789012",
            "durationMs": 710,
            "status": "PASSED",
            "output": "Parque de tarjetas verificado + Reverso 0420 + Código AUT-2026 generado",
        },
        {
            "tool": "alm_sync_test_result",
            "target": "POST /api/v1/qaops/test-runs (Jira Xray / TestLink / Redmine)",
            "durationMs": 40,
            "status": "PASSED",
            "output": "14/14 casos de tarjetas bancarias sincronizados en Jira Xray",
        },
    ],
    "testCasesDetail": [
        {
            "key": "GTN-TC-001",
            "testLinkId": "TL-GTN-101",
            "name": "test_tc001_catalogo_servicios_tarjetas_bancarias",
            "locatorPrimary": "#hero-title / #catalogo-servicios-grid .service-card",
            "locatorFallback": "[data-testid='hero-title'] / [data-testid^='service-card-']",
            "assertion": "6 módulos de operativa de tarjetas bancarias Getnet renderizados",
            "durationMs": 540,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-002",
            "testLinkId": "TL-GTN-102",
            "name": "test_tc002_busqueda_parque_tarjetas_madrid_visa_emv",
            "locatorPrimary": "#cm-provincia + #trj-tipo + #btn-buscar-cuadro",
            "locatorFallback": "[data-testid='select-provincia'] + [data-testid='btn-buscar-cuadro']",
            "assertion": ">= 2 nodos emisores de tarjetas Visa Débito EMV en Madrid",
            "durationMs": 490,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-003",
            "testLinkId": "TL-GTN-103",
            "name": "test_tc003_busqueda_guardia_24h_red_euro6000",
            "locatorPrimary": "#trj-tipo + #trj-programa + #btn-buscar-cuadro",
            "locatorFallback": "[data-testid='select-programa-tarjeta'] -> Guardia ATM 24h",
            "assertion": ">= 2 centros de bloqueo preventivo de tarjetas 24h operativos",
            "durationMs": 480,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-004",
            "testLinkId": "TL-GTN-104",
            "name": "test_tc004_autorizacion_tarjeta_iso8583_exitosa",
            "locatorPrimary": "#aut-tarjeta + #aut-tipo-acto + #btn-solicitar-autorizacion",
            "locatorFallback": "[data-testid='input-aut-tarjeta'] + [data-testid='aut-resultado-alert']",
            "assertion": "Estado == AUTORIZADA y código ISO-8583 AUT-2026-XXXXX generado",
            "durationMs": 550,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-005",
            "testLinkId": "TL-GTN-105",
            "name": "test_tc005_autorizacion_pan_tarjeta_invalido",
            "locatorPrimary": "#aut-tarjeta (valor '12345') + #aut-resultado-alert",
            "locatorFallback": "[data-testid='aut-resultado-alert']",
            "assertion": "Rechazo HTTP 400 + Alerta PAN entre 12 y 16 dígitos numéricos",
            "durationMs": 440,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-006",
            "testLinkId": "TL-GTN-106",
            "name": "test_tc006_autorizacion_tarjeta_auditoria_antifraude",
            "locatorPrimary": "POST /api/v1/tarjetas/autorizaciones (Auditoría Antifraude > 15.000 EUR)",
            "locatorFallback": "Contrato SDD RN-AUT-02",
            "assertion": "Estado == PENDIENTE_REVISION_RIESGOS (Control Antifraude Tarjetas)",
            "durationMs": 92,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-007",
            "testLinkId": "TL-GTN-107",
            "name": "test_tc007_disputa_chargeback_tarjeta_abono_90",
            "locatorPrimary": "#rmb-nif + #rmb-modalidad + #rmb-importe + #rmb-iban",
            "locatorFallback": "[data-testid='rmb-importe-abonado']",
            "assertion": "Expediente DSP-2026-XXXXX y abono provisional 225.00 EUR (90% de 250 EUR)",
            "durationMs": 590,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-008",
            "testLinkId": "TL-GTN-108",
            "name": "test_tc008_disputa_chargeback_iban_invalido",
            "locatorPrimary": "#rmb-iban (valor 'ES1234') + #rmb-resultado-alert",
            "locatorFallback": "[data-testid='rmb-resultado-alert']",
            "assertion": "Rechazo HTTP 400 + Alerta formato IBAN ES + 22 dígitos",
            "durationMs": 450,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-009",
            "testLinkId": "TL-GTN-109",
            "name": "test_tc009_login_titular_wallet_tarjeta_digital",
            "locatorPrimary": "#login-nif + #login-password + #btn-login-cliente",
            "locatorFallback": "[data-testid='tarjeta-digital-getnet']",
            "assertion": "Titular Carlos Martínez Gómez + Contrato CTR-GTN-908122 + Tarjeta Tokenizada",
            "durationMs": 530,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-010",
            "testLinkId": "TL-GTN-110",
            "name": "test_tc010_soporte_criptografico_emv_hsm_24h",
            "locatorPrimary": "#sop-unidad + #vc-motivo + #btn-reservar-vc",
            "locatorFallback": "[data-testid='vc-codigo-cita']",
            "assertion": "Sesión HSM/EMV confirmada SOP-2026-XXXXX",
            "durationMs": 510,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-013",
            "testLinkId": "TL-GTN-113",
            "name": "test_tc013_incidencia_funcional_tarjeta_getnet_atm_autofix",
            "locatorPrimary": "POST /api/v1/tarjetas/bloqueo + Getnet_ATM (ATM-GTN-MAD-0042)",
            "locatorFallback": "#btn-ejecutar-bloqueo-atm / [data-testid='atm-bloqueo-alert']",
            "assertion": "Detección + PAN Masking + Auto-Fix EMV 0420 + GTN-INC-ATM-001 RESOLVED",
            "durationMs": 140,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-014",
            "testLinkId": "TL-GTN-114",
            "name": "test_tc014_incidencia_sistemas_dynatrace_cloudwatch_mcp_autofix",
            "locatorPrimary": "GET /api/v1/observability/status + POST /api/v1/alm/autonomous-cycle",
            "locatorFallback": "MCP Server getnet-observability-dynatrace-cloudwatch-atm-mcp",
            "assertion": "Dynatrace CLOSED + CloudWatch OK + Redis TTL=3000ms + GTN-INC-SYS-002 RESOLVED",
            "durationMs": 155,
            "status": "PASSED",
        },
    ],
}

EXECUTION_HISTORY: List[Dict[str, Any]] = [
    {
        "execKey": "GTN-EXEC-2026-105",
        "buildName": "Build #105 · Ciclo Autónomo ALM Zero-Touch (Getnet ATM + Dynatrace + CloudWatch MCP + Motor RAG)",
        "runner": "5 Agentes Autónomos ALM + Motor RAG + Dynatrace/CloudWatch MCP",
        "environment": "Production Simulation (Zero Human-in-the-Loop)",
        "testsScope": "GTN-INC-ATM-001 + GTN-INC-SYS-002 -> RAG Playbooks -> Auto-Fix & Re-Deploy (GTN-TC-001..014)",
        "passed": 14,
        "failed": 0,
        "durationMs": 5820,
        "status": "PASSED",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    },
    {
        "execKey": "GTN-EXEC-2026-104",
        "buildName": "Build #104 · Suite Pytest + Selenium POM (12 Casos Funcionales de Tarjetas Bancarias)",
        "runner": "Pytest + Selenium WebDriver (Chrome Headless)",
        "environment": "Local Simulation (127.0.0.1:8080)",
        "testsScope": "GTN-TC-001 .. GTN-TC-010, GTN-TC-013, GTN-TC-014 (12 tests tarjetas)",
        "passed": 12,
        "failed": 0,
        "durationMs": 5740,
        "status": "PASSED",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    },
    {
        "execKey": "GTN-EXEC-2026-103",
        "buildName": "Build #103 · Diagnóstico Servidores MCP (Dynatrace + CloudWatch + Selenium + RAG)",
        "runner": "Observability-MCP-Agent + RAG-Knowledge-Architect-Agent",
        "environment": "Local Simulation (127.0.0.1:8080)",
        "testsScope": "DOM Pruning (46 locators) + Dynatrace Davis AI + CloudWatch Alarms + Getnet ATM",
        "passed": 6,
        "failed": 0,
        "durationMs": 1720,
        "status": "PASSED",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    },
    {
        "execKey": "GTN-EXEC-2026-102",
        "buildName": "Build #102 · Performance Gate JMeter IA de Tarjetas Bancarias",
        "runner": "JMeter AI Assistant (ai_jmeter_assistant.py)",
        "environment": "Local Simulation (12 VUs / 60 muestras)",
        "testsScope": "GTN-TC-011 .. GTN-TC-012 (P95 = 51.2ms, Apdex = 1.0)",
        "passed": 2,
        "failed": 0,
        "durationMs": 1380,
        "status": "PASSED",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    },
]


def load_alm_backlog() -> Dict[str, Any]:
    if ALM_JSON_PATH.exists():
        with open(ALM_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "project": {},
        "epics": [],
        "userStories": [],
        "testPlan": {},
        "testCases": [],
        "productionIncidents": [],
        "defects": [],
    }


def save_alm_backlog(data: Dict[str, Any]) -> None:
    ALM_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ALM_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Rutas Vistas HTML (Portal Tarjetas Getnet + Cuadro de Mando CIO Jira Xray)
# ---------------------------------------------------------------------------


@app.route("/")
def root_redirect():
    return redirect("/alm-dashboard")


@app.route("/getnet-portal")
def getnet_portal_redirect():
    return redirect("/servicios-para-clientes")


@app.route("/servicios-para-clientes")
def servicios_para_clientes_view():
    return render_template(
        "servicios_clientes.html",
        servicios=SERVICIOS_TARJETAS_CATALOGO,
        parque_inicial=PARQUE_TARJETAS_DB,
        system_state=SYSTEM_INCIDENT_STATE,
        tarjetas_log=TARJETAS_BLOQUEADAS_LOG,
        mcp_connections=MCP_CONNECTIONS_STATE,
    )


@app.route("/alm-dashboard")
def alm_dashboard_view():
    alm_data = load_alm_backlog()
    return render_template(
        "alm_dashboard.html",
        alm=alm_data,
        jmeter=JMETER_LATEST_REPORT,
        selenium=SELENIUM_LATEST_REPORT,
        executions=EXECUTION_HISTORY,
        autonomous=AUTONOMOUS_ALM_STATE,
        system_state=SYSTEM_INCIDENT_STATE,
        mcp_connections=MCP_CONNECTIONS_STATE,
        state_machine=STATE_MACHINE_FLOW,
        agents_roster=AUTONOMOUS_AGENTS_ROSTER,
        rag_playbooks=RAG_ENGINE.playbooks,
        rag_meta=RAG_ENGINE.kb_data.get("metadata", {}),
    )


@app.route("/presentacion")
def presentacion_ejecutiva_view():
    pres_html = PROJECT_ROOT / "presentacion" / "index.html"
    if pres_html.exists():
        return send_file(pres_html)
    return redirect("/alm-dashboard")


# ---------------------------------------------------------------------------
# Endpoints API REST (/api/v1/*) — Operativa de Tarjetas Bancarias Getnet
# ---------------------------------------------------------------------------


@app.route("/api/v1/health", methods=["GET"])
def api_health():
    degraded = SYSTEM_INCIDENT_STATE["atm_functional_bug_active"] or SYSTEM_INCIDENT_STATE["systems_cloudwatch_bug_active"]
    return jsonify(
        {
            "status": "DEGRADED_INCIDENT_ACTIVE" if degraded else "UP",
            "service": "getnet-autonomous-alm-card-core-sim",
            "client": "Getnet (Grupo Santander)",
            "domain": "Tarjetas Bancarias (Emisión EMV, Bloqueo ATM, ISO-8583, 3DS2, Chargebacks)",
            "qaopsProvider": "Ayesa Digital",
            "almMode": "ZERO_HUMAN_IN_THE_LOOP",
            "currentRelease": SYSTEM_INCIDENT_STATE["currentRelease"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "incidentFlags": {
                "atmFunctionalBugActive": SYSTEM_INCIDENT_STATE["atm_functional_bug_active"],
                "systemsCloudwatchBugActive": SYSTEM_INCIDENT_STATE["systems_cloudwatch_bug_active"],
            },
            "mcpConnections": {k: v["status"] for k, v in MCP_CONNECTIONS_STATE.items()},
            "stats": {
                "nodosParqueTarjetas": len(PARQUE_TARJETAS_DB),
                "autorizacionesTramitadas": len(AUTORIZACIONES_REGISTRADAS),
                "disputasTramitadas": len(DISPUTAS_REGISTRADAS),
                "tarjetasBloqueadas": len(TARJETAS_BLOQUEADAS_LOG),
                "sesionesSoporteHsm": len(SOPORTE_SESIONES_REGISTRADAS),
            },
        }
    )


@app.route("/api/v1/servicios", methods=["GET"])
def api_servicios():
    return jsonify({"total": len(SERVICIOS_TARJETAS_CATALOGO), "servicios": SERVICIOS_TARJETAS_CATALOGO})


@app.route("/api/v1/tarjetas/parque", methods=["GET"])
@app.route("/api/v1/red-tarjetas", methods=["GET"])
def api_parque_tarjetas():
    provincia = request.args.get("provincia", "").strip()
    tipo_tarjeta = (
        request.args.get("tipoTarjeta", "").strip()
        or request.args.get("redTarjeta", "").strip()
        or request.args.get("modalidad", "").strip()
    )
    programa = request.args.get("programa", "").strip()
    q = request.args.get("q", "").strip().lower()
    guardia = request.args.get("guardia24h", "").strip().lower()

    resultados = []
    for item in PARQUE_TARJETAS_DB:
        if provincia and provincia != "Todas" and item["provincia"].lower() != provincia.lower():
            continue
        if tipo_tarjeta and tipo_tarjeta != "Todas":
            tt_low = tipo_tarjeta.lower()
            if tt_low != item["tipo_tarjeta"].lower() and tt_low not in item.get("servicio_getnet", "").lower():
                continue
        if programa and programa != "Todas":
            if not any(programa.lower() in p.lower() for p in item["programas"]):
                continue
        if guardia in ("true", "1", "si") and not item["guardia_24h"]:
            continue
        if q:
            texto = (
                f"{item['nombre']} {item['responsable']} {item['direccion']} "
                f"{item['tipo_tarjeta']} {item.get('servicio_getnet', '')}"
            ).lower()
            if q not in texto:
                continue
        resultados.append(item)

    return jsonify(
        {
            "filtros": {
                "provincia": provincia or "Todas",
                "tipoTarjeta": tipo_tarjeta or "Todas",
                "programa": programa or "Todas",
                "q": q,
            },
            "total": len(resultados),
            "resultados": resultados,
        }
    )


@app.route("/api/v1/tarjetas/autorizaciones", methods=["POST"])
@app.route("/api/v1/autorizaciones", methods=["POST"])
def api_crear_autorizacion():
    payload = request.get_json(silent=True) or {}
    num_tarjeta = str(payload.get("numTarjeta", "")).strip().replace(" ", "")
    tipo_operacion = str(payload.get("tipoOperacion") or payload.get("tipoActo") or "").strip()
    cod_referencia = str(payload.get("codigoReferencia") or payload.get("codigoPrescripcion") or "").strip()
    nodo_atm_comercio = str(payload.get("nodoAtmComercio") or payload.get("centroMedico") or "").strip()
    observaciones = str(payload.get("observaciones", "")).strip()

    if not re.fullmatch(r"\d{12,16}", num_tarjeta):
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "INVALID_CARD_NUMBER",
                    "mensaje": "El PAN de la Tarjeta Bancaria Getnet debe contener entre 12 y 16 dígitos numéricos (ej. 4548123456789012).",
                }
            ),
            400,
        )

    if not tipo_operacion or not cod_referencia or not nodo_atm_comercio:
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "MISSING_REQUIRED_FIELDS",
                    "mensaje": "Todos los campos obligatorios de la tarjeta (Tipo de operación EMV, Código de comercio/ATM y Nodo adquirente) deben completarse.",
                }
            ),
            400,
        )

    es_revision_riesgos = (
        "antifraude" in tipo_operacion.lower()
        or "internacional" in tipo_operacion.lower()
        or "15.000" in tipo_operacion.lower()
        or "riesgo" in tipo_operacion.lower()
    )
    if es_revision_riesgos:
        time.sleep(0.04)
        estado = "PENDIENTE_REVISION_RIESGOS"
        mensaje = "Su operación con tarjeta bancaria requiere validación por la Unidad de Riesgos Emisor & Antifraude Getnet (SLA máximo 24h)."
    else:
        estado = "AUTORIZADA"
        mensaje = "Autorización ISO-8583 (MTI 0110 · RC 00) concedida automáticamente por el motor de tarjetas Getnet."

    codigo_aut = f"AUT-2026-{random.randint(10000, 99999)}"
    registro = {
        "codigoAutorizacion": codigo_aut,
        "numTarjeta": atm_sentinel.mask_card_numbers(num_tarjeta),
        "tipoOperacion": tipo_operacion,
        "codigoReferencia": cod_referencia,
        "nodoAtmComercio": nodo_atm_comercio,
        "observaciones": observaciones,
        "estado": estado,
        "mensaje": mensaje,
        "fechaSolicitud": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    AUTORIZACIONES_REGISTRADAS.append(registro)
    return jsonify({"ok": True, "autorizacion": registro}), 201


@app.route("/api/v1/tarjetas/disputas", methods=["POST"])
@app.route("/api/v1/disputas", methods=["POST"])
def api_crear_disputa_tarjeta():
    payload = request.get_json(silent=True) or {}
    nif = str(payload.get("nif", "")).strip().upper()
    programa_tarjeta = str(payload.get("programaTarjeta") or payload.get("programaTarjeta") or "Getnet Corporate Premier (90%)").strip()
    concepto = str(payload.get("conceptoCargo") or payload.get("conceptoFactura") or "Disputa / Chargeback Tarjeta Bancaria").strip()
    iban = str(payload.get("iban", "")).strip().upper().replace(" ", "")

    try:
        importe = float(payload.get("importeCargo") if "importeCargo" in payload else payload.get("importeFactura", 0))
    except (TypeError, ValueError):
        importe = -1.0

    if not re.fullmatch(r"[0-9XYZ]\d{7}[A-Z]", nif):
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "INVALID_NIF",
                    "mensaje": "El NIF/NIE/CIF del titular de la tarjeta no tiene un formato válido (ej. 12345678Z).",
                }
            ),
            400,
        )

    if importe <= 0 or importe > 15000:
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "INVALID_AMOUNT",
                    "mensaje": "El importe del contracargo (chargeback) en tarjeta debe ser mayor que 0,00 € y no superar 15.000,00 €.",
                }
            ),
            400,
        )

    if not re.fullmatch(r"ES\d{22}", iban):
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "INVALID_IBAN",
                    "mensaje": "El código IBAN de abono de la disputa debe comenzar por ES seguido de 22 dígitos numéricos.",
                }
            ),
            400,
        )

    porcentaje = 0.90 if "premier" in programa_tarjeta.lower() or "90" in programa_tarjeta else 0.80
    importe_abonado = round(importe * porcentaje, 2)
    expediente = f"DSP-2026-{random.randint(10000, 99999)}"

    registro = {
        "expediente": expediente,
        "nif": nif,
        "programaTarjeta": programa_tarjeta,
        "conceptoCargo": concepto,
        "importeCargo": round(importe, 2),
        "porcentajeAbonoProvisional": int(porcentaje * 100),
        "importeAbonoProvisional": importe_abonado,
        "ibanAbono": f"{iban[:4]} **** **** **** {iban[-4:]}",
        "estado": "EN_TRAMITACION_CHARGEBACK",
        "plazoEstimadoDias": 1,
        "fechaRegistro": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    DISPUTAS_REGISTRADAS.append(registro)
    return jsonify({"ok": True, "disputa": registro, "disputa": registro}), 201


@app.route("/api/v1/auth/login", methods=["POST"])
def api_login_titular():
    payload = request.get_json(silent=True) or {}
    nif = str(payload.get("nif", "")).strip().upper()
    password = str(payload.get("password", "")).strip()

    titular = TITULARES_TARJETAS_DB.get(nif)
    if not titular or password not in titular["passwords_validos"]:
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "AUTH_INVALID_CREDENTIALS",
                    "mensaje": "NIF/NIE o clave de acceso incorrectos. Para pruebas QAOps de tarjetas utilice 12345678Z / Getnet2026!.",
                }
            ),
            401,
        )

    perfil_publico = {k: v for k, v in titular.items() if k != "passwords_validos"}
    return jsonify({"ok": True, "cliente": perfil_publico})


@app.route("/api/v1/tarjetas/soporte", methods=["POST"])
@app.route("/api/v1/citas", methods=["POST"])
def api_crear_sesion_soporte():
    payload = request.get_json(silent=True) or {}
    area_tecnica = str(payload.get("areaTecnica") or payload.get("unidadTecnica") or "Criptografía EMV & HSM").strip()
    canal = str(payload.get("canalSoporte") or payload.get("modalidadCita") or "Consola Remota HSM / WebRTC").strip()
    motivo = str(payload.get("motivoSoporte") or payload.get("motivoConsulta") or "").strip()
    telefono = str(payload.get("telefonoContacto", "600123456")).strip()

    if not motivo:
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "MISSING_REASON",
                    "mensaje": "Por favor indique el motivo técnico de la incidencia de tarjeta bancaria o cajero ATM.",
                }
            ),
            400,
        )

    codigo_sesion = f"SOP-2026-{random.randint(10000, 99999)}"
    sesion = {
        "codigoCita": codigo_sesion,
        "areaTecnica": area_tecnica,
        "canalSoporte": canal,
        "motivoConsulta": motivo,
        "telefonoContacto": telefono,
        "especialistaAsignado": "Ing. Patricia Navarro Solís (Especialista Guardia 24h Criptografía EMV & HSM Nº 28/49102)",
        "facultativoAsignado": "Ing. Patricia Navarro Solís (Especialista Guardia 24h Criptografía EMV & HSM Nº 28/49102)",
        "salaVirtualUrl": f"https://soporte-tarjetas.getnet.eu/sala/{codigo_sesion}",
        "estado": "CONFIRMADA",
    }
    SOPORTE_SESIONES_REGISTRADAS.append(sesion)
    return jsonify({"ok": True, "cita": sesion, "sesion": sesion}), 201


# ---------------------------------------------------------------------------
# Aplicativo de Sistema de Bloqueo de Tarjetas ATM (Getnet_ATM)
# ---------------------------------------------------------------------------


@app.route("/api/v1/tarjetas/estado", methods=["GET"])
def api_tarjetas_estado():
    return jsonify(
        {
            "ok": True,
            "systemState": SYSTEM_INCIDENT_STATE,
            "tarjetasBloqueadas": TARJETAS_BLOQUEADAS_LOG,
        }
    )


@app.route("/api/v1/tarjetas/bloqueo", methods=["POST"])
def api_bloqueo_tarjeta_atm():
    payload = request.get_json(silent=True) or {}
    raw_pan = str(payload.get("numTarjeta", "4548 1234 5678 9012")).strip()
    clean_digits = re.sub(r"\D", "", raw_pan)
    atm_id = str(payload.get("atmId", "ATM-GTN-MAD-0042")).strip() or "ATM-GTN-MAD-0042"
    ubicacion = str(payload.get("ubicacion", "Sucursal Getnet Gran Vía 28, Madrid")).strip()
    motivo = str(payload.get("motivoBloqueo", "SOSPECHA_SKIMMING_RANURA")).strip()

    if not 12 <= len(clean_digits) <= 19:
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "INVALID_PAN_FORMAT",
                    "mensaje": "El PAN de la tarjeta bancaria debe contener entre 12 y 19 dígitos para procesar el bloqueo ATM.",
                }
            ),
            400,
        )

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    raw_desc = f"Evento en {atm_id} ({ubicacion}): Solicitud de bloqueo por {motivo} para la tarjeta bancaria {raw_pan}."
    inc_obj = {
        "atm_id": atm_id,
        "ubicacion": ubicacion,
        "descripcion": raw_desc,
        "fecha_hora": now_iso,
    }
    atm_errors = validate_incident(inc_obj)
    masked_desc = redact_pan(raw_desc)
    masked_pan = atm_sentinel.mask_card_numbers(raw_pan)
    safe_prompt = scene_prompt(inc_obj)

    if SYSTEM_INCIDENT_STATE["atm_functional_bug_active"] or not SYSTEM_INCIDENT_STATE["enable_emv_reversal_0420"]:
        failed_entry = {
            "operacionId": f"BLK-ERR-{random.randint(10000, 99999)}",
            "atmId": atm_id,
            "ubicacion": ubicacion,
            "panEnmascarado": masked_pan,
            "motivo": motivo,
            "estado": "ERROR_TARJETA_RETENIDA_SIN_REVERSO",
            "codigoReverso": None,
            "tokenDigitalReemplazo": None,
            "cardEjected": False,
            "atmValidationErrors": atm_errors,
            "atmMaskedDescription": masked_desc,
            "resolvedBy": "PENDIENTE_AUTO_REMEDIACION_ALM",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        TARJETAS_BLOQUEADAS_LOG.insert(0, failed_entry)
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "ATM_CARD_TRAPPED_NO_EMV_0420_REVERSAL",
                    "incidentKey": "GTN-INC-ATM-001",
                    "mensaje": (
                        f"INCIDENCIA FUNCIONAL EN PRODUCCIÓN ({atm_id}): La tarjeta bancaria {masked_pan} ha quedado "
                        "bloqueada y retenida en el obturador sin emitir reverso ISO-8583 MTI 0420 "
                        "(enable_emv_reversal_0420=False). Requiere remediación autónoma ALM."
                    ),
                    "operacion": failed_entry,
                }
            ),
            409,
        )

    cod_reverso = f"REV-EMV-2026-{random.randint(10000, 99999)}"
    token_digital = f"TOK-GTN-WALLET-{clean_digits[-4:]}-{random.randint(100, 999)}"
    success_entry = {
        "operacionId": f"BLK-GTN-2026-{random.randint(10000, 99999)}",
        "atmId": atm_id,
        "ubicacion": ubicacion,
        "panEnmascarado": masked_pan,
        "motivo": motivo,
        "estado": "BLOQUEO_PREVENTIVO_CON_REVERSO_EMV_0420",
        "codigoReverso": cod_reverso,
        "tokenDigitalReemplazo": token_digital,
        "cardEjected": True,
        "atmValidationErrors": atm_errors,
        "atmMaskedDescription": masked_desc,
        "atmScenePrompt": safe_prompt,
        "resolvedBy": "Self-Healing-Patch-Agent (Hotfix PATCH-GTN-ATM-0420 Activo)",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    TARJETAS_BLOQUEADAS_LOG.insert(0, success_entry)
    return (
        jsonify(
            {
                "ok": True,
                "mensaje": (
                    f"Bloqueo preventivo de tarjeta completado con éxito en {atm_id}. Reverso ISO-8583 MTI 0420 "
                    f"({cod_reverso}) emitido, tarjeta liberada y token digital ({token_digital}) aprovisionado."
                ),
                "operacion": success_entry,
            }
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Observabilidad Híbrida (Dynatrace + AWS CloudWatch + Prometheus + RAG)
# ---------------------------------------------------------------------------


@app.route("/api/v1/observability/status", methods=["GET"])
def api_observability_status():
    sys_bug = SYSTEM_INCIDENT_STATE["systems_cloudwatch_bug_active"]
    atm_bug = SYSTEM_INCIDENT_STATE["atm_functional_bug_active"]

    dt_problems = [
        {
            "problemId": "DT-PROB-2026-8841",
            "title": "Response time degradation & Redis Mutex Deadlock on getnet-card-blocker-svc",
            "status": "OPEN" if sys_bug else "CLOSED",
            "severityLevel": "PERFORMANCE / AVAILABILITY (P0)",
            "impactedEntity": "SERVICE-GETNET-CARD-BLOCKER",
            "rootCauseEntity": "PROCESS_GROUP-REDIS-CARD-MUTEX (redis_lock_ttl_ms=0)",
            "p95LatencyMs": 1840.0 if sys_bug else 42.5,
            "hikariPoolPct": 98.5 if sys_bug else 18.4,
            "linkedIncident": "GTN-INC-SYS-002",
            "ragPlaybook": "RAG-PB-SYS-002",
        },
        {
            "problemId": "DT-PROB-2026-8845",
            "title": "Custom Device ATM-GTN-MAD-0042 Card Reader Retention without MTI 0420 Reversal",
            "status": "OPEN" if atm_bug else "CLOSED",
            "severityLevel": "CUSTOM_ALERT / FUNCTIONAL (P1)",
            "impactedEntity": "CUSTOM_DEVICE-ATM-MAD-0042",
            "rootCauseEntity": "card_lock_engine (enable_emv_reversal_0420=False)",
            "retainedCards": 3 if atm_bug else 0,
            "linkedIncident": "GTN-INC-ATM-001",
            "ragPlaybook": "RAG-PB-ATM-001",
        },
    ]

    dt_traces = [
        {
            "traceId": "dt-trace-9941a8c02b",
            "endpoint": "POST /api/v1/tarjetas/bloqueo",
            "service": "getnet-card-blocker-svc",
            "durationMs": 1840.0 if sys_bug else 34.2,
            "httpStatus": 503 if sys_bug else 201,
            "redisLockTtlMs": 0 if sys_bug else 3000,
            "emvReversal0420": "OMITTED_ERROR" if atm_bug else "EMITTED_OK",
        },
        {
            "traceId": "dt-trace-7720f1d44e",
            "endpoint": "POST /api/v1/tarjetas/autorizaciones",
            "service": "getnet-iso8583-auth-svc",
            "durationMs": 41.8,
            "httpStatus": 201,
            "redisLockTtlMs": 3000,
            "emvReversal0420": "N/A (MTI 0110 RC 00)",
        },
    ]

    cw_alarms = [
        {
            "alarmName": "CW-ALARM-GTN-CARDLOCK-P99",
            "namespace": "AWS/GetnetCardCore",
            "metric": "CardBlockLatencyP95",
            "threshold": "450 ms",
            "currentValue": "1840.0 ms" if sys_bug else "42.5 ms",
            "state": "ALARM" if sys_bug else "OK",
            "severity": "CRITICAL (P0)",
            "linkedIncident": "GTN-INC-SYS-002",
        },
        {
            "alarmName": "CW-ALARM-GTN-RDS-HIKARIPOOL",
            "namespace": "AWS/RDS",
            "metric": "DatabaseConnectionPoolUtilization",
            "threshold": "85.0 %",
            "currentValue": "98.5 %" if sys_bug else "18.4 %",
            "state": "ALARM" if sys_bug else "OK",
            "severity": "HIGH (P1)",
            "linkedIncident": "GTN-INC-SYS-002",
        },
        {
            "alarmName": "CW-ALARM-GTN-ATM-SENTINEL-TRAP",
            "namespace": "AWS/GetnetATMSentinel",
            "metric": "AtmCardRetentionWithoutReversalCount",
            "threshold": "0 events",
            "currentValue": "3 events (ATM-GTN-MAD-0042)" if atm_bug else "0 events",
            "state": "ALARM" if atm_bug else "OK",
            "severity": "CRITICAL (P1)",
            "linkedIncident": "GTN-INC-ATM-001",
        },
    ]

    cw_logs = (
        [
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "FATAL",
                "service": "getnet-card-blocker-svc",
                "message": "DeadlockDetectedException: Redis mutex lock on table CARD_BLOCK_STATE acquired with lock_ttl_ms=0; HikariPool-1 connection timeout after 3000ms",
            },
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "ERROR",
                "service": "getnet-atm-sentinel-edge",
                "message": "ATM-GTN-MAD-0042: Card 4548 **** **** 9012 trapped in reader slot; enable_emv_reversal_0420=False prevented MTI 0420 dispatch",
            },
        ]
        if (sys_bug or atm_bug)
        else [
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "INFO",
                "service": "getnet-card-blocker-svc",
                "message": "Hotfix PATCH-GTN-SYS-REDIS active: redis_lock_ttl_ms=3000, circuit_breaker=CLOSED, HikariPool active=4/32 (18.4%), P95=42.5ms",
            },
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "INFO",
                "service": "getnet-atm-sentinel-edge",
                "message": "Hotfix PATCH-GTN-ATM-0420 active: ATM-GTN-MAD-0042 EMV reversal 0420 enabled, PAN redaction PCI-DSS compliant, 0 trapped cards",
            },
        ]
    )

    prom_metrics = {
        "getnet_card_block_latency_p95_ms": 1840.0 if sys_bug else 42.5,
        "getnet_redis_mutex_deadlocks_total": 27 if sys_bug else 0,
        "getnet_db_hikaricp_utilization_pct": 98.5 if sys_bug else 18.4,
        "getnet_atm_retained_cards_total": 3 if atm_bug else 0,
        "getnet_iso8583_0420_reversals_success_rate": 0.0 if atm_bug else 100.0,
        "getnet_autonomous_alm_mttr_seconds": AUTONOMOUS_ALM_STATE["mttrSeconds"],
    }

    return jsonify(
        {
            "ok": True,
            "systemState": SYSTEM_INCIDENT_STATE,
            "mcpConnections": MCP_CONNECTIONS_STATE,
            "dynatrace": {
                "environmentUrl": MCP_CONNECTIONS_STATE["dynatrace"]["endpointUrl"],
                "connectionStatus": MCP_CONNECTIONS_STATE["dynatrace"]["status"],
                "monitoredEntities": MCP_CONNECTIONS_STATE["dynatrace"]["monitoredEntities"],
                "davisRootCause": (
                    "Redis Mutex Lock TTL=0 causing HikariCP exhaustion on getnet-card-blocker-svc"
                    if sys_bug
                    else "All monitored banking card services healthy (0 Davis problems open)"
                ),
                "problems": dt_problems,
                "purePathTraces": dt_traces,
                "smartscapeTopology": [
                    {"from": "CUSTOM_DEVICE-ATM-MAD-0042", "to": "SERVICE-GETNET-CARD-BLOCKER", "protocol": "ISO-8583 / HTTPS"},
                    {"from": "SERVICE-GETNET-CARD-BLOCKER", "to": "PROCESS_GROUP-REDIS-CARD-MUTEX", "protocol": "RESP (Redis Lock)"},
                    {"from": "SERVICE-GETNET-CARD-BLOCKER", "to": "SERVICE-GETNET-ISO8583-AUTH", "protocol": "gRPC / ISO-8583 MTI 0420"},
                ],
            },
            "cloudwatch": {
                "region": "eu-west-1",
                "logGroups": ["/aws/ecs/getnet-card-blocker-svc", "/aws/lambda/getnet-atm-sentinel-edge"],
                "alarms": cw_alarms,
                "recentLogs": cw_logs,
            },
            "prometheus": {
                "status": "FIRING_ALERTS" if (sys_bug or atm_bug) else "HEALTHY",
                "activeAlerts": (
                    ["RedisMutexDeadlockHigh", "HikariPoolExhaustionCritical", "AtmCardRetentionFunctionalFailure"]
                    if (sys_bug or atm_bug)
                    else []
                ),
                "metrics": prom_metrics,
            },
            "autonomousAlm": AUTONOMOUS_ALM_STATE,
        }
    )


@app.route("/api/v1/observability/prometheus", methods=["GET"])
def api_prometheus_text():
    sys_bug = SYSTEM_INCIDENT_STATE["systems_cloudwatch_bug_active"]
    atm_bug = SYSTEM_INCIDENT_STATE["atm_functional_bug_active"]
    lines = [
        "# HELP getnet_card_block_latency_p95_ms Percentil 95 de latencia en el servicio de bloqueo de tarjetas Getnet",
        "# TYPE getnet_card_block_latency_p95_ms gauge",
        f'getnet_card_block_latency_p95_ms{{service="getnet-card-blocker-svc",env="prod"}} {1840.0 if sys_bug else 42.5}',
        "# HELP getnet_redis_mutex_deadlocks_total Total de deadlocks detectados en locks distribuidos Redis",
        "# TYPE getnet_redis_mutex_deadlocks_total counter",
        f'getnet_redis_mutex_deadlocks_total{{service="getnet-card-blocker-svc",env="prod"}} {27 if sys_bug else 0}',
        "# HELP getnet_db_hikaricp_utilization_pct Porcentaje de uso del pool de conexiones HikariCP",
        "# TYPE getnet_db_hikaricp_utilization_pct gauge",
        f'getnet_db_hikaricp_utilization_pct{{service="getnet-card-blocker-svc",env="prod"}} {98.5 if sys_bug else 18.4}',
        "# HELP getnet_atm_retained_cards_total Tarjetas bancarias retenidas sin reverso EMV en cajeros ATM",
        "# TYPE getnet_atm_retained_cards_total gauge",
        f'getnet_atm_retained_cards_total{{atm_id="ATM-GTN-MAD-0042",env="prod"}} {3 if atm_bug else 0}',
    ]
    return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")


# ---------------------------------------------------------------------------
# Ventanas Interactivas de Conexión MCP Server (Dynatrace & AWS CloudWatch)
# ---------------------------------------------------------------------------


@app.route("/api/v1/mcp/connect", methods=["POST"])
def api_mcp_connect_and_test():
    """
    Endpoint para las ventanas modales de conexión MCP Server (Dynatrace, AWS CloudWatch, Prometheus y Getnet ATM).
    Actualiza parámetros de conexión, simula el handshake JSON-RPC 2.0 y devuelve telemetría en vivo.
    """
    payload = request.get_json(silent=True) or {}
    provider = str(payload.get("provider", "dynatrace")).strip().lower()
    if provider == "kiro_atm":
        provider = "getnet_atm"
    custom_url = str(payload.get("endpointUrl", "")).strip()
    custom_query = str(payload.get("query", "")).strip()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if provider in MCP_CONNECTIONS_STATE:
        if custom_url:
            MCP_CONNECTIONS_STATE[provider]["endpointUrl"] = custom_url
        MCP_CONNECTIONS_STATE[provider]["status"] = "CONNECTED"
        MCP_CONNECTIONS_STATE[provider]["lastSync"] = now_str

    obs_resp = api_observability_status().get_json()

    if provider == "dynatrace":
        tool_name = "dynatrace_get_davis_problems"
        tool_args = {
            "dql_query": custom_query
            or "fetch spans | filter dt.entity.service == 'SERVICE-GETNET-CARD-BLOCKER' | summarize p95=percentile(duration, 95)",
        }
        result_payload = obs_resp.get("dynatrace", {})
    elif provider == "cloudwatch":
        tool_name = "cloudwatch_get_alarms"
        tool_args = {
            "log_group": payload.get("logGroup", "/aws/ecs/getnet-card-blocker-svc"),
            "insights_query": custom_query
            or "fields @timestamp, @message | filter level in ['ERROR', 'FATAL'] | sort @timestamp desc | limit 20",
        }
        result_payload = obs_resp.get("cloudwatch", {})
    elif provider == "prometheus":
        tool_name = "prometheus_query_metrics"
        tool_args = {"query": custom_query or "getnet_card_block_latency_p95_ms"}
        result_payload = obs_resp.get("prometheus", {})
    else:
        tool_name = "getnet_atm_inspect_incident"
        tool_args = {"atm_id": "ATM-GTN-MAD-0042"}
        result_payload = AUTONOMOUS_ALM_STATE.get("atmDetail", {})

    jsonrpc_trace = {
        "request": {
            "jsonrpc": "2.0",
            "id": random.randint(1000, 9999),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": tool_args},
        },
        "response": {
            "jsonrpc": "2.0",
            "result": {
                "serverInfo": MCP_CONNECTIONS_STATE.get(provider, {}),
                "telemetryPayload": result_payload,
            },
        },
    }
    return jsonify(
        {
            "ok": True,
            "provider": provider,
            "connection": MCP_CONNECTIONS_STATE.get(provider, {}),
            "jsonrpc": jsonrpc_trace,
        }
    )


# ---------------------------------------------------------------------------
# Endpoints del Motor RAG y Base de Conocimiento de Incidencias Bancarias
# ---------------------------------------------------------------------------


@app.route("/api/v1/rag/playbooks", methods=["GET"])
def api_rag_list_playbooks():
    return jsonify(
        {
            "ok": True,
            "metadata": RAG_ENGINE.kb_data.get("metadata", {}),
            "playbooks": RAG_ENGINE.playbooks,
        }
    )


@app.route("/api/v1/rag/query", methods=["POST"])
def api_rag_query():
    payload = request.get_json(silent=True) or {}
    query = str(
        payload.get("query", "Tarjeta retenida en cajero ATM sin reverso ISO-8583 MTI 0420 y deadlock Redis")
    ).strip()
    telemetry_source = payload.get("telemetrySource")
    top_k = int(payload.get("topK", 3))
    result = RAG_ENGINE.retrieve(query=query, telemetry_source=telemetry_source, top_k=top_k)
    return jsonify({"ok": True, "ragResult": result})


@app.route("/api/v1/alm/agents-state", methods=["GET"])
def api_alm_agents_state():
    return jsonify(
        {
            "ok": True,
            "stateMachineFlow": STATE_MACHINE_FLOW,
            "agentsRoster": AUTONOMOUS_AGENTS_ROSTER,
            "mcpConnections": MCP_CONNECTIONS_STATE,
        }
    )


# ---------------------------------------------------------------------------
# Inyección de Fallos y Ciclo Completo ALM Autónomo (Zero Human-in-the-Loop)
# ---------------------------------------------------------------------------


@app.route("/api/v1/alm/inject-incidents", methods=["POST"])
def api_inject_incidents():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    SYSTEM_INCIDENT_STATE.update(
        {
            "currentRelease": "v2026.11.1-BROKEN-PRO",
            "atm_functional_bug_active": True,
            "systems_cloudwatch_bug_active": True,
            "enable_emv_reversal_0420": False,
            "redis_lock_ttl_ms": 0,
            "circuit_breaker_enabled": False,
        }
    )

    for st in STATE_MACHINE_FLOW:
        st["status"] = "ACTIVE_IN_PROGRESS" if st["order"] <= 3 else "PENDING_TRIGGER"

    AUTONOMOUS_ALM_STATE["overallStatus"] = "ALERTA CRÍTICA EN PRO · 2 INCIDENCIAS DE TARJETAS ACTIVAS (PENDIENTE AUTO-REMEDIACIÓN)"
    AUTONOMOUS_ALM_STATE["deployedRelease"] = "v2026.11.1-BROKEN-PRO"
    AUTONOMOUS_ALM_STATE["atmDetail"]["status"] = "OPEN · DETECTED IN ATM-GTN-MAD-0042"
    AUTONOMOUS_ALM_STATE["cloudwatchSysDetail"]["status"] = "ALARM · FIRING IN DYNATRACE DAVIS AI & AWS CLOUDWATCH"

    alm_data = load_alm_backlog()
    for inc in alm_data.get("productionIncidents", []):
        inc["status"] = "OPEN · CRITICAL IN PRO (AWAITING AUTO-FIX)"
    for bug in alm_data.get("defects", []):
        bug["status"] = "Open (Critical in PRO)"
    for tc in alm_data.get("testCases", []):
        if tc.get("key") in ("GTN-TC-013", "GTN-TC-014"):
            tc["status"] = "FAILED"
    save_alm_backlog(alm_data)

    for stc in SELENIUM_LATEST_REPORT.get("testCasesDetail", []):
        if stc.get("key") in ("GTN-TC-013", "GTN-TC-014"):
            stc["status"] = "FAILED"
    SELENIUM_LATEST_REPORT["passed"] = 10
    SELENIUM_LATEST_REPORT["failed"] = 2

    EXECUTION_HISTORY.insert(
        0,
        {
            "execKey": f"GTN-ALERT-2026-{100 + len(EXECUTION_HISTORY) + 1}",
            "buildName": "🔥 INCIDENCIAS DE TARJETAS DETECTADAS (Getnet ATM + Dynatrace Davis AI + CloudWatch)",
            "runner": "Getnet-ATM-Vision-Agent + Observability-MCP-Agent",
            "environment": "PRODUCTION (eu-west-1)",
            "testsScope": "GTN-INC-ATM-001 (Card Trapped) + GTN-INC-SYS-002 (Redis Deadlock P95=1840ms)",
            "passed": 10,
            "failed": 2,
            "durationMs": 410,
            "status": "FAILED",
            "timestamp": now_str,
        },
    )

    return jsonify(
        {
            "ok": True,
            "message": "Incidencias funcional (Getnet ATM) y de sistemas (Dynatrace/CloudWatch) inyectadas en Producción.",
            "systemState": SYSTEM_INCIDENT_STATE,
            "autonomousAlm": AUTONOMOUS_ALM_STATE,
        }
    )


@app.route("/api/v1/alm/autonomous-cycle", methods=["POST"])
def api_autonomous_alm_cycle():
    t0 = time.perf_counter()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    raw_incident = {
        "atm_id": "ATM-GTN-MAD-0042",
        "ubicacion": "Sucursal Getnet Gran Vía 28, Madrid",
        "descripcion": (
            "Fallo funcional en cajero ATM-GTN-MAD-0042: La tarjeta bancaria Getnet 4548 1234 5678 9012 del titular "
            "Sr. Carlos Martínez quedó retenida en estado ERROR_TARJETA_RETENIDA_SIN_REVERSO."
        ),
        "fecha_hora": now_iso,
    }
    atm_val_errors = validate_incident(raw_incident)
    pan_masked = redact_pan(raw_incident["descripcion"])
    safe_scene = scene_prompt(raw_incident)
    triage_obj = {
        "categoria": "TARJETA_RETENIDA",
        "severidad": "ALTA",
        "causa_probable": "Regresión en card_lock_engine: enable_emv_reversal_0420=False impide emitir reverso MTI 0420 y liberar obturador.",
        "accion_recomendada": "Activar reverso automático ISO-8583 0420, desbloquear eyección segura y emitir token digital en Wallet Getnet.",
    }
    triage_errors = validate_triage(triage_obj)

    rag_atm = RAG_ENGINE.retrieve("Tarjeta retenida en ranura cajero ATM sin reverso ISO-8583 MTI 0420")
    rag_sys = RAG_ENGINE.retrieve("Dynatrace Davis AI y CloudWatch deadlock Redis TTL 0 saturación HikariCP")

    SYSTEM_INCIDENT_STATE.update(
        {
            "currentRelease": "v2026.11.2-AUTONOMOUS-PRO",
            "atm_functional_bug_active": False,
            "systems_cloudwatch_bug_active": False,
            "enable_emv_reversal_0420": True,
            "auto_issue_digital_token": True,
            "redis_lock_ttl_ms": 3000,
            "circuit_breaker_enabled": True,
            "redis_cache_enabled": True,
            "lastAutonomousRun": now_str,
            "autonomousCyclesCount": SYSTEM_INCIDENT_STATE.get("autonomousCyclesCount", 1) + 1,
        }
    )

    for st in STATE_MACHINE_FLOW:
        st["status"] = "COMPLETED"

    cod_rev = f"REV-EMV-2026-{random.randint(10000, 99999)}"
    TARJETAS_BLOQUEADAS_LOG.insert(
        0,
        {
            "operacionId": f"BLK-AUTOFIX-{random.randint(10000, 99999)}",
            "atmId": "ATM-GTN-MAD-0042",
            "ubicacion": "Sucursal Getnet Gran Vía 28, Madrid",
            "panEnmascarado": "4548 **** **** 9012",
            "motivo": "AUTO_REMEDIACION_ALM_ZERO_TOUCH",
            "estado": "BLOQUEO_PREVENTIVO_CON_REVERSO_EMV_0420",
            "codigoReverso": cod_rev,
            "tokenDigitalReemplazo": "TOK-GTN-WALLET-9012",
            "cardEjected": True,
            "resolvedBy": "Ciclo ALM Sin Human-in-the-Loop (RAG-PB-ATM-001 + RAG-PB-SYS-002)",
            "timestamp": now_str,
        },
    )

    alm_data = load_alm_backlog()
    alm_data["project"]["version"] = "2026.11.2-AUTONOMOUS-PRO"
    for inc in alm_data.get("productionIncidents", []):
        inc["status"] = "RESOLVED (AUTO-REDEPLOYED)"
        inc["resolvedAt"] = now_iso
    for bug in alm_data.get("defects", []):
        bug["status"] = "Resolved (Auto-Fixed)"
    for tc in alm_data.get("testCases", []):
        tc["status"] = "PASSED"
    save_alm_backlog(alm_data)

    for stc in SELENIUM_LATEST_REPORT.get("testCasesDetail", []):
        stc["status"] = "PASSED"
    SELENIUM_LATEST_REPORT["passed"] = len(SELENIUM_LATEST_REPORT.get("testCasesDetail", []))
    SELENIUM_LATEST_REPORT["failed"] = 0
    SELENIUM_LATEST_REPORT["timestamp"] = now_str

    AUTONOMOUS_ALM_STATE.update(
        {
            "overallStatus": "HEALTHY · 2/2 INCIDENCIAS DE TARJETAS RESUELTAS Y REDESPLEGADAS EN PRO",
            "deployedRelease": "v2026.11.2-AUTONOMOUS-PRO",
            "lastCycleTimestamp": now_str,
        }
    )
    AUTONOMOUS_ALM_STATE["atmDetail"].update(
        {
            "panRedacted": pan_masked,
            "scenePrompt": safe_scene,
            "triage": triage_obj,
            "status": "RESOLVED (AUTO-REDEPLOYED)",
        }
    )
    AUTONOMOUS_ALM_STATE["cloudwatchSysDetail"]["status"] = "RESOLVED (AUTO-REDEPLOYED)"

    elapsed_ms = max(int((time.perf_counter() - t0) * 1000), 140)
    EXECUTION_HISTORY.insert(
        0,
        {
            "execKey": f"GTN-EXEC-2026-{100 + len(EXECUTION_HISTORY) + 1}",
            "buildName": f"Build #{100 + len(EXECUTION_HISTORY) + 1} · Ciclo Completo ALM Zero-Touch (RAG + Auto-Fix & Re-Deploy PRO)",
            "runner": "5 Agentes Autónomos (Getnet ATM + Dynatrace + CloudWatch MCP + Motor RAG + Jira Xray)",
            "environment": "PRODUCTION (v2026.11.2-AUTONOMOUS-PRO)",
            "testsScope": "GTN-INC-ATM-001 & GTN-INC-SYS-002 RESOLVED · 14/14 Xray Card Tests PASSED",
            "passed": 14,
            "failed": 0,
            "durationMs": elapsed_ms,
            "status": "PASSED",
            "timestamp": now_str,
        },
    )

    return jsonify(
        {
            "ok": True,
            "status": "RESOLVED_AND_REDEPLOYED",
            "atmIncidentKey": "GTN-INC-ATM-001",
            "atmIncidentStatus": "RESOLVED (AUTO-REDEPLOYED)",
            "sysIncidentKey": "GTN-INC-SYS-002",
            "sysIncidentStatus": "RESOLVED (AUTO-REDEPLOYED)",
            "ragPlaybooksApplied": [
                rag_atm["agenticSynthesis"]["selectedPlaybookId"],
                rag_sys["agenticSynthesis"]["selectedPlaybookId"],
            ],
            "atmValidationOk": len(atm_val_errors) == 0 and len(triage_errors) == 0,
            "panRedacted": pan_masked,
            "emvReversalCode": cod_rev,
            "deployedRelease": "v2026.11.2-AUTONOMOUS-PRO",
            "elapsedMs": elapsed_ms,
            "autonomousAlm": AUTONOMOUS_ALM_STATE,
        }
    )


# ---------------------------------------------------------------------------
# Endpoints ALM & QAOps Telemetry (Jira Xray / TestLink / Redmine / JMeter AI)
# ---------------------------------------------------------------------------


@app.route("/api/v1/alm/backlog", methods=["GET"])
def api_alm_backlog():
    data = load_alm_backlog()
    return jsonify(
        {
            "ok": True,
            "backlog": data,
            "seleniumReport": SELENIUM_LATEST_REPORT,
            "jmeterReport": JMETER_LATEST_REPORT,
            "executions": EXECUTION_HISTORY,
            "autonomousAlm": AUTONOMOUS_ALM_STATE,
            "systemState": SYSTEM_INCIDENT_STATE,
            "mcpConnections": MCP_CONNECTIONS_STATE,
            "stateMachineFlow": STATE_MACHINE_FLOW,
            "agentsRoster": AUTONOMOUS_AGENTS_ROSTER,
        }
    )


@app.route("/api/v1/qaops/test-runs", methods=["POST"])
def api_update_test_runs():
    payload = request.get_json(silent=True) or {}
    results = payload.get("results", [])
    if isinstance(payload, dict) and "key" in payload and not results:
        results = [payload]

    alm_data = load_alm_backlog()
    updated_keys = []
    total_ms = 0
    passed_cnt = 0
    failed_cnt = 0

    for res in results:
        tc_key = str(res.get("key", "")).strip()
        new_status = res.get("status", "PASSED").upper()
        duration_ms = res.get("durationMs")
        if new_status == "PASSED":
            passed_cnt += 1
        else:
            failed_cnt += 1
        if duration_ms is not None:
            total_ms += int(duration_ms)

        for tc in alm_data.get("testCases", []):
            if tc.get("key") == tc_key or tc.get("testLinkId") == tc_key:
                tc["status"] = new_status
                if duration_ms is not None:
                    tc["lastExecutionTimeMs"] = int(duration_ms)
                updated_keys.append(tc["key"])

        for s_tc in SELENIUM_LATEST_REPORT.get("testCasesDetail", []):
            if s_tc.get("key") == tc_key or s_tc.get("testLinkId") == tc_key:
                s_tc["status"] = new_status
                if duration_ms is not None:
                    s_tc["durationMs"] = int(duration_ms)

    if updated_keys:
        save_alm_backlog(alm_data)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        SELENIUM_LATEST_REPORT["timestamp"] = now_str
        if len(results) >= 5:
            SELENIUM_LATEST_REPORT["totalDurationMs"] = total_ms
            SELENIUM_LATEST_REPORT["passed"] = passed_cnt
            SELENIUM_LATEST_REPORT["failed"] = failed_cnt
            SELENIUM_LATEST_REPORT["total"] = passed_cnt + failed_cnt

        EXECUTION_HISTORY.insert(
            0,
            {
                "execKey": f"GTN-EXEC-2026-{100 + len(EXECUTION_HISTORY) + 1}",
                "buildName": (
                    f"Build #{100 + len(EXECUTION_HISTORY) + 1} · "
                    + (
                        "Suite Pytest + Selenium POM (E2E Tarjetas Getnet)"
                        if len(results) >= 5
                        else f"Sincronización Xray ({', '.join(updated_keys)})"
                    )
                ),
                "runner": payload.get("runner", "Pytest + Selenium WebDriver / MCP Agent"),
                "environment": "Local Simulation (127.0.0.1:8080)",
                "testsScope": f"{len(updated_keys)} caso(s): {', '.join(updated_keys[:4])}{'...' if len(updated_keys) > 4 else ''}",
                "passed": passed_cnt,
                "failed": failed_cnt,
                "durationMs": total_ms or 550,
                "status": "PASSED" if failed_cnt == 0 else "FAILED",
                "timestamp": now_str,
            },
        )

    return jsonify({"ok": True, "updatedTestCases": updated_keys, "totalUpdated": len(updated_keys)})


@app.route("/api/v1/qaops/jmeter-report", methods=["POST"])
def api_update_jmeter_report():
    global JMETER_LATEST_REPORT
    payload = request.get_json(silent=True) or {}
    if payload:
        JMETER_LATEST_REPORT.update(payload)
        EXECUTION_HISTORY.insert(
            0,
            {
                "execKey": f"GTN-EXEC-2026-{100 + len(EXECUTION_HISTORY) + 1}",
                "buildName": f"Build #{100 + len(EXECUTION_HISTORY) + 1} · Performance Gate JMeter IA (Tarjetas Getnet)",
                "runner": "JMeter AI Assistant (ai_jmeter_assistant.py)",
                "environment": f"Local Simulation ({JMETER_LATEST_REPORT.get('totalSamples', 60)} muestras)",
                "testsScope": f"GTN-TC-011..012 (P95 = {JMETER_LATEST_REPORT.get('p95Ms')}ms, Apdex = {JMETER_LATEST_REPORT.get('apdex')})",
                "passed": 2 if JMETER_LATEST_REPORT.get("slaStatus") == "PASSED" else 0,
                "failed": 0 if JMETER_LATEST_REPORT.get("slaStatus") == "PASSED" else 2,
                "durationMs": int(float(JMETER_LATEST_REPORT.get("p99Ms", 120)) * 12),
                "status": JMETER_LATEST_REPORT.get("slaStatus", "PASSED"),
                "timestamp": JMETER_LATEST_REPORT.get("timestamp"),
            },
        )
    return jsonify({"ok": True, "jmeterReport": JMETER_LATEST_REPORT})


@app.route("/api/v1/qaops/screenshot/<filename>", methods=["GET"])
def api_get_screenshot(filename: str):
    safe_name = Path(filename).name
    img_path = PROJECT_ROOT / "selenium-qaops" / "reports" / safe_name
    if img_path.exists():
        return send_file(img_path, mimetype="image/png")
    return jsonify({"ok": False, "error": "Screenshot no encontrado"}), 404


@app.route("/api/v1/qaops/trigger-selenium", methods=["POST"])
def api_trigger_selenium():
    t0 = time.perf_counter()
    rc_mcp = subprocess.call(
        [sys.executable, str(PROJECT_ROOT / "mcp-selenium-server" / "server.py"), "--selftest"],
        cwd=str(PROJECT_ROOT),
    )
    rc_pytest = subprocess.call(
        [sys.executable, "-m", "pytest", "selenium-qaops/tests/test_servicios_clientes_e2e.py", "-q"],
        cwd=str(PROJECT_ROOT),
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return jsonify(
        {
            "ok": rc_mcp == 0 and rc_pytest == 0,
            "mcpExitCode": rc_mcp,
            "pytestExitCode": rc_pytest,
            "totalElapsedMs": elapsed_ms,
            "seleniumReport": SELENIUM_LATEST_REPORT,
        }
    )


@app.route("/api/v1/qaops/trigger-observability-mcp", methods=["POST"])
def api_trigger_observability_mcp():
    t0 = time.perf_counter()
    rc_obs = subprocess.call(
        [sys.executable, str(PROJECT_ROOT / "mcp-observability-server" / "server.py"), "--selftest"],
        cwd=str(PROJECT_ROOT),
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return jsonify(
        {
            "ok": rc_obs == 0,
            "exitCode": rc_obs,
            "totalElapsedMs": elapsed_ms,
            "autonomousAlm": AUTONOMOUS_ALM_STATE,
        }
    )


@app.route("/api/v1/qaops/trigger-jmeter", methods=["POST"])
def api_trigger_jmeter():
    t0 = time.perf_counter()
    rc_jm = subprocess.call(
        [sys.executable, str(PROJECT_ROOT / "jmeter-ai" / "ai_jmeter_assistant.py"), "--vus", "12", "--iterations", "5"],
        cwd=str(PROJECT_ROOT),
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return jsonify(
        {
            "ok": rc_jm == 0,
            "exitCode": rc_jm,
            "totalElapsedMs": elapsed_ms,
            "jmeterReport": JMETER_LATEST_REPORT,
        }
    )


@app.route("/api/v1/alm/export/<fmt>", methods=["GET"])
def api_export_alm(fmt: str):
    fmt = fmt.lower()
    if fmt == "jira-xray":
        return send_file(ALM_JSON_PATH, as_attachment=True, download_name="getnet_backlog_xray_export.json")
    if fmt == "testlink":
        return send_file(TESTLINK_XML_PATH, as_attachment=True, download_name="getnet_tarjetas_testplan_testlink.xml")
    if fmt == "redmine":
        return send_file(REDMINE_CSV_PATH, as_attachment=True, download_name="getnet_redmine_issues_backlog.csv")
    return jsonify({"ok": False, "error": "Formato no soportado. Use jira-xray, testlink o redmine."}), 404


if __name__ == "__main__":
    port = int(os.environ.get("GETNET_PORT", "8080"))
    app.run(host="127.0.0.1", port=port, debug=False)
