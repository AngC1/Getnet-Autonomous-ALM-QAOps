"""
Orquestador Maestro QAOps & Autonomous Production ALM — Getnet (Grupo Santander).
Levanta el portal de Tarjetas Bancarias Getnet y el Cuadro de Mando Jira Xray (si no está ya activo) y ejecuta sin Human-in-the-Loop:
  1. Diagnóstico del Servidor MCP de Observabilidad (Dynatrace Davis AI + AWS CloudWatch + Prometheus + Motor RAG + AWS_Kiro ATM)
     y ejecución completa del ciclo de Auto-Remediación de las 2 incidencias de Producción (GTN-INC-ATM-001 y GTN-INC-SYS-002).
  2. Diagnóstico del Servidor MCP de Selenium (Self-Healing DOM + Flujos E2E de Tarjetas + Evidencia PNG).
  3. Suite completa Pytest + Selenium E2E de Tarjetas Bancarias (GTN-TC-001..010 y GTN-TC-013..014).
  4. Motor de Rendimiento JMeter Asistido por IA (GTN-TC-011 y GTN-TC-012).
  5. Certificación del Cuadro de Mando Ejecutivo en Jira Xray (14/14 Test Cases de Tarjetas PASSED y 2/2 Incidencias RESOLVED).
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
BASE_URL = "http://127.0.0.1:8080"


def is_portal_up() -> bool:
    try:
        r = requests.get(f"{BASE_URL}/api/v1/health", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


def main() -> int:
    server_proc = None
    try:
        if not is_portal_up():
            print("[1/5] Iniciando Simulador Portal Tarjetas Getnet y Hub ALM Jira Xray en http://127.0.0.1:8080 ...")
            server_proc = subprocess.Popen(
                [sys.executable, str(ROOT / "portal-getnet" / "app.py")],
                cwd=str(ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(25):
                if is_portal_up():
                    break
                time.sleep(0.3)
            if not is_portal_up():
                print("ERROR: No se pudo iniciar el servidor Getnet en el puerto 8080.")
                return 1
        else:
            print("[1/5] Portal Tarjetas Getnet detectado activo en http://127.0.0.1:8080")

        print("\n[2/5] Ejecutando Servidor MCP de Observabilidad (Dynatrace + CloudWatch + Prometheus + RAG + AWS_Kiro ATM) y Ciclo ALM Zero-Touch...")
        rc_obs = subprocess.call(
            [sys.executable, str(ROOT / "mcp-observability-server" / "server.py"), "--selftest"],
            cwd=str(ROOT),
        )
        if rc_obs != 0:
            return rc_obs

        print("\n[3/5] Ejecutando Self-Test del Servidor MCP de Selenium (Inspección DOM + Flujos de Tarjetas Bancarias + Bloqueo ATM)...")
        rc_mcp = subprocess.call(
            [sys.executable, str(ROOT / "mcp-selenium-server" / "server.py"), "--selftest"],
            cwd=str(ROOT),
        )
        if rc_mcp != 0:
            return rc_mcp

        print("\n[4/5] Ejecutando Suite Automatizada Pytest + Selenium POM de Tarjetas Bancarias (GTN-TC-001 .. GTN-TC-014)...")
        rc_pytest = subprocess.call(
            [sys.executable, "-m", "pytest", "selenium-qaops/tests/test_servicios_clientes_e2e.py", "-v"],
            cwd=str(ROOT),
        )
        if rc_pytest != 0:
            return rc_pytest

        print("\n[5/5] Ejecutando Prueba de Carga y Diagnóstico de Tarjetas con JMeter IA (GTN-TC-011 .. GTN-TC-012)...")
        rc_jmeter = subprocess.call(
            [sys.executable, str(ROOT / "jmeter-ai" / "ai_jmeter_assistant.py"), "--vus", "12", "--iterations", "5"],
            cwd=str(ROOT),
        )
        if rc_jmeter != 0:
            return rc_jmeter

        alm_resp = requests.get(f"{BASE_URL}/api/v1/alm/backlog", timeout=5).json()
        alm = alm_resp["backlog"]
        passed = sum(1 for tc in alm["testCases"] if tc["status"] == "PASSED")
        total = len(alm["testCases"])
        inc_resolved = sum(1 for inc in alm.get("productionIncidents", []) if "RESOLVED" in inc["status"])
        print("\n================================================================================")
        print(f"DEMO CIO GETNET CERTIFICADA: {passed}/{total} Test Cases de Tarjetas PASSED | {inc_resolved}/2 Incidencias PRO Resueltas")
        print(f" - Portal Operativo de Tarjetas y ATM : {BASE_URL}/servicios-para-clientes")
        print(f" - Cuadro de Mando CIO Jira Xray      : {BASE_URL}/alm-dashboard")
        print(f" - Presentación Ejecutiva CIO         : {BASE_URL}/presentacion")
        print("================================================================================")
        return 0
    finally:
        if server_proc is not None:
            server_proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
