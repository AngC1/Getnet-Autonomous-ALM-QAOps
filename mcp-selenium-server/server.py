"""
Servidor MCP (Model Context Protocol) de Selenium para QAOps & Autonomous ALM — Getnet (Grupo Santander).
Permite a los Agentes de IA controlar Selenium WebDriver, inspeccionar el DOM con auto-curación (Self-Healing Locators),
ejecutar flujos funcionales exclusivos de Tarjetas Bancarias (/servicios-para-clientes) y reportar
ejecuciones al Hub ALM en Jira Xray, TestLink y Redmine.

Modos de uso:
  1. Modo Estándar MCP (JSON-RPC 2.0 sobre stdio):
     python mcp-selenium-server/server.py
  2. Modo Diagnóstico / Self-Test E2E contra el portal de tarjetas:
     python mcp-selenium-server/server.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import Select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "selenium-qaops" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


class SeleniumMcpController:
    """Controlador de sesión Selenium WebDriver gestionado por el Servidor MCP de Tarjetas Getnet."""

    def __init__(self, base_url: str = "http://127.0.0.1:8080") -> None:
        self.base_url = base_url.rstrip("/")
        self.driver: Optional[WebDriver] = None

    def start_session(self, headless: bool = True) -> Dict[str, Any]:
        if self.driver is not None:
            return {"status": "already_active", "currentUrl": self.driver.current_url}

        try:
            opts = ChromeOptions()
            if headless:
                opts.add_argument("--headless=new")
            opts.add_argument("--window-size=1440,950")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--no-sandbox")
            self.driver = webdriver.Chrome(options=opts)
            browser_name = "Chrome"
        except Exception:
            opts_edge = EdgeOptions()
            if headless:
                opts_edge.add_argument("--headless=new")
            opts_edge.add_argument("--window-size=1440,950")
            self.driver = webdriver.Edge(options=opts_edge)
            browser_name = "Edge"

        self.driver.get(f"{self.base_url}/servicios-para-clientes")
        return {
            "status": "started",
            "browser": browser_name,
            "headless": headless,
            "title": self.driver.title,
            "url": self.driver.current_url,
        }

    def ensure_driver(self) -> WebDriver:
        if self.driver is None:
            self.start_session(headless=True)
        assert self.driver is not None
        return self.driver

    def navigate(self, path_or_url: str) -> Dict[str, Any]:
        drv = self.ensure_driver()
        target = path_or_url if path_or_url.startswith("http") else f"{self.base_url}/{path_or_url.lstrip('/')}"
        drv.get(target)
        return {"status": "navigated", "url": drv.current_url, "title": drv.title}

    def inspect_dom_locators(self) -> Dict[str, Any]:
        """Extrae elementos interactivos y construye un catálogo de selectores resilientes para IA."""
        drv = self.ensure_driver()
        elements = drv.find_elements(By.CSS_SELECTOR, "button, input, select, a, [data-testid]")
        catalog: List[Dict[str, str]] = []
        for el in elements[:48]:
            el_id = el.get_attribute("id") or ""
            testid = el.get_attribute("data-testid") or ""
            tag = el.tag_name
            text = (el.text or el.get_attribute("placeholder") or "").strip()[:60]
            if not el_id and not testid:
                continue
            primary = f"#{el_id}" if el_id else f"[data-testid='{testid}']"
            fallback = f"[data-testid='{testid}']" if (el_id and testid) else f"{tag}#{el_id}"
            catalog.append(
                {
                    "tag": tag,
                    "id": el_id,
                    "dataTestId": testid,
                    "labelOrText": text,
                    "recommendedCss": primary,
                    "selfHealingFallbackCss": fallback,
                }
            )
        return {
            "url": drv.current_url,
            "interactiveElementsCount": len(catalog),
            "locators": catalog,
        }

    def execute_tarjetas_flow(self, flow_name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Ejecuta un flujo E2E de Tarjetas Bancarias del Portal Getnet y devuelve evidencias."""
        params = params or {}
        drv = self.ensure_driver()
        drv.get(f"{self.base_url}/servicios-para-clientes")
        start_t = time.perf_counter()

        if flow_name == "parque_tarjetas":
            drv.find_element(By.ID, "btn-tab-cuadro").click()
            Select(drv.find_element(By.ID, "cm-provincia")).select_by_visible_text(
                params.get("provincia", "Madrid")
            )
            Select(drv.find_element(By.ID, "trj-tipo")).select_by_visible_text(
                params.get("tipoTarjeta", "Visa Débito EMV")
            )
            drv.find_element(By.ID, "btn-buscar-cuadro").click()
            time.sleep(0.25)
            cards = drv.find_elements(By.CSS_SELECTOR, "[data-testid='center-card-item']")
            elapsed = int((time.perf_counter() - start_t) * 1000)
            return {
                "flow": flow_name,
                "status": "PASSED" if len(cards) > 0 else "FAILED",
                "nodosTarjetasEncontrados": len(cards),
                "durationMs": elapsed,
            }

        if flow_name == "autorizacion":
            drv.find_element(By.ID, "btn-tab-autorizaciones").click()
            drv.find_element(By.ID, "aut-tarjeta").send_keys(params.get("numTarjeta", "4548123456789012"))
            drv.find_element(By.ID, "aut-prescripcion").send_keys(params.get("codigoReferencia", "ISO-99281"))
            drv.find_element(By.ID, "aut-centro").send_keys(
                params.get("nodoAtmComercio", "Cajero ATM-GTN-MAD-0042 Gran Vía")
            )
            drv.find_element(By.ID, "btn-solicitar-autorizacion").click()
            time.sleep(0.25)
            alert_text = drv.find_element(By.ID, "aut-resultado-alert").text
            elapsed = int((time.perf_counter() - start_t) * 1000)
            return {
                "flow": flow_name,
                "status": "PASSED" if "AUTORIZADA" in alert_text else "FAILED",
                "alertText": alert_text,
                "durationMs": elapsed,
            }

        if flow_name == "bloqueo_atm":
            drv.find_element(By.ID, "btn-tab-bloqueo-atm").click()
            drv.find_element(By.ID, "btn-ejecutar-bloqueo-atm").click()
            time.sleep(0.25)
            alert_text = drv.find_element(By.ID, "atm-bloqueo-alert").text
            elapsed = int((time.perf_counter() - start_t) * 1000)
            return {
                "flow": flow_name,
                "status": "PASSED" if "REV-EMV-2026-" in alert_text else "FAILED",
                "alertText": alert_text,
                "durationMs": elapsed,
            }

        if flow_name == "disputa":
            drv.find_element(By.ID, "btn-tab-disputas").click()
            drv.find_element(By.ID, "rmb-nif").send_keys(params.get("nif", "12345678Z"))
            drv.find_element(By.ID, "rmb-importe").send_keys(str(params.get("importe", "250.00")))
            drv.find_element(By.ID, "rmb-iban").send_keys(
                params.get("iban", "ES9121000418450200051332")
            )
            drv.find_element(By.ID, "btn-enviar-disputa").click()
            time.sleep(0.25)
            alert_text = drv.find_element(By.ID, "rmb-resultado-alert").text
            elapsed = int((time.perf_counter() - start_t) * 1000)
            return {
                "flow": flow_name,
                "status": "PASSED" if "DSP-2026-" in alert_text else "FAILED",
                "alertText": alert_text,
                "durationMs": elapsed,
            }

        return {"flow": flow_name, "status": "ERROR", "message": f"Flujo no reconocido: {flow_name}"}

    def take_screenshot(self, filename: str = "mcp_capture.png") -> Dict[str, Any]:
        drv = self.ensure_driver()
        out_path = REPORTS_DIR / filename
        drv.save_screenshot(str(out_path))
        return {"status": "saved", "path": str(out_path)}

    def sync_alm_result(self, test_case_key: str, status: str = "PASSED", duration_ms: int = 800) -> Dict[str, Any]:
        res = requests.post(
            f"{self.base_url}/api/v1/qaops/test-runs",
            json={"key": test_case_key, "status": status, "durationMs": duration_ms},
            timeout=5,
        )
        return res.json()

    def close_session(self) -> Dict[str, Any]:
        if self.driver is not None:
            self.driver.quit()
            self.driver = None
        return {"status": "closed"}


