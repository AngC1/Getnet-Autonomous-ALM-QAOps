"""
Simulador del Portal Getnet (Grupo Santander) — Servicios para Clientes, Comercios y Red ATM (/servicios-para-clientes)
+ Aplicativo de Bloqueo de Tarjetas e Incidencias ATM (AWS_Kiro-main)
+ Monitor de Sistemas AWS CloudWatch & OpenSource Prometheus MCP
+ Hub ALM Autónomo en Producción Sin Human-in-the-Loop (Jira Xray / TestLink / Redmine / Selenium MCP / JMeter IA).
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
TESTLINK_XML_PATH = PROJECT_ROOT / "alm-backlog" / "testlink" / "segurcaixa_testplan_testlink.xml"
REDMINE_CSV_PATH = PROJECT_ROOT / "alm-backlog" / "redmine" / "redmine_issues_backlog.csv"

KIRO_DIR = PROJECT_ROOT / "AWS_Kiro-main" / "AWS_Kiro-main"
if str(KIRO_DIR) not in sys.path:
    sys.path.insert(0, str(KIRO_DIR))

from brand_verifier.incident import (  # noqa: E402
    redact_pan,
    scene_prompt,
    validate_incident,
    validate_triage,
)
import atm_sentinel  # noqa: E402

app = Flask(__name__, template_folder="templates", static_folder="static")

# ---------------------------------------------------------------------------
# Estado en Vivo del Sistema de Bloqueo de Tarjetas y Ciclo ALM Autónomo (PRO)
# ---------------------------------------------------------------------------

SYSTEM_INCIDENT_STATE: Dict[str, Any] = {
    "environment": "PRODUCTION (eu-west-1 · Zero Human-in-the-Loop)",
    "currentRelease": "v2026.11.2-AUTONOMOUS-PRO",
    "atm_functional_bug_active": False,
    "systems_cloudwatch_bug_active": False,
    "enable_emv_reversal_0420": True,
    "auto_issue_digital_token": True,
    "redis_lock_ttl_ms": 1500,
    "circuit_breaker_enabled": True,
    "redis_cache_enabled": True,
    "lastAutonomousRun": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "autonomousCyclesCount": 3,
}

TARJETAS_BLOQUEADAS_LOG: List[Dict[str, Any]] = [
    {
        "operacionId": "BLK-GTN-2026-90411",
        "atmId": "ATM-GTN-MAD-0042",
        "ubicacion": "Sucursal Getnet Gran Vía 28, Madrid",
        "panEnmascarado": "4548 **** **** 9012",
        "motivo": "SOSPECHA_SKIMMING_RANURA (Detectado por AWS_Kiro ATM Sentinel)",
        "estado": "BLOQUEO_PREVENTIVO_CON_REVERSO_EMV_0420",
        "codigoReverso": "REV-EMV-2026-88412",
        "tokenDigitalReemplazo": "TOK-GTN-WALLET-9012",
        "cardEjected": True,
        "resolvedBy": "Agente Autónomo ALM (Hotfix PATCH-GTN-ATM-0420)",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
]

AUTONOMOUS_ALM_STATE: Dict[str, Any] = {
    "mode": "ZERO_HUMAN_IN_THE_LOOP",
    "overallStatus": "HEALTHY · 2/2 INCIDENCIAS RESUELTAS Y REDESPLEGADAS EN PRO",
    "mttdSeconds": 0.8,
    "mttaSeconds": 1.4,
    "mttrSeconds": 6.9,
    "deployedRelease": "v2026.11.2-AUTONOMOUS-PRO",
    "lastCycleTimestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "pipelineStages": [
        {
            "step": "1. DETECCIÓN EN PRO",
            "actor": "AWS_Kiro ATM Sentinel + AWS CloudWatch / Prometheus MCP",
            "status": "COMPLETED",
            "durationMs": 820,
            "detail": (
                "Detectada retención funcional de tarjeta en ATM-GTN-MAD-0042 (PAN 4548 **** **** 9012) "
                "y alarma crítica CW-ALARM-GTN-CARDLOCK-P99 (P95 = 1840ms, HikariCP = 98.5%)."
            ),
        },
        {
            "step": "2. TRIAGE COGNITIVO & PCI-DSS",
            "actor": "Agente de Triaje Kiro + Jira Xray Connector",
            "status": "COMPLETED",
            "durationMs": 1150,
            "detail": (
                "PAN redactado automáticamente (redact_pan). Creados tickets críticos en Jira Xray: "
                "GTN-INC-ATM-001 (TARJETA_RETENIDA / ALTA) y GTN-INC-SYS-002 (DEADLOCK_REDIS / BLOCKER)."
            ),
        },
        {
            "step": "3. ANÁLISIS CAUSA RAÍZ (RCA)",
            "actor": "Agente SRE & Code AST Analyzer via MCP",
            "status": "COMPLETED",
            "durationMs": 1420,
            "detail": (
                "RCA #1 (ATM): Flag enable_emv_reversal_0420=False en card_lock_engine impide expulsión y reverso 0420. "
                "RCA #2 (Sistemas): Lock Redis en tabla CARD_BLOCK_STATE con lock_ttl_ms=0 satura pool HikariCP."
            ),
        },
        {
            "step": "4. RE-FIXING AUTÓNOMO (HOTFIX)",
            "actor": "Agente de Ingeniería Autónoma (Zero-Touch Patch)",
            "status": "COMPLETED",
            "durationMs": 1640,
            "detail": (
                "Aplicados parches PATCH-GTN-ATM-0420 (enable_emv_reversal_0420=True + Token Wallet) y "
                "PATCH-GTN-SYS-REDIS (redis_lock_ttl_ms=1500 + Circuit Breaker + Caché Redis)."
            ),
        },
        {
            "step": "5. QUALITY GATES & RE-DEPLOY CANARY",
            "actor": "Selenium MCP + Pytest E2E + JMeter IA + Canary Deployer",
            "status": "COMPLETED",
            "durationMs": 1890,
            "detail": (
                "Desplegada versión v2026.11.2-AUTONOMOUS-PRO. Certificados 14/14 Test Cases en Jira Xray "
                "(GTN-TC-001 a GTN-TC-014 PASSED). Latencia P95 reducida de 1840ms a 42.5ms."
            ),
        },
        {
            "step": "6. CUADRO DE MANDO CIO JIRA XRAY",
            "actor": "Hub ALM Getnet (Jira Xray / TestLink / Redmine)",
            "status": "COMPLETED",
            "durationMs": 310,
            "detail": (
                "Incidencias GTN-INC-ATM-001 y GTN-INC-SYS-002 cerradas automáticamente en estado "
                "RESOLVED (AUTO-REDEPLOYED) con trazabilidad completa de auditoría."
            ),
        },
    ],
    "atmKiroDetail": {
        "incidentKey": "GTN-INC-ATM-001",
        "atmId": "ATM-GTN-MAD-0042",
        "location": "Sucursal Getnet Gran Vía 28, Madrid",
        "engine": "AWS_Kiro-main (atm_sentinel.py + brand_verifier/incident.py)",
        "rawEvent": "Tarjeta Getnet 4548 1234 5678 9012 retenida en ranura tras bloqueo preventivo sin reverso EMV.",
        "panRedacted": "Tarjeta Getnet **** **** **** 9012 retenida en ranura tras bloqueo preventivo sin reverso EMV.",
        "scenePrompt": (
            "Cajero automatico de calle por la noche, plano medio realista, pantalla encendida mostrando el logotipo, "
            "sin personas identificables, sin texto legible y sin numeros. Contexto de la escena: Tarjeta Getnet "
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
            {"frame": "frame_01_0.50s.jpg", "time_s": 0.5, "obs": "Inserción de tarjeta EMV en lector híbrido ATM-GTN-MAD-0042"},
            {"frame": "frame_03_4.20s.jpg", "time_s": 4.2, "obs": "Activación de bloqueo preventivo; tarjeta retenida en ranura"},
            {"frame": "frame_06_9.80s.jpg", "time_s": 9.8, "obs": "Hotfix aplicado: Reverso MTI 0420 emitido y plástico liberado"},
        ],
        "status": "RESOLVED (AUTO-REDEPLOYED)",
    },
    "cloudwatchSysDetail": {
        "incidentKey": "GTN-INC-SYS-002",
        "service": "getnet-card-blocker-svc (ECS Cluster prod-eu-west-1)",
        "alarmName": "CW-ALARM-GTN-CARDLOCK-P99",
        "mcpServer": "getnet-observability-kiro-mcp v1.0.0 (CloudWatch + Prometheus OpenSource)",
        "logGroup": "/aws/ecs/getnet-card-blocker-svc",
        "errorSignature": "DeadlockDetectedException: Redis mutex lock on CARD_BLOCK_STATE acquired with lock_ttl_ms=0; HikariPool-1 connection timeout (3000ms)",
        "metricsBeforeFix": {
            "p95LatencyMs": 1840.0,
            "errorRatePct": 14.8,
            "hikariPoolUsagePct": 98.5,
            "redisMutexDeadlocks": 27,
            "alarmState": "ALARM",
        },
        "metricsAfterFix": {
            "p95LatencyMs": 42.5,
            "errorRatePct": 0.0,
            "hikariPoolUsagePct": 18.4,
            "redisMutexDeadlocks": 0,
            "alarmState": "OK",
        },
        "hotfixCommit": "fix(card-blocker-svc): set redis_lock_ttl_ms=1500, enable circuit breaker & Redis rule cache",
        "status": "RESOLVED (AUTO-REDEPLOYED)",
    },
}

# ---------------------------------------------------------------------------
# Catálogo de Servicios Getnet (Compatible 100% con Selectores Selenium/MCP)
# ---------------------------------------------------------------------------

SERVICIOS_CATALOGO: List[Dict[str, Any]] = [
    {
        "id": "srv-cuadro-medico",
        "codigo": "CUADRO_MEDICO",
        "titulo": "Red de Cajeros ATM, SmartPOS y Centros Getnet",
        "descripcion": "Más de 43.000 terminales SmartPOS, cajeros ATM monitorizados con IA (AWS Kiro) y 1.300 nodos de soporte en España.",
        "icono": "🏧",
        "sla_respuesta_ms": 150,
        "destacado": True,
        "tab_target": "tab-cuadro",
    },
    {
        "id": "srv-autorizaciones",
        "codigo": "AUTORIZACIONES",
        "titulo": "Autorizaciones ISO-8583 y Operativa de Tarjetas",
        "descripcion": "Gestiona autorizaciones instantáneas, desbloqueo de tarjetas EMV y validaciones antifraude sin tiempos de espera.",
        "icono": "💳",
        "sla_respuesta_ms": 250,
        "destacado": True,
        "tab_target": "tab-autorizaciones",
    },
    {
        "id": "srv-reembolsos",
        "codigo": "REEMBOLSOS",
        "titulo": "Liquidación de Comercios, Reembolsos y Chargebacks",
        "descripcion": "Tramita liquidaciones TPV, devoluciones y disputas recibiendo hasta el 90% de abono inmediato en tu cuenta IBAN.",
        "icono": "💶",
        "sla_respuesta_ms": 250,
        "destacado": True,
        "tab_target": "tab-reembolsos",
    },
    {
        "id": "srv-area-cliente",
        "codigo": "AREA_CLIENTE",
        "titulo": "Área Cliente / Comercio y Tarjeta Digital Getnet",
        "descripcion": "Consulta tus contratos de adquirencia, liquidaciones y lleva siempre activa tu Tarjeta Corporativa Digital Getnet.",
        "icono": "🪪",
        "sla_respuesta_ms": 180,
        "destacado": True,
        "tab_target": "tab-area-cliente",
    },
    {
        "id": "srv-videoconsulta",
        "codigo": "SALUD_DIGITAL",
        "titulo": "Soporte Técnico Remoto y Asistencia Especializada 24h",
        "descripcion": "Conecta por videollamada WebRTC o línea prioritaria 24h con especialistas en pasarela de pagos, TPV y cajeros ATM.",
        "icono": "🛠️",
        "sla_respuesta_ms": 200,
        "destacado": False,
        "tab_target": "tab-videoconsulta",
    },
    {
        "id": "srv-urgencias",
        "codigo": "URGENCIAS_24H",
        "titulo": "Centro de Control ATM Bloqueo de Tarjetas & CloudWatch 24h",
        "descripcion": "Simulador en vivo de incidencias de bloqueo de tarjeta en ATM (AWS_Kiro) y remediación autónoma CloudWatch sin Human-in-the-Loop.",
        "icono": "🚨",
        "sla_respuesta_ms": 120,
        "destacado": True,
        "tab_target": "tab-bloqueo-atm",
    },
]

CUADRO_MEDICO_DB: List[Dict[str, Any]] = [
    {
        "id": "GTN-MAD-001",
        "nombre": "Hub Central Getnet & Cajero ATM-GTN-MAD-0042 (Hospital Ruber / Castellana)",
        "facultativo": "Ing. Alejandro Vega Martín (Responsable Nodo ATM & SmartPOS)",
        "provincia": "Madrid",
        "especialidad": "Cardiología",
        "servicio_getnet": "Cajeros ATM Cash-In & SmartPOS",
        "direccion": "Gran Vía 28 / Calle de la Masó, 38, 28034 Madrid",
        "telefono": "913 875 000",
        "polizas": ["Adeslas Plena Plus", "Adeslas Plena Vital", "Adeslas Seniors", "Adeslas Premier", "Muface / Isfas", "Getnet Premier"],
        "cita_online": True,
        "urgencias_24h": True,
        "copago": "0 € Comisión (Getnet Premier)",
    },
    {
        "id": "GTN-MAD-002",
        "nombre": "Centro de Operaciones Getnet Madrid Príncipe de Vergara",
        "facultativo": "Ing. Elena Soriano Ruiz (Especialista Adquirencia & EMV)",
        "provincia": "Madrid",
        "especialidad": "Cardiología",
        "servicio_getnet": "Terminales TPV & Tarjetas Corporativas",
        "direccion": "Calle del Príncipe de Vergara, 204, 28002 Madrid",
        "telefono": "915 643 210",
        "polizas": ["Adeslas Plena Plus", "Adeslas Plena Vital", "Adeslas Seniors", "Muface / Isfas", "Getnet Pro"],
        "cita_online": True,
        "urgencias_24h": False,
        "copago": "Según tarifa comercio",
    },
    {
        "id": "GTN-MAD-003",
        "nombre": "Nodo de Guardia 24h Getnet & Red ATM Sanchinarro",
        "facultativo": "Unidad de Guardia 24h · Monitorización ATM Sentinel & CloudWatch",
        "provincia": "Madrid",
        "especialidad": "Urgencias 24h",
        "servicio_getnet": "Soporte Crítico ATM & Guardia 24h",
        "direccion": "Calle de Oña, 10, 28050 Madrid",
        "telefono": "917 567 800",
        "polizas": ["Adeslas Plena Plus", "Adeslas Plena Vital", "Adeslas Seniors", "Adeslas Premier", "Muface / Isfas"],
        "cita_online": True,
        "urgencias_24h": True,
        "copago": "SLA Crítico < 15 min",
    },
    {
        "id": "GTN-MAD-004",
        "nombre": "Oficina Comercial Getnet SmartPOS Goya",
        "facultativo": "Dr. Javier Mendoza Ortiz (Consultor Pagos Digitales)",
        "provincia": "Madrid",
        "especialidad": "Dental",
        "servicio_getnet": "Comercios Retail & Franquicias",
        "direccion": "Calle de Goya, 115, 28009 Madrid",
        "telefono": "900 229 922",
        "polizas": ["Adeslas Plena Plus", "Adeslas Dental Max", "Adeslas Seniors", "Muface / Isfas"],
        "cita_online": True,
        "urgencias_24h": False,
        "copago": "Franquicia Cero Getnet",
    },
    {
        "id": "GTN-BCN-001",
        "nombre": "Hub Tecnológico Getnet Barcelona Diagonal / Teknon",
        "facultativo": "Ing. Montserrat Puigvert Bosch",
        "provincia": "Barcelona",
        "especialidad": "Dermatología",
        "servicio_getnet": "Pasarela E-Commerce & Tokenización",
        "direccion": "Carrer de Vilana, 12, 08022 Barcelona",
        "telefono": "932 906 200",
        "polizas": ["Adeslas Plena Plus", "Adeslas Plena Vital", "Adeslas Premier"],
        "cita_online": True,
        "urgencias_24h": True,
        "copago": "0 € (Getnet Plus)",
    },
    {
        "id": "GTN-BCN-002",
        "nombre": "Centro de Respuesta Inmediata ATM 24h Barcelona",
        "facultativo": "Unidad de Guardia 24h · Red Cajeros & TPV Cataluña",
        "provincia": "Barcelona",
        "especialidad": "Urgencias 24h",
        "servicio_getnet": "Urgencias Operativas 24h",
        "direccion": "Plaça d'Alfonso Comín, 5, 08023 Barcelona",
        "telefono": "932 554 000",
        "polizas": ["Adeslas Plena Plus", "Adeslas Plena Vital", "Adeslas Seniors", "Muface / Isfas"],
        "cita_online": True,
        "urgencias_24h": True,
        "copago": "0 €",
    },
    {
        "id": "GTN-SEV-001",
        "nombre": "Centro Regional Getnet Andalucía - Sevilla",
        "facultativo": "Ing. Manuel Domínguez Romero",
        "provincia": "Sevilla",
        "especialidad": "Traumatología",
        "servicio_getnet": "Soporte TPV Hostelería & ATM",
        "direccion": "Calle Rafael Salgado, 3, 41013 Sevilla",
        "telefono": "954 937 676",
        "polizas": ["Adeslas Plena Plus", "Adeslas Plena Vital", "Adeslas Seniors", "Muface / Isfas"],
        "cita_online": True,
        "urgencias_24h": True,
        "copago": "0 €",
    },
    {
        "id": "GTN-VAL-001",
        "nombre": "Centro Regional Getnet Levante - Valencia",
        "facultativo": "Ing. Carmen Albornoz Gil",
        "provincia": "Valencia",
        "especialidad": "Pediatría",
        "servicio_getnet": "Adquirencia & Liquidación Instantánea",
        "direccion": "Carrer de la Vall de la Ballestera, 59, 46015 València",
        "telefono": "963 179 100",
        "polizas": ["Adeslas Plena Plus", "Adeslas Plena Vital", "Muface / Isfas"],
        "cita_online": True,
        "urgencias_24h": True,
        "copago": "0 €",
    },
    {
        "id": "GTN-BIL-001",
        "nombre": "Centro Operativo Getnet Zona Norte - Bilbao",
        "facultativo": "Ing. Iñaki Etxebarria Goikoetxea",
        "provincia": "Bilbao",
        "especialidad": "Cardiología",
        "servicio_getnet": "Cajeros ATM & Pasarela ISO-8583",
        "direccion": "Ballets Olaeta Kalea, 4, 48014 Bilbo",
        "telefono": "944 755 000",
        "polizas": ["Adeslas Plena Plus", "Adeslas Premier", "Muface / Isfas"],
        "cita_online": True,
        "urgencias_24h": True,
        "copago": "0 €",
    },
]

CLIENTES_DB: Dict[str, Dict[str, Any]] = {
    "12345678Z": {
        "nif": "12345678Z",
        "passwords_validos": ["Adeslas2026!", "Getnet2026!"],
        "nombre": "Carlos Martínez Gómez",
        "num_poliza": "POL-SCA-908122",
        "contrato_getnet": "MRC-GTN-908122",
        "num_tarjeta": "8000123456789012",
        "modalidad": "Getnet Premier Enterprise + Reembolso 90% (Adeslas Plena Plus)",
        "fecha_alta": "15/01/2021",
        "estado_poliza": "ACTIVA - COMERCIO & TARJETA VERIFICADOS EN PRO",
        "copago_acumulado_anual": "0,00 € (Tarifa Plana Getnet Premier)",
        "beneficiarios": [
            {"nombre": "Carlos Martínez Gómez (Titular / Comercio)", "tarjeta": "8000123456789012"},
            {"nombre": "Terminal ATM-GTN-MAD-0042 (Tarjeta Operativa)", "tarjeta": "4548123456789012"},
        ],
    },
    "87654321X": {
        "nif": "87654321X",
        "passwords_validos": ["Adeslas2026!", "Getnet2026!"],
        "nombre": "Marta Sánchez Alcázar",
        "num_poliza": "POL-SCA-774510",
        "contrato_getnet": "MRC-GTN-774510",
        "num_tarjeta": "8000987654321098",
        "modalidad": "Getnet Corporate Red Santander / Euro6000",
        "fecha_alta": "01/02/2019",
        "estado_poliza": "ACTIVA - CONCIERTO CORPORATIVO",
        "copago_acumulado_anual": "0,00 €",
        "beneficiarios": [
            {"nombre": "Marta Sánchez Alcázar (Titular)", "tarjeta": "8000987654321098"},
        ],
    },
}

AUTORIZACIONES_REGISTRADAS: List[Dict[str, Any]] = []
REEMBOLSOS_REGISTRADOS: List[Dict[str, Any]] = []
CITAS_REGISTRADAS: List[Dict[str, Any]] = []

JMETER_LATEST_REPORT: Dict[str, Any] = {
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "scenario": "Pico Transaccional Getnet Core & Card Blocker (12 VUs / 60 muestras)",
    "totalSamples": 60,
    "throughputRps": 46.2,
    "avgResponseMs": 29.8,
    "p90Ms": 58.0,
    "p95Ms": 68.4,
    "p99Ms": 89.2,
    "errorRatePct": 0.0,
    "apdex": 1.0,
    "slaStatus": "PASSED",
    "aiInsights": [
        "Cumplimiento SLA Global Getnet: APROBADO (P95 = 68.4 ms frente al umbral SLA < 450.0 ms; Error Rate = 0.0%).",
        "Índice de satisfacción transaccional Apdex = 1.0 con caudal sostenido de 46.2 req/s tras aplicar Hotfix PATCH-GTN-SYS-REDIS.",
        "Certificación Post-Redeploy (GTN-INC-SYS-002): El lock distribuido Redis con TTL=1500ms y caché activa eliminó la contención en getnet-card-blocker-svc.",
    ],
    "endpoints": [
        {"label": "GET /api/v1/cuadro-medico", "samples": 24, "avgMs": 13.5, "p95Ms": 24.0, "errorPct": 0.0},
        {"label": "POST /api/v1/autorizaciones", "samples": 12, "avgMs": 17.2, "p95Ms": 29.5, "errorPct": 0.0},
        {"label": "POST /api/v1/autorizaciones (Estudio Genético)", "samples": 12, "avgMs": 62.1, "p95Ms": 71.0, "errorPct": 0.0},
        {"label": "POST /api/v1/reembolsos", "samples": 12, "avgMs": 15.8, "p95Ms": 26.4, "errorPct": 0.0},
    ],
}

SELENIUM_LATEST_REPORT: Dict[str, Any] = {
    "runId": "XRAY-EXEC-GTN-2026-104",
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "browser": "Google Chrome Headless 1440x950 (Selenium WebDriver 4.52)",
    "mcpServer": "getnet-selenium-qaops v1.0.0 + getnet-observability-kiro-mcp v1.0.0",
    "domLocatorsExtracted": 45,
    "domPruningSavingPct": 92.8,
    "selfHealingEventsCount": 0,
    "selfHealingStatus": "ACTIVE · 45/45 Selectores Primarios Verificados (0 Roturas)",
    "totalDurationMs": 5820,
    "passed": 12,
    "failed": 0,
    "total": 12,
    "screenshotUrl": "/api/v1/qaops/screenshot/mcp_selftest_servicios_clientes.png",
    "mcpToolRuns": [
        {
            "tool": "atm_kiro_inspect_incident (AWS_Kiro-main)",
            "target": "ATM-GTN-MAD-0042 · PAN 4548 **** **** 9012",
            "durationMs": 120,
            "status": "PASSED",
            "output": "Triaje TARJETA_RETENIDA (CRITICO) + PAN Redacted PCI-DSS + Hotfix EMV 0420",
        },
        {
            "tool": "cloudwatch_get_alarms + prometheus_query_metrics",
            "target": "CW-ALARM-GTN-CARDLOCK-P99 & getnet-card-blocker-svc",
            "durationMs": 95,
            "status": "PASSED",
            "output": "Deadlock Redis resuelto (TTL=1500ms) · Alarma CloudWatch en estado OK",
        },
        {
            "tool": "selenium_start_session & inspect_dom_locators",
            "target": "http://127.0.0.1:8080/servicios-para-clientes",
            "durationMs": 640,
            "status": "PASSED",
            "output": "45 selectores extraídos (-92.8% ahorro de tokens vía DOM Pruning)",
        },
        {
            "tool": "selenium_execute_adeslas_flow (cuadro_medico & autorizacion)",
            "target": "Provincia=Madrid, Tarjeta=8000123456789012",
            "durationMs": 740,
            "status": "PASSED",
            "output": "Nodos ATM/TPV verificados + Código AUT-2026 generado",
        },
        {
            "tool": "selenium_take_screenshot",
            "target": "selenium-qaops/reports/mcp_selftest_servicios_clientes.png",
            "durationMs": 175,
            "status": "PASSED",
            "output": "Evidencia visual PNG almacenada",
        },
        {
            "tool": "alm_sync_test_result",
            "target": "POST /api/v1/qaops/test-runs (Jira Xray / TestLink / Redmine)",
            "durationMs": 42,
            "status": "PASSED",
            "output": "14/14 casos sincronizados en Cuadro de Mando Jira Xray",
        },
    ],
    "testCasesDetail": [
        {
            "key": "GTN-TC-001",
            "testLinkId": "TL-GTN-101",
            "name": "test_tc001_catalogo_servicios_clientes",
            "locatorPrimary": "#hero-title / #catalogo-servicios-grid .service-card",
            "locatorFallback": "[data-testid='hero-title'] / [data-testid^='service-card-']",
            "assertion": "6 tarjetas de servicio Getnet renderizadas y KPIs visibles",
            "durationMs": 580,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-002",
            "testLinkId": "TL-GTN-102",
            "name": "test_tc002_busqueda_cuadro_medico_madrid_cardiologia",
            "locatorPrimary": "#cm-provincia + #cm-especialidad + #btn-buscar-cuadro",
            "locatorFallback": "[data-testid='select-provincia'] + [data-testid='btn-buscar-cuadro']",
            "assertion": ">= 2 nodos ATM / centros operativos en Madrid",
            "durationMs": 510,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-003",
            "testLinkId": "TL-GTN-103",
            "name": "test_tc003_busqueda_urgencias_muface",
            "locatorPrimary": "#cm-especialidad + #cm-poliza + #btn-buscar-cuadro",
            "locatorFallback": "[data-testid='select-poliza'] -> Guardia 24h",
            "assertion": ">= 2 centros con Guardia / Urgencias 24h operativos",
            "durationMs": 490,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-004",
            "testLinkId": "TL-GTN-104",
            "name": "test_tc004_solicitud_autorizacion_exitosa",
            "locatorPrimary": "#aut-tarjeta + #aut-tipo-acto + #btn-solicitar-autorizacion",
            "locatorFallback": "[data-testid='input-aut-tarjeta'] + [data-testid='aut-resultado-alert']",
            "assertion": "Estado == AUTORIZADA y código AUT-2026-XXXXX generado",
            "durationMs": 560,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-005",
            "testLinkId": "TL-GTN-105",
            "name": "test_tc005_autorizacion_tarjeta_invalida",
            "locatorPrimary": "#aut-tarjeta (valor '12345') + #aut-resultado-alert",
            "locatorFallback": "[data-testid='aut-resultado-alert']",
            "assertion": "Rechazo HTTP 400 + Alerta 'entre 12 y 16 dígitos numéricos'",
            "durationMs": 450,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-006",
            "testLinkId": "TL-GTN-106",
            "name": "test_tc006_autorizacion_revision_medica",
            "locatorPrimary": "POST /api/v1/autorizaciones (Inspección Antifraude / Compleja)",
            "locatorFallback": "Contrato SDD RN-AUT-02",
            "assertion": "Estado == PENDIENTE_REVISION_MEDICA (SLA 48h)",
            "durationMs": 95,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-007",
            "testLinkId": "TL-GTN-107",
            "name": "test_tc007_reembolso_premier_calculo_90",
            "locatorPrimary": "#rmb-nif + #rmb-modalidad + #rmb-importe + #rmb-iban",
            "locatorFallback": "[data-testid='rmb-importe-abonado']",
            "assertion": "Expediente RMB-2026-XXXXX y abono exacto 225.00 EUR (90% de 250 EUR)",
            "durationMs": 610,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-008",
            "testLinkId": "TL-GTN-108",
            "name": "test_tc008_reembolso_iban_invalido",
            "locatorPrimary": "#rmb-iban (valor 'ES1234') + #rmb-resultado-alert",
            "locatorFallback": "[data-testid='rmb-resultado-alert']",
            "assertion": "Rechazo HTTP 400 + Alerta formato IBAN ES + 22 dígitos",
            "durationMs": 460,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-009",
            "testLinkId": "TL-GTN-109",
            "name": "test_tc009_login_area_cliente_tarjeta_digital",
            "locatorPrimary": "#login-nif + #login-password + #btn-login-cliente",
            "locatorFallback": "[data-testid='tarjeta-digital-adeslas']",
            "assertion": "Titular Carlos Martínez Gómez + Contrato POL-SCA-908122 + Tarjeta Digital",
            "durationMs": 550,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-010",
            "testLinkId": "TL-GTN-110",
            "name": "test_tc010_reserva_videoconsulta_medica",
            "locatorPrimary": "#vc-especialidad + #vc-motivo + #btn-reservar-vc",
            "locatorFallback": "[data-testid='vc-codigo-cita']",
            "assertion": "Sesión confirmada CIT-2026-XXXXX + Dra. Patricia Navarro Solís",
            "durationMs": 520,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-013",
            "testLinkId": "TL-GTN-113",
            "name": "test_tc013_incidencia_funcional_atm_kiro_autofix",
            "locatorPrimary": "POST /api/v1/tarjetas/bloqueo + AWS_Kiro (ATM-GTN-MAD-0042)",
            "locatorFallback": "#btn-ejecutar-bloqueo-atm / [data-testid='atm-bloqueo-alert']",
            "assertion": "Detección + PAN Masking + Auto-Fix EMV 0420 + GTN-INC-ATM-001 RESOLVED",
            "durationMs": 145,
            "status": "PASSED",
        },
        {
            "key": "GTN-TC-014",
            "testLinkId": "TL-GTN-114",
            "name": "test_tc014_incidencia_sistemas_cloudwatch_mcp_autofix",
            "locatorPrimary": "GET /api/v1/observability/status + POST /api/v1/alm/autonomous-cycle",
            "locatorFallback": "MCP Server getnet-observability-kiro-mcp",
            "assertion": "Alarma CloudWatch OK + Redis Lock TTL=1500ms + GTN-INC-SYS-002 RESOLVED",
            "durationMs": 162,
            "status": "PASSED",
        },
    ],
}

EXECUTION_HISTORY: List[Dict[str, Any]] = [
    {
        "execKey": "GTN-EXEC-2026-104",
        "buildName": "Build #104 · Ciclo Autónomo ALM en PRO Sin Human-in-the-Loop (ATM Kiro + CloudWatch MCP)",
        "runner": "Autonomous ALM Orchestrator + AWS_Kiro + CloudWatch/Prometheus MCP",
        "environment": "Production Simulation (Zero Human-in-the-Loop)",
        "testsScope": "GTN-INC-ATM-001 + GTN-INC-SYS-002 -> Auto-Fix & Re-Deploy (GTN-TC-001..014)",
        "passed": 14,
        "failed": 0,
        "durationMs": 6930,
        "status": "PASSED",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    },
    {
        "execKey": "GTN-EXEC-2026-103",
        "buildName": "Build #103 · Suite Pytest + Selenium POM (E2E Funcional & Auto-Remediation)",
        "runner": "Pytest + Selenium WebDriver (Chrome Headless)",
        "environment": "Local Simulation (127.0.0.1:8080)",
        "testsScope": "GTN-TC-001 .. GTN-TC-010, GTN-TC-013, GTN-TC-014 (12 tests)",
        "passed": 12,
        "failed": 0,
        "durationMs": 5820,
        "status": "PASSED",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    },
    {
        "execKey": "GTN-EXEC-2026-102",
        "buildName": "Build #102 · Diagnóstico Servidores MCP (Selenium + CloudWatch/Prometheus)",
        "runner": "Agente IA via MCP Servers (getnet-selenium + getnet-observability)",
        "environment": "Local Simulation (127.0.0.1:8080)",
        "testsScope": "DOM Pruning (45 locators) + CloudWatch Alarms + AWS_Kiro ATM Sentinel",
        "passed": 6,
        "failed": 0,
        "durationMs": 1840,
        "status": "PASSED",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    },
    {
        "execKey": "GTN-EXEC-2026-101",
        "buildName": "Build #101 · Performance Gate JMeter Asistido por IA",
        "runner": "JMeter AI Assistant (ai_jmeter_assistant.py)",
        "environment": "Local Simulation (12 VUs / 60 muestras)",
        "testsScope": "GTN-TC-011 .. GTN-TC-012 (P95 = 68.4ms, Apdex = 1.0)",
        "passed": 2,
        "failed": 0,
        "durationMs": 1420,
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
# Rutas Vistas HTML (Portal Getnet + Cuadro de Mando Ejecutivo Jira Xray)
# ---------------------------------------------------------------------------


@app.route("/")
def root_redirect():
    return redirect("/servicios-para-clientes")


@app.route("/getnet-portal")
def getnet_portal_redirect():
    return redirect("/servicios-para-clientes")


@app.route("/servicios-para-clientes")
def servicios_para_clientes_view():
    return render_template(
        "servicios_clientes.html",
        servicios=SERVICIOS_CATALOGO,
        cuadro_inicial=CUADRO_MEDICO_DB,
        system_state=SYSTEM_INCIDENT_STATE,
        tarjetas_log=TARJETAS_BLOQUEADAS_LOG,
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
    )


@app.route("/presentacion")
def presentacion_ejecutiva_view():
    pres_html = PROJECT_ROOT / "presentacion" / "index.html"
    if pres_html.exists():
        return send_file(pres_html)
    return redirect("/alm-dashboard")


# ---------------------------------------------------------------------------
# Endpoints API REST (/api/v1/*) para Portal Getnet, AWS_Kiro, CloudWatch MCP
# ---------------------------------------------------------------------------


@app.route("/api/v1/health", methods=["GET"])
def api_health():
    degraded = SYSTEM_INCIDENT_STATE["atm_functional_bug_active"] or SYSTEM_INCIDENT_STATE["systems_cloudwatch_bug_active"]
    return jsonify(
        {
            "status": "DEGRADED_INCIDENT_ACTIVE" if degraded else "UP",
            "service": "getnet-autonomous-alm-card-core-sim",
            "client": "Getnet (Grupo Santander)",
            "qaopsProvider": "Ayesa Digital",
            "almMode": "ZERO_HUMAN_IN_THE_LOOP",
            "currentRelease": SYSTEM_INCIDENT_STATE["currentRelease"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "incidentFlags": {
                "atmFunctionalBugActive": SYSTEM_INCIDENT_STATE["atm_functional_bug_active"],
                "systemsCloudwatchBugActive": SYSTEM_INCIDENT_STATE["systems_cloudwatch_bug_active"],
            },
            "stats": {
                "nodosRedAtm": len(CUADRO_MEDICO_DB),
                "autorizacionesTramitadas": len(AUTORIZACIONES_REGISTRADAS),
                "reembolsosTramitados": len(REEMBOLSOS_REGISTRADOS),
                "tarjetasBloqueadas": len(TARJETAS_BLOQUEADAS_LOG),
                "citasSoporteAgendadas": len(CITAS_REGISTRADAS),
            },
        }
    )


@app.route("/api/v1/servicios", methods=["GET"])
def api_servicios():
    return jsonify({"total": len(SERVICIOS_CATALOGO), "servicios": SERVICIOS_CATALOGO})


@app.route("/api/v1/cuadro-medico", methods=["GET"])
def api_cuadro_medico():
    provincia = request.args.get("provincia", "").strip()
    especialidad = request.args.get("especialidad", "").strip()
    poliza = request.args.get("poliza", "").strip()
    q = request.args.get("q", "").strip().lower()
    urgencias = request.args.get("urgencias24h", "").strip().lower()

    resultados = []
    for item in CUADRO_MEDICO_DB:
        if provincia and provincia != "Todas" and item["provincia"].lower() != provincia.lower():
            continue
        if especialidad and especialidad != "Todas":
            esp_low = especialidad.lower()
            if esp_low != item["especialidad"].lower() and esp_low not in item.get("servicio_getnet", "").lower():
                continue
        if poliza and poliza != "Todas":
            if not any(poliza.lower() in p.lower() for p in item["polizas"]):
                continue
        if urgencias in ("true", "1", "si") and not item["urgencias_24h"]:
            continue
        if q:
            texto = (
                f"{item['nombre']} {item['facultativo']} {item['direccion']} "
                f"{item['especialidad']} {item.get('servicio_getnet', '')}"
            ).lower()
            if q not in texto:
                continue
        resultados.append(item)

    return jsonify(
        {
            "filtros": {
                "provincia": provincia or "Todas",
                "especialidad": especialidad or "Todas",
                "poliza": poliza or "Todas",
                "q": q,
            },
            "total": len(resultados),
            "resultados": resultados,
        }
    )


@app.route("/api/v1/autorizaciones", methods=["POST"])
def api_crear_autorizacion():
    payload = request.get_json(silent=True) or {}
    num_tarjeta = str(payload.get("numTarjeta", "")).strip().replace(" ", "")
    tipo_acto = str(payload.get("tipoActo", "")).strip()
    cod_prescripcion = str(payload.get("codigoPrescripcion", "")).strip()
    centro_medico = str(payload.get("centroMedico", "")).strip()
    observaciones = str(payload.get("observaciones", "")).strip()

    if not re.fullmatch(r"\d{12,16}", num_tarjeta):
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "INVALID_CARD_NUMBER",
                    "mensaje": "El número de Tarjeta Getnet debe contener entre 12 y 16 dígitos numéricos (ej. 8000123456789012).",
                }
            ),
            400,
        )

    if not tipo_acto or not cod_prescripcion or not centro_medico:
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "MISSING_REQUIRED_FIELDS",
                    "mensaje": "Todos los campos obligatorios (Tipo de operación, Código de referencia y Nodo/Centro) deben completarse.",
                }
            ),
            400,
        )

    es_compleja = (
        "genético" in tipo_acto.lower()
        or "genetico" in tipo_acto.lower()
        or "oncol" in tipo_acto.lower()
        or "antifraude" in tipo_acto.lower()
    )
    if es_compleja:
        time.sleep(0.04)
        estado = "PENDIENTE_REVISION_MEDICA"
        mensaje = "Su operación requiere validación por la Unidad de Riesgos / Inspección de Getnet (SLA máximo 48h)."
    else:
        estado = "AUTORIZADA"
        mensaje = "Autorización ISO-8583 concedida automáticamente por el motor Getnet. Operación confirmada."

    codigo_aut = f"AUT-2026-{random.randint(10000, 99999)}"
    registro = {
        "codigoAutorizacion": codigo_aut,
        "numTarjeta": num_tarjeta,
        "tipoActo": tipo_acto,
        "codigoPrescripcion": cod_prescripcion,
        "centroMedico": centro_medico,
        "observaciones": observaciones,
        "estado": estado,
        "mensaje": mensaje,
        "fechaSolicitud": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    AUTORIZACIONES_REGISTRADAS.append(registro)
    return jsonify({"ok": True, "autorizacion": registro}), 201


@app.route("/api/v1/reembolsos", methods=["POST"])
def api_crear_reembolso():
    payload = request.get_json(silent=True) or {}
    nif = str(payload.get("nif", "")).strip().upper()
    modalidad_poliza = str(payload.get("modalidadPoliza", "Getnet Premier (90%)")).strip()
    concepto = str(payload.get("conceptoFactura", "Liquidación TPV / Disputa Comercio")).strip()
    iban = str(payload.get("iban", "")).strip().upper().replace(" ", "")

    try:
        importe = float(payload.get("importeFactura", 0))
    except (TypeError, ValueError):
        importe = -1.0

    if not re.fullmatch(r"[0-9XYZ]\d{7}[A-Z]", nif):
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "INVALID_NIF",
                    "mensaje": "El NIF/NIE/CIF introducido no tiene un formato válido (ej. 12345678Z).",
                }
            ),
            400,
        )

    if importe <= 0:
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "INVALID_AMOUNT",
                    "mensaje": "El importe de la liquidación/factura debe ser mayor que 0,00 €.",
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
                    "mensaje": "El código IBAN debe comenzar por ES seguido de 22 dígitos numéricos.",
                }
            ),
            400,
        )

    porcentaje = 0.90 if "premier" in modalidad_poliza.lower() or "90" in modalidad_poliza else 0.80
    importe_reembolsado = round(importe * porcentaje, 2)
    expediente = f"RMB-2026-{random.randint(10000, 99999)}"

    registro = {
        "expediente": expediente,
        "nif": nif,
        "modalidadPoliza": modalidad_poliza,
        "conceptoFactura": concepto,
        "importeFactura": round(importe, 2),
        "porcentajeCobertura": int(porcentaje * 100),
        "importeEstimadoReembolso": importe_reembolsado,
        "ibanAbono": f"{iban[:4]} **** **** **** {iban[-4:]}",
        "estado": "EN_TRAMITACION_ABONO",
        "plazoEstimadoDias": 1,
        "fechaRegistro": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    REEMBOLSOS_REGISTRADOS.append(registro)
    return jsonify({"ok": True, "reembolso": registro}), 201


@app.route("/api/v1/auth/login", methods=["POST"])
def api_login_cliente():
    payload = request.get_json(silent=True) or {}
    nif = str(payload.get("nif", "")).strip().upper()
    password = str(payload.get("password", "")).strip()

    cliente = CLIENTES_DB.get(nif)
    if not cliente or password not in cliente["passwords_validos"]:
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "AUTH_INVALID_CREDENTIALS",
                    "mensaje": "NIF/NIE o contraseña incorrectos. Para pruebas QAOps utilice 12345678Z / Adeslas2026! (o Getnet2026!).",
                }
            ),
            401,
        )

    perfil_publico = {k: v for k, v in cliente.items() if k != "passwords_validos"}
    return jsonify({"ok": True, "cliente": perfil_publico})


@app.route("/api/v1/citas", methods=["POST"])
def api_crear_cita():
    payload = request.get_json(silent=True) or {}
    especialidad = str(payload.get("especialidad", "Medicina General")).strip()
    modalidad = str(payload.get("modalidadCita", "Videoconsulta Inmediata")).strip()
    motivo = str(payload.get("motivoConsulta", "")).strip()
    telefono = str(payload.get("telefonoContacto", "600123456")).strip()

    if not motivo:
        return (
            jsonify(
                {
                    "ok": False,
                    "errorCode": "MISSING_REASON",
                    "mensaje": "Por favor indique brevemente el motivo de la asistencia o soporte remoto 24h.",
                }
            ),
            400,
        )

    codigo_cita = f"CIT-2026-{random.randint(10000, 99999)}"
    cita = {
        "codigoCita": codigo_cita,
        "especialidad": especialidad,
        "modalidadCita": modalidad,
        "motivoConsulta": motivo,
        "telefonoContacto": telefono,
        "facultativoAsignado": "Dra. Patricia Navarro Solís (Especialista Guardia 24h Nº 28/49102)",
        "salaVirtualUrl": f"https://soporte24h.getnet.eu/sala/{codigo_cita}",
        "estado": "CONFIRMADA",
    }
    CITAS_REGISTRADAS.append(cita)
    return jsonify({"ok": True, "cita": cita}), 201


# ---------------------------------------------------------------------------
# NUEVO: Aplicativo de Sistema de Bloqueo de Tarjetas + ATM Kiro + CloudWatch
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
    """
    Simula la aplicación de sistema de bloqueo preventivo de tarjeta desde un Cajero ATM (AWS_Kiro-main).
    - Si hay una incidencia funcional activa (atm_functional_bug_active=True), reproduce el fallo de producción:
      la tarjeta queda retenida sin reverso EMV 0420 (HTTP 409).
    - Si el ciclo autónomo ALM ya aplicó el Re-Fixing (o se invoca tras auto-remediación),
      procesa el bloqueo con redact_pan (AWS_Kiro), emite el reverso ISO-8583 MTI 0420,
      expulsa la tarjeta de forma segura y genera un token digital de reemplazo.
    """
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
                    "mensaje": "El PAN de la tarjeta debe contener entre 12 y 19 dígitos para procesar el bloqueo ATM.",
                }
            ),
            400,
        )

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    raw_desc = (
        f"Evento en {atm_id} ({ubicacion}): Solicitud de bloqueo por {motivo} para la tarjeta {raw_pan}."
    )
    inc_obj = {
        "atm_id": atm_id,
        "ubicacion": ubicacion,
        "descripcion": raw_desc,
        "fecha_hora": now_iso,
    }
    kiro_errors = validate_incident(inc_obj)
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
            "kiroValidationErrors": kiro_errors,
            "kiroMaskedDescription": masked_desc,
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
                        f"INCIDENCIA FUNCIONAL EN PRODUCCIÓN ({atm_id}): La tarjeta {masked_pan} ha quedado "
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
        "kiroValidationErrors": kiro_errors,
        "kiroMaskedDescription": masked_desc,
        "kiroScenePrompt": safe_prompt,
        "resolvedBy": "Agente Autónomo ALM (Hotfix PATCH-GTN-ATM-0420 Activo)",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    TARJETAS_BLOQUEADAS_LOG.insert(0, success_entry)
    return (
        jsonify(
            {
                "ok": True,
                "mensaje": (
                    f"Bloqueo preventivo completado con éxito en {atm_id}. Reverso ISO-8583 MTI 0420 "
                    f"({cod_reverso}) emitido, tarjeta liberada y token digital ({token_digital}) aprovisionado."
                ),
                "operacion": success_entry,
            }
        ),
        201,
    )


@app.route("/api/v1/observability/status", methods=["GET"])
def api_observability_status():
    """Devuelve el estado de AWS CloudWatch Alarms, CloudWatch Logs Insights y Prometheus OpenSource MCP."""
    sys_bug = SYSTEM_INCIDENT_STATE["systems_cloudwatch_bug_active"]
    atm_bug = SYSTEM_INCIDENT_STATE["atm_functional_bug_active"]

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
                "service": "atm-kiro-sentinel-edge",
                "message": "ATM-GTN-MAD-0042: Card 4548 **** **** 9012 trapped in reader slot; enable_emv_reversal_0420=False prevented MTI 0420 dispatch",
            },
        ]
        if (sys_bug or atm_bug)
        else [
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "INFO",
                "service": "getnet-card-blocker-svc",
                "message": "Hotfix PATCH-GTN-SYS-REDIS active: redis_lock_ttl_ms=1500, circuit_breaker=CLOSED, HikariPool active=4/32 (18.4%), P95=42.5ms",
            },
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "INFO",
                "service": "atm-kiro-sentinel-edge",
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
            "cloudwatch": {
                "region": "eu-west-1",
                "logGroups": ["/aws/ecs/getnet-card-blocker-svc", "/aws/lambda/atm-kiro-sentinel-edge"],
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
    """Exposición en formato nativo Prometheus / OpenMetrics para scraping de monitores OpenSource."""
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
        "# HELP getnet_atm_retained_cards_total Tarjetas retenidas sin reverso EMV en cajeros ATM",
        "# TYPE getnet_atm_retained_cards_total gauge",
        f'getnet_atm_retained_cards_total{{atm_id="ATM-GTN-MAD-0042",env="prod"}} {3 if atm_bug else 0}',
    ]
    return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")


@app.route("/api/v1/alm/inject-incidents", methods=["POST"])
def api_inject_incidents():
    """
    Inyecta en vivo las 2 incidencias de Producción para demostración ante el CIO de Getnet:
      1. Incidencia Funcional ATM (AWS_Kiro-main): Retención de tarjeta sin reverso EMV 0420 en ATM-GTN-MAD-0042.
      2. Incidencia de Sistemas (AWS CloudWatch + Prometheus MCP): Deadlock Redis (TTL=0) + Saturación HikariCP (98.5%).
    """
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

    AUTONOMOUS_ALM_STATE["overallStatus"] = "ALERTA CRÍTICA EN PRO · 2 INCIDENCIAS ACTIVAS (PENDIENTE AUTO-REMEDIACIÓN)"
    AUTONOMOUS_ALM_STATE["deployedRelease"] = "v2026.11.1-BROKEN-PRO"
    AUTONOMOUS_ALM_STATE["atmKiroDetail"]["status"] = "OPEN · DETECTED IN ATM-GTN-MAD-0042"
    AUTONOMOUS_ALM_STATE["cloudwatchSysDetail"]["status"] = "ALARM · FIRING IN AWS CLOUDWATCH & PROMETHEUS"

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
            "buildName": "🔥 INCIDENCIA EN PRODUCCIÓN DETECTADA (ATM-GTN-MAD-0042 + CloudWatch Alarm)",
            "runner": "AWS_Kiro ATM Sentinel + AWS CloudWatch / Prometheus MCP",
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
            "message": "Incidencias funcional (ATM Kiro) y de sistemas (CloudWatch/Prometheus) inyectadas en Producción.",
            "systemState": SYSTEM_INCIDENT_STATE,
            "autonomousAlm": AUTONOMOUS_ALM_STATE,
        }
    )


@app.route("/api/v1/alm/autonomous-cycle", methods=["POST"])
def api_autonomous_alm_cycle():
    """
    Ejecuta el Ciclo Completo ALM en Producción Sin Human-in-the-Loop:
      1. Detección desde ATM (AWS_Kiro-main) y desde Sistemas (AWS CloudWatch + Prometheus MCP).
      2. Triage automático con enmascarado PCI-DSS (redact_pan) y registro en Jira Xray.
      3. Análisis de Causa Raíz (RCA) sobre código y logs de producción.
      4. Re-Fixing autónomo (Hotfix EMV 0420 + Redis Lock TTL 1500ms & Circuit Breaker).
      5. Re-Deploy Canary (v2026.11.2-AUTONOMOUS-PRO) y verificación de los 14 casos en Jira Xray.
    """
    t0 = time.perf_counter()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Etapa 1 y 2: Ejecutar motor real AWS_Kiro-main para validar e inspeccionar la incidencia funcional del ATM
    raw_incident = {
        "atm_id": "ATM-GTN-MAD-0042",
        "ubicacion": "Sucursal Getnet Gran Vía 28, Madrid",
        "descripcion": (
            "Fallo funcional en cajero ATM-GTN-MAD-0042: La tarjeta Getnet 4548 1234 5678 9012 del titular "
            "Sr. Carlos Martínez quedó retenida en estado ERROR_TARJETA_RETENIDA_SIN_REVERSO."
        ),
        "fecha_hora": now_iso,
    }
    kiro_val_errors = validate_incident(raw_incident)
    pan_masked = redact_pan(raw_incident["descripcion"])
    safe_scene = scene_prompt(raw_incident)
    triage_obj = {
        "categoria": "TARJETA_RETENIDA",
        "severidad": "ALTA",
        "causa_probable": "Regresión en card_lock_engine: enable_emv_reversal_0420=False impide emitir reverso MTI 0420 y liberar obturador.",
        "accion_recomendada": "Activar reverso automático ISO-8583 0420, desbloquear eyección segura y emitir token digital en Wallet Getnet.",
    }
    triage_errors = validate_triage(triage_obj)

    # Etapa 3 y 4: Aplicar Re-Fixing autónomo en el estado del sistema de producción
    SYSTEM_INCIDENT_STATE.update(
        {
            "currentRelease": "v2026.11.2-AUTONOMOUS-PRO",
            "atm_functional_bug_active": False,
            "systems_cloudwatch_bug_active": False,
            "enable_emv_reversal_0420": True,
            "auto_issue_digital_token": True,
            "redis_lock_ttl_ms": 1500,
            "circuit_breaker_enabled": True,
            "redis_cache_enabled": True,
            "lastAutonomousRun": now_str,
            "autonomousCyclesCount": SYSTEM_INCIDENT_STATE.get("autonomousCyclesCount", 1) + 1,
        }
    )

    # Registrar operación de desbloqueo/reverso exitosa verificada tras el hotfix
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
            "resolvedBy": "Ciclo ALM Sin Human-in-the-Loop (PATCH-GTN-ATM-0420 + PATCH-GTN-SYS-REDIS)",
            "timestamp": now_str,
        },
    )

    # Etapa 5 y 6: Actualizar estado en Jira Xray Backlog y telemetría ejecutiva
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
            "overallStatus": "HEALTHY · 2/2 INCIDENCIAS RESUELTAS Y REDESPLEGADAS EN PRO",
            "deployedRelease": "v2026.11.2-AUTONOMOUS-PRO",
            "lastCycleTimestamp": now_str,
        }
    )
    AUTONOMOUS_ALM_STATE["atmKiroDetail"].update(
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
            "buildName": f"Build #{100 + len(EXECUTION_HISTORY) + 1} · Ciclo Completo ALM Zero-Touch (Auto-Fix & Re-Deploy PRO)",
            "runner": "Agente Autónomo ALM (AWS_Kiro + CloudWatch/Prometheus MCP + Jira Xray)",
            "environment": "PRODUCTION (v2026.11.2-AUTONOMOUS-PRO)",
            "testsScope": "GTN-INC-ATM-001 & GTN-INC-SYS-002 RESOLVED · 14/14 Xray Tests PASSED",
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
            "kiroValidationOk": len(kiro_val_errors) == 0 and len(triage_errors) == 0,
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
        }
    )


@app.route("/api/v1/qaops/test-runs", methods=["POST"])
def api_update_test_runs():
    """
    Recibe resultados de ejecución desde Pytest/Selenium o desde los Servidores MCP
    y actualiza en vivo el estado de los casos de prueba en el Backlog ALM (soporta GTN-TC-* y alias SCA-TC-*).
    """
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
        normalized_key = tc_key.replace("SCA-TC-", "GTN-TC-").replace("TL-SCA-", "TL-GTN-")
        new_status = res.get("status", "PASSED").upper()
        duration_ms = res.get("durationMs")
        if new_status == "PASSED":
            passed_cnt += 1
        else:
            failed_cnt += 1
        if duration_ms is not None:
            total_ms += int(duration_ms)

        for tc in alm_data.get("testCases", []):
            if tc.get("key") in (tc_key, normalized_key) or tc.get("legacyKey") == tc_key or tc.get("testLinkId") in (tc_key, normalized_key):
                tc["status"] = new_status
                if duration_ms is not None:
                    tc["lastExecutionTimeMs"] = int(duration_ms)
                updated_keys.append(tc["key"])

        for s_tc in SELENIUM_LATEST_REPORT.get("testCasesDetail", []):
            if s_tc.get("key") in (tc_key, normalized_key) or s_tc.get("testLinkId") in (tc_key, normalized_key):
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
                        "Suite Pytest + Selenium POM (E2E Getnet)"
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
                "buildName": f"Build #{100 + len(EXECUTION_HISTORY) + 1} · Performance Gate JMeter IA (Getnet)",
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
    """Lanza en vivo el Self-Test del Servidor MCP de Selenium y la suite Pytest + Selenium desde el Dashboard Jira."""
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
    """Lanza en vivo el Servidor MCP de Observabilidad (CloudWatch + Prometheus + AWS_Kiro) y ciclo autónomo ALM."""
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
    """Lanza en vivo la prueba de carga y análisis cognitivo JMeter IA desde el Dashboard ALM."""
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
        return send_file(TESTLINK_XML_PATH, as_attachment=True, download_name="getnet_testplan_testlink.xml")
    if fmt == "redmine":
        return send_file(REDMINE_CSV_PATH, as_attachment=True, download_name="getnet_redmine_issues_backlog.csv")
    return jsonify({"ok": False, "error": "Formato no soportado. Use jira-xray, testlink o redmine."}), 404


if __name__ == "__main__":
    port = int(os.environ.get("GETNET_PORT", os.environ.get("ADESLAS_PORT", "8080")))
    app.run(host="127.0.0.1", port=port, debug=False)
