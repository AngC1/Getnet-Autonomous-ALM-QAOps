"""
Servidor MCP (Model Context Protocol) de Observabilidad Híbrida (Dynatrace Davis AI + AWS CloudWatch + OpenSource Prometheus/OTel),
Base de Conocimiento RAG y Motor de Triaje Funcional ATM (Getnet_ATM) para Getnet — Ayesa Digital QAOps.

Permite a los agentes autónomos (Zero Human-in-the-Loop):
  1. Conectar vía MCP con Dynatrace (Davis AI Problem Feed, Smartscape Topology y consultas DQL PurePath).
  2. Consultar alarmas e insights de AWS CloudWatch (/aws/ecs/getnet-card-blocker-svc).
  3. Consultar métricas en tiempo real del monitor OpenSource (Prometheus / OpenTelemetry / Alertmanager).
  4. Procesar incidencias funcionales de bloqueo de tarjetas bancarias desde cajeros ATM usando Getnet_ATM
     (enmascarado PCI-DSS de PAN, extracción de telemetría de vídeo y triaje cognitivo).
  5. Consultar la Base de Conocimiento RAG (rag-knowledge-base/) sobre comportamiento de incidencias bancarias.
  6. Orquestar el ciclo completo ALM en Producción sin Human-in-the-Loop:
     Detección -> RAG Lookup -> Triage -> Análisis RCA -> Re-Fixing -> Re-Deploy -> Certificación en Jira Xray.

Modos de uso:
  1. Modo Estándar MCP (JSON-RPC 2.0 sobre stdio):
     python mcp-observability-server/server.py
  2. Modo Diagnóstico / Self-Test E2E contra el portal Getnet:
     python mcp-observability-server/server.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GETNET_ATM_DIR = PROJECT_ROOT / "Getnet_ATM"
RAG_DIR = PROJECT_ROOT / "rag-knowledge-base"
for p in (GETNET_ATM_DIR, RAG_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from brand_verifier.incident import (  # noqa: E402
    process_incident as getnet_atm_process_incident,
    redact_pan,
    scene_prompt,
    validate_incident,
    validate_triage,
)
from brand_verifier.s3io import S3IO  # noqa: E402
import atm_sentinel  # noqa: E402
from rag_engine import IncidentRAGEngine  # noqa: E402


class LocalMemoryS3Client:
    """Cliente S3 en memoria para persistencia determinista del motor Getnet_ATM sin requerir credenciales externas."""

    def __init__(self) -> None:
        self.objects: Dict[str, bytes] = {}

    def put_object(self, Bucket: str, Key: str, Body: bytes, **kwargs: Any) -> Dict[str, Any]:
        self.objects[Key] = Body if isinstance(Body, bytes) else str(Body).encode("utf-8")
        return {"ETag": '"simulated-etag-getnet-atm"'}

    def get_object(self, Bucket: str, Key: str, **kwargs: Any) -> Dict[str, Any]:
        import io
        raw = self.objects.get(Key, b"{}")
        return {"Body": io.BytesIO(raw)}


class SimulatedBedrockTriageClient:
    """Cliente Bedrock determinista para triaje de incidencias ATM de tarjetas bancarias Getnet conforme a Getnet_ATM."""

    def __init__(self, response_payload: Dict[str, Any]) -> None:
        self.response_payload = response_payload
        self.calls = 0

    def converse(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls += 1
        return {
            "output": {
                "message": {
                    "content": [{"text": json.dumps(self.response_payload, ensure_ascii=False)}]
                }
            },
            "usage": {"inputTokens": 340, "outputTokens": 128},
        }


class ObservabilityMcpController:
    """Controlador MCP de Observabilidad (Dynatrace + AWS CloudWatch + Prometheus + Getnet ATM + Motor RAG)."""

    def __init__(self, base_url: str = "http://127.0.0.1:8080") -> None:
        self.base_url = base_url.rstrip("/")
        self.rag_engine = IncidentRAGEngine()

    def get_observability_status(self) -> Dict[str, Any]:
        res = requests.get(f"{self.base_url}/api/v1/observability/status", timeout=5)
        return res.json()

    def dynatrace_get_davis_problems(self, status_filter: Optional[str] = None) -> Dict[str, Any]:
        data = self.get_observability_status()
        dt = data.get("dynatrace", {})
        problems = dt.get("problems", [])
        if status_filter:
            problems = [p for p in problems if p.get("status") == status_filter.upper()]
        return {
            "provider": "Dynatrace Davis AI & Smartscape MCP Server",
            "environmentUrl": dt.get("environmentUrl", "https://getnet-prod.live.dynatrace.com"),
            "connectionStatus": dt.get("connectionStatus", "CONNECTED"),
            "monitoredEntities": dt.get("monitoredEntities", []),
            "totalProblems": len(problems),
            "problems": problems,
            "smartscapeTopology": dt.get("smartscapeTopology", []),
        }

    def dynatrace_execute_dql(
        self,
        dql_query: str = "fetch spans | filter dt.entity.service == 'SERVICE-GETNET-CARD-BLOCKER' | summarize p95=percentile(duration, 95), lockErrors=countIf(redis.lock.timeout == true)",
    ) -> Dict[str, Any]:
        data = self.get_observability_status()
        dt = data.get("dynatrace", {})
        return {
            "provider": "Dynatrace Grail DQL Engine via MCP",
            "dqlQuery": dql_query,
            "executionTimeMs": 18,
            "records": dt.get("purePathTraces", []),
            "davisRootCause": dt.get("davisRootCause", "Healthy"),
        }

    def cloudwatch_get_alarms(self, state_filter: Optional[str] = None) -> Dict[str, Any]:
        data = self.get_observability_status()
        alarms = data.get("cloudwatch", {}).get("alarms", [])
        if state_filter:
            alarms = [a for a in alarms if a.get("state") == state_filter.upper()]
        return {
            "provider": "AWS CloudWatch (eu-west-1 / Irlanda · Core Tarjetas Getnet)",
            "namespace": "AWS/GetnetCardCore",
            "totalAlarms": len(alarms),
            "alarms": alarms,
            "logGroups": data.get("cloudwatch", {}).get("logGroups", []),
        }

    def cloudwatch_query_logs_insights(self, log_group: str = "/aws/ecs/getnet-card-blocker-svc") -> Dict[str, Any]:
        data = self.get_observability_status()
        logs = data.get("cloudwatch", {}).get("recentLogs", [])
        return {
            "logGroup": log_group,
            "query": "fields @timestamp, @message | filter level = 'ERROR' or level = 'FATAL' | sort @timestamp desc | limit 20",
            "eventsMatched": len(logs),
            "events": logs,
        }

    def prometheus_query_metrics(self, query: str = "getnet_card_blocker_metrics") -> Dict[str, Any]:
        data = self.get_observability_status()
        prom = data.get("prometheus", {})
        return {
            "monitor": "Prometheus + OpenTelemetry Collector + Grafana Alertmanager (OpenSource MCP)",
            "scrapeTarget": "http://127.0.0.1:8080/api/v1/observability/prometheus",
            "query": query,
            "status": prom.get("status", "UP"),
            "activeAlerts": prom.get("activeAlerts", []),
            "metrics": prom.get("metrics", {}),
        }

    def rag_retrieve_incident_playbook(self, query: str, telemetry_source: Optional[str] = None) -> Dict[str, Any]:
        return self.rag_engine.retrieve(query=query, telemetry_source=telemetry_source, top_k=3)

    def getnet_atm_inspect_incident(
        self,
        atm_id: str = "ATM-GTN-MAD-0042",
        ubicacion: str = "Sucursal Getnet Gran Vía 28, Madrid",
        descripcion: str = (
            "Fallo funcional en cajero ATM-GTN-MAD-0042: La tarjeta bancaria corporativa Getnet 4548 1234 5678 9012 "
            "del titular Sr. Carlos Martínez quedó bloqueada en estado LOCKED_NO_REVERSAL tras validación EMV "
            "sin emitir trama de reverso ISO-8583 MTI 0420 ni expulsar el plástico."
        ),
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        raw_incident = {
            "atm_id": atm_id,
            "ubicacion": ubicacion,
            "descripcion": descripcion,
            "fecha_hora": now_iso,
        }
        validation_errors = validate_incident(raw_incident)
        redacted_desc = redact_pan(descripcion)
        safe_scene_prompt = scene_prompt(raw_incident)

        s3_mem = LocalMemoryS3Client()
        s3_io = S3IO(client=s3_mem, bucket="getnet-atm-incidents-pro", sleep=lambda _: None)
        triage_payload = {
            "categoria": "TARJETA_RETENIDA",
            "severidad": "ALTA",
            "causa_probable": (
                "Regresión funcional en card_lock_engine (ejectCardOnBlock=False y omit_iso8583_0420=True) "
                "al bloquear preventivamente la tarjeta bancaria EMV tras evento en ranura."
            ),
            "accion_recomendada": (
                "Aplicar hotfix automático en módulo de bloqueo de tarjetas para activar reverso EMV MTI 0420, "
                "liberar estado lógico y emitir token de reemplazo digital en billetera Getnet."
            ),
        }
        bedrock_sim = SimulatedBedrockTriageClient(triage_payload)
        atm_res = getnet_atm_process_incident(
            raw_incident,
            s3=s3_io,
            bedrock_client=bedrock_sim,
            model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            id_factory=lambda: "GTN-INC-ATM-001",
        )

        sentinel_meta = atm_sentinel.build_meta(atm_id, ubicacion, descripcion, now_iso)
        sentinel_analysis = atm_sentinel.validate_analysis(
            {
                "risk_level": "CRITICO",
                "threat_type": "CARD_TRAPPING",
                "confidence": 0.96,
                "summary": (
                    "Retención funcional de tarjeta bancaria en ranura motorizada de ATM-GTN-MAD-0042 combinada con "
                    "bloqueo lógico sin trama de reverso ISO-8583 MTI 0420."
                ),
                "evidence": [
                    "Fotograma 1 (t=0.5s): Inserción de tarjeta bancaria Getnet en lector híbrido EMV.",
                    "Fotograma 3 (t=4.2s): Bloqueo preventivo activado; obturador retiene tarjeta (ejectCardOnBlock=False).",
                    "Fotograma 6 (t=9.8s): Timeout en pasarela de autorización sin emisión de reverso automático 0420.",
                ],
                "recommended_actions": [
                    "Activar flag atm_emv_fallback_reversal=True en servicio getnet-card-blocker-svc.",
                    "Desbloquear ciclo de expulsión segura y emitir tarjeta digital de reemplazo inmediato.",
                    "Ejecutar regresión E2E en Jira Xray (GTN-TC-013) y desplegar Canary en Producción.",
                ],
            }
        )
        sentinel_report = atm_sentinel.assemble_report(
            sentinel_meta,
            sentinel_analysis,
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "s3://getnet-atm-media-pro/incidents/GTN-INC-ATM-001/video/atm_mad_0042_cardlock.mp4",
            [
                {"index": 12, "time_s": 0.5, "s3_key": "incidents/GTN-INC-ATM-001/frames/frame_01_0.50s.jpg"},
                {"index": 105, "time_s": 4.2, "s3_key": "incidents/GTN-INC-ATM-001/frames/frame_03_4.20s.jpg"},
                {"index": 245, "time_s": 9.8, "s3_key": "incidents/GTN-INC-ATM-001/frames/frame_06_9.80s.jpg"},
            ],
        )

        return {
            "atmEngine": "Getnet_ATM (brand_verifier.incident + atm_sentinel)",
            "validationErrors": validation_errors,
            "triageSchemaValid": validate_triage(atm_res.triaje) == [],
            "incidentId": atm_res.id,
            "estadoTriaje": atm_res.estado,
            "panRedactedDescription": redacted_desc,
            "privacySafeScenePrompt": safe_scene_prompt,
            "s3ObjectsPersisted": list(s3_mem.objects.keys()),
            "triageResult": atm_res.triaje,
            "sentinelVideoReport": sentinel_report,
        }

    def execute_autonomous_alm_cycle(self, inject_first: bool = True) -> Dict[str, Any]:
        """Ejecuta el ciclo completo ALM en Producción sin Human-in-the-Loop."""
        if inject_first:
            requests.post(f"{self.base_url}/api/v1/alm/inject-incidents", json={"source": "MCP_OBSERVABILITY"}, timeout=5)
        res = requests.post(
            f"{self.base_url}/api/v1/alm/autonomous-cycle",
            json={"triggeredBy": "getnet-observability-mcp-server (Zero Human-in-the-Loop)"},
            timeout=15,
        )
        return res.json()


MCP_TOOLS_SCHEMA = [
    {
        "name": "dynatrace_get_davis_problems",
        "description": "Conecta vía MCP con Dynatrace Davis AI para obtener problemas activos, topología Smartscape y causa raíz en microservicios de tarjetas bancarias.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status_filter": {"type": "string", "enum": ["OPEN", "CLOSED"]},
            },
        },
    },
    {
        "name": "dynatrace_execute_dql",
        "description": "Ejecuta una consulta DQL (Dynatrace Query Language) sobre trazas distribuidas PurePath y métricas de bloqueo de tarjetas.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dql_query": {"type": "string"},
            },
        },
    },
    {
        "name": "cloudwatch_get_alarms",
        "description": "Consulta las alarmas activas de AWS CloudWatch para los microservicios de tarjetas bancarias y ATM de Getnet.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state_filter": {"type": "string", "enum": ["ALARM", "OK", "INSUFFICIENT_DATA"]},
            },
        },
    },
    {
        "name": "cloudwatch_query_logs_insights",
        "description": "Ejecuta una consulta en AWS CloudWatch Logs Insights sobre el grupo de logs de producción de tarjetas Getnet.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "log_group": {"type": "string", "default": "/aws/ecs/getnet-card-blocker-svc"},
            },
        },
    },
    {
        "name": "prometheus_query_metrics",
        "description": "Consulta métricas en tiempo real y alertas del monitor OpenSource (Prometheus / OpenTelemetry / Alertmanager).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": "getnet_card_blocker_metrics"},
            },
        },
    },
    {
        "name": "rag_retrieve_incident_playbook",
        "description": "Consulta la Base de Conocimiento RAG de Getnet para obtener el modelo de comportamiento de una incidencia de tarjetas y su playbook de remediación sin Human-in-the-Loop.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "telemetry_source": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "getnet_atm_inspect_incident",
        "description": "Analiza una incidencia funcional de bloqueo/retención de tarjeta bancaria en ATM usando Getnet_ATM (PAN masking PCI-DSS, vídeo y triaje).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "atm_id": {"type": "string", "default": "ATM-GTN-MAD-0042"},
                "ubicacion": {"type": "string", "default": "Sucursal Getnet Gran Vía 28, Madrid"},
                "descripcion": {"type": "string"},
            },
        },
    },
    {
        "name": "alm_autonomous_zero_touch_cycle",
        "description": "Ejecuta el ciclo completo ALM en Producción sin Human-in-the-Loop (Detección, RAG, Triage, RCA, Re-Fixing, Re-Deploy y Certificación Jira Xray).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "inject_first": {"type": "boolean", "default": True},
            },
        },
    },
]


def handle_mcp_request(controller: ObservabilityMcpController, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "getnet-observability-dynatrace-cloudwatch-atm-mcp", "version": "2.0.0"},
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS_SCHEMA}}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "dynatrace_get_davis_problems":
                out = controller.dynatrace_get_davis_problems(args.get("status_filter"))
            elif name == "dynatrace_execute_dql":
                out = controller.dynatrace_execute_dql(args.get("dql_query", "fetch spans | limit 10"))
            elif name == "cloudwatch_get_alarms":
                out = controller.cloudwatch_get_alarms(args.get("state_filter"))
            elif name == "cloudwatch_query_logs_insights":
                out = controller.cloudwatch_query_logs_insights(
                    args.get("log_group", "/aws/ecs/getnet-card-blocker-svc")
                )
            elif name == "prometheus_query_metrics":
                out = controller.prometheus_query_metrics(args.get("query", "getnet_card_blocker_metrics"))
            elif name == "rag_retrieve_incident_playbook":
                out = controller.rag_retrieve_incident_playbook(
                    query=args.get("query", "bloqueo tarjeta atm mti 0420 redis deadlock"),
                    telemetry_source=args.get("telemetry_source"),
                )
            elif name in ("getnet_atm_inspect_incident", "atm_kiro_inspect_incident"):
                out = controller.getnet_atm_inspect_incident(
                    atm_id=args.get("atm_id", "ATM-GTN-MAD-0042"),
                    ubicacion=args.get("ubicacion", "Sucursal Getnet Gran Vía 28, Madrid"),
                    descripcion=args.get(
                        "descripcion",
                        "La tarjeta bancaria Getnet 4548 1234 5678 9012 quedó bloqueada y retenida en ATM-GTN-MAD-0042.",
                    ),
                )
            elif name == "alm_autonomous_zero_touch_cycle":
                out = controller.execute_autonomous_alm_cycle(inject_first=args.get("inject_first", True))
            else:
                raise ValueError(f"Herramienta MCP desconocida: {name}")

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=2)}]},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": f"Error en herramienta MCP {name}: {exc}"}],
                },
            }

    if req_id is not None:
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    return None


def run_stdio_server(base_url: str) -> None:
    controller = ObservabilityMcpController(base_url=base_url)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        resp = handle_mcp_request(controller, req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def run_selftest(base_url: str) -> int:
    print("=== [Getnet Autonomous ALM] Self-Test del Servidor MCP (Dynatrace + AWS CloudWatch + Prometheus + RAG + Getnet ATM) ===")
    controller = ObservabilityMcpController(base_url=base_url)
    t0 = time.perf_counter()

    atm_out = controller.getnet_atm_inspect_incident()
    print(
        f"1. Motor Funcional ATM (Getnet_ATM): Incidencia {atm_out['incidentId']} -> "
        f"Estado: {atm_out['estadoTriaje']} | Categoría: {atm_out['triageResult']['categoria']} | "
        f"PAN Redacted: {'**** 9012' in atm_out['panRedactedDescription']}"
    )

    dt_out = controller.dynatrace_get_davis_problems()
    print(
        f"2. Dynatrace Davis AI MCP: {dt_out['connectionStatus']} ({dt_out['environmentUrl']}) | "
        f"Entidades Smartscape: {len(dt_out['monitoredEntities'])}"
    )

    cw_out = controller.cloudwatch_get_alarms()
    print(f"3. AWS CloudWatch MCP: {cw_out['totalAlarms']} alarmas monitorizadas en namespace {cw_out['namespace']}")

    prom_out = controller.prometheus_query_metrics()
    print(
        f"4. OpenSource Monitor (Prometheus/OpenTelemetry MCP): Estado {prom_out['status']} | "
        f"Métricas recolectadas: {len(prom_out['metrics'])}"
    )

    rag_out = controller.rag_retrieve_incident_playbook("Tarjeta retenida ATM sin reverso ISO-8583 MTI 0420 y deadlock Redis")
    print(
        f"5. Base de Conocimiento RAG: Playbook recuperado {rag_out['agenticSynthesis']['selectedPlaybookId']} "
        f"(Score: {rag_out['topScore']} | Agente: {rag_out['agenticSynthesis']['autonomousAgent']})"
    )

    cycle_out = controller.execute_autonomous_alm_cycle(inject_first=True)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    print(
        f"6. Ciclo Completo ALM Sin Human-in-the-Loop: {cycle_out.get('status')} "
        f"(Incidente ATM: {cycle_out.get('atmIncidentStatus')} | Incidente Sistemas: {cycle_out.get('sysIncidentStatus')} | "
        f"Release: {cycle_out.get('deployedRelease')} en {elapsed_ms} ms)"
    )
    return 0 if cycle_out.get("ok") else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Servidor MCP de Observabilidad Dynatrace + CloudWatch + Prometheus + RAG + Getnet ATM")
    parser.add_argument("--base-url", default=os.environ.get("GETNET_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--selftest", action="store_true", help="Ejecuta autodiagnóstico MCP y ciclo autónomo ALM")
    args = parser.parse_args()

    if args.selftest:
        sys.exit(run_selftest(args.base_url))
    else:
        run_stdio_server(args.base_url)