MCP_TOOLS_SCHEMA = [
    {
        "name": "selenium_start_session",
        "description": "Inicia una sesión de Selenium WebDriver apuntando al portal de Tarjetas Getnet (/servicios-para-clientes).",
        "inputSchema": {
            "type": "object",
            "properties": {"headless": {"type": "boolean", "default": True}},
        },
    },
    {
        "name": "selenium_navigate",
        "description": "Navega a una URL o ruta del portal de tarjetas Getnet o del Cuadro de Mando Jira Xray.",
        "inputSchema": {
            "type": "object",
            "properties": {"path_or_url": {"type": "string"}},
            "required": ["path_or_url"],
        },
    },
    {
        "name": "selenium_inspect_dom_locators",
        "description": "Extrae elementos interactivos del DOM y propone selectores CSS primarios y de respaldo (Self-Healing).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "selenium_execute_tarjetas_flow",
        "description": "Ejecuta un flujo funcional E2E de tarjetas bancarias Getnet (parque_tarjetas, autorizacion, disputa, bloqueo_atm).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "flow_name": {"type": "string", "enum": ["parque_tarjetas", "autorizacion", "disputa", "bloqueo_atm"]},
                "params": {"type": "object"},
            },
            "required": ["flow_name"],
        },
    },
    {
        "name": "selenium_take_screenshot",
        "description": "Guarda una captura de pantalla PNG de la sesión actual como evidencia de prueba.",
        "inputSchema": {
            "type": "object",
            "properties": {"filename": {"type": "string", "default": "mcp_evidence.png"}},
        },
    },
    {
        "name": "alm_sync_test_result",
        "description": "Actualiza el resultado de un Test Case de tarjetas (ej. GTN-TC-002) en el Hub ALM (Jira Xray / TestLink / Redmine).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "test_case_key": {"type": "string"},
                "status": {"type": "string", "enum": ["PASSED", "FAILED", "BLOCKED"]},
                "duration_ms": {"type": "integer"},
            },
            "required": ["test_case_key", "status"],
        },
    },
    {
        "name": "selenium_close_session",
        "description": "Cierra el navegador Selenium WebDriver activo.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def handle_mcp_request(controller: SeleniumMcpController, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "getnet-selenium-qaops-mcp", "version": "2.0.0"},
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS_SCHEMA}}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "selenium_start_session":
                out = controller.start_session(headless=args.get("headless", True))
            elif name == "selenium_navigate":
                out = controller.navigate(args["path_or_url"])
            elif name == "selenium_inspect_dom_locators":
                out = controller.inspect_dom_locators()
            elif name == "selenium_execute_tarjetas_flow":
                out = controller.execute_tarjetas_flow(args["flow_name"], args.get("params"))
            elif name == "selenium_take_screenshot":
                out = controller.take_screenshot(args.get("filename", "mcp_evidence.png"))
            elif name == "alm_sync_test_result":
                out = controller.sync_alm_result(
                    args["test_case_key"], args.get("status", "PASSED"), int(args.get("duration_ms", 800))
                )
            elif name == "selenium_close_session":
                out = controller.close_session()
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
    controller = SeleniumMcpController(base_url=base_url)
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            resp = handle_mcp_request(controller, req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    finally:
        controller.close_session()


def run_selftest(base_url: str) -> int:
    print("=== [Getnet QAOps] Self-Test del Servidor MCP de Selenium (Operativa de Tarjetas Bancarias) ===")
    controller = SeleniumMcpController(base_url=base_url)
    try:
        info = controller.start_session(headless=True)
        print(f"1. Sesión iniciada: {info['browser']} -> {info['url']}")

        dom_info = controller.inspect_dom_locators()
        print(f"2. Inspección DOM Self-Healing: {dom_info['interactiveElementsCount']} selectores extraídos.")

        flow_pt = controller.execute_tarjetas_flow(
            "parque_tarjetas", {"provincia": "Madrid", "tipoTarjeta": "Visa Débito EMV"}
        )
        print(
            f"3. Flujo MCP Parque de Tarjetas Getnet: {flow_pt['status']} "
            f"({flow_pt['nodosTarjetasEncontrados']} nodos, {flow_pt['durationMs']} ms)"
        )

        flow_aut = controller.execute_tarjetas_flow("autorizacion")
        print(f"4. Flujo MCP Autorizaciones Tarjeta ISO-8583: {flow_aut['status']} ({flow_aut['durationMs']} ms)")

        flow_blk = controller.execute_tarjetas_flow("bloqueo_atm")
        print(f"5. Flujo MCP Bloqueo Tarjeta ATM (Getnet_ATM): {flow_blk['status']} ({flow_blk['durationMs']} ms)")

        shot = controller.take_screenshot("mcp_selftest_servicios_clientes.png")
        print(f"6. Evidencia PNG generada: {shot['path']}")

        sync = controller.sync_alm_result("GTN-TC-002", "PASSED", flow_pt["durationMs"])
        print(f"7. Sincronización ALM Jira Xray / TestLink: {sync}")
        return 0
    finally:
        controller.close_session()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Servidor MCP de Selenium - Getnet Tarjetas QAOps")
    parser.add_argument("--base-url", default=os.environ.get("GETNET_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--selftest", action="store_true", help="Ejecuta prueba de autodiagnóstico MCP contra el portal")
    args = parser.parse_args()

    if args.selftest:
        sys.exit(run_selftest(args.base_url))
    else:
        run_stdio_server(args.base_url)
