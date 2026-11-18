"""
Suite Automatizada E2E (Selenium WebDriver + Pytest + Autonomous ALM + Motor RAG)
exclusiva para Operativa de Tarjetas Bancarias de Getnet (Grupo Santander).
Mapeada 1:1 con el Backlog ALM en Jira Xray (GTN-TC-001..010, GTN-TC-013..014),
TestLink (TL-GTN-101..114) y Redmine (#5001..5006).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pages.servicios_clientes_page import ServiciosClientesPage


@pytest.mark.xray("GTN-TC-001")
def test_tc001_catalogo_servicios_tarjetas_bancarias(driver, base_url):
    """GTN-TC-001 / TL-GTN-101: Renderizado del catálogo de los 6 módulos de tarjetas bancarias Getnet y KPIs."""
    page = ServiciosClientesPage(driver, base_url).open()
    hero_low = page.get_hero_title().lower()
    assert "getnet" in hero_low and "tarjetas" in hero_low
    assert page.get_service_cards_count() == 6


@pytest.mark.xray("GTN-TC-002")
def test_tc002_busqueda_parque_tarjetas_madrid_visa_emv(driver, base_url):
    """GTN-TC-002 / TL-GTN-102: Búsqueda de Parque de Tarjetas Bancarias en Madrid para Visa Débito EMV."""
    page = ServiciosClientesPage(driver, base_url).open()
    total = page.buscar_parque_tarjetas(provincia="Madrid", tipo_tarjeta="Visa Débito EMV")
    assert total >= 2


@pytest.mark.xray("GTN-TC-003")
def test_tc003_busqueda_guardia_24h_red_euro6000(driver, base_url):
    """GTN-TC-003 / TL-GTN-103: Búsqueda de centros de Guardia ATM 24h en programa Red Euro6000 ATM."""
    page = ServiciosClientesPage(driver, base_url).open()
    total = page.buscar_parque_tarjetas(
        tipo_tarjeta="Guardia ATM 24h (Bloqueo Preventivo)",
        programa="Red Euro6000 ATM",
    )
    assert total >= 2


@pytest.mark.xray("GTN-TC-004")
def test_tc004_autorizacion_tarjeta_iso8583_exitosa(driver, base_url):
    """GTN-TC-004 / TL-GTN-104: Autorización online ISO-8583 exitosa con PAN de tarjeta válido."""
    page = ServiciosClientesPage(driver, base_url).open()
    resultado = page.solicitar_autorizacion_tarjeta(
        num_tarjeta="4548123456789012",
        tipo_operacion_visible="Autorización Compra TPV Chip EMV (MTI 0100)",
        codigo_referencia="ISO-99281",
        nodo_atm_comercio="Cajero ATM-GTN-MAD-0042 Gran Vía",
    )
    assert "AUTORIZADA" in resultado
    assert "AUT-2026-" in resultado


@pytest.mark.xray("GTN-TC-005")
def test_tc005_autorizacion_pan_tarjeta_invalido(driver, base_url):
    """GTN-TC-005 / TL-GTN-105: Validación negativa de Autorización con PAN de tarjeta inválido."""
    page = ServiciosClientesPage(driver, base_url).open()
    resultado = page.solicitar_autorizacion_tarjeta(
        num_tarjeta="12345",
        tipo_operacion_visible="Retirada de Efectivo en Cajero ATM",
        codigo_referencia="ATM-1102",
        nodo_atm_comercio="Cajero ATM-GTN-MAD-0042",
    )
    assert "Error en validación de tarjeta" in resultado
    assert "12 y 16 dígitos" in resultado


@pytest.mark.xray("GTN-TC-006")
def test_tc006_autorizacion_tarjeta_auditoria_antifraude(base_url):
    """GTN-TC-006 / TL-GTN-106: Operación internacional de tarjeta derivada a Control de Riesgos & Antifraude."""
    res = requests.post(
        f"{base_url}/api/v1/tarjetas/autorizaciones",
        json={
            "numTarjeta": "4548123456789012",
            "tipoOperacion": "Operación Internacional de Alto Riesgo (Auditoría Antifraude)",
            "codigoReferencia": "RISK-55019",
            "nodoAtmComercio": "Hub Internacional Tarjetas Getnet",
        },
        timeout=5,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["ok"] is True
    assert data["autorizacion"]["estado"] == "PENDIENTE_REVISION_RIESGOS"


@pytest.mark.xray("GTN-TC-007")
def test_tc007_disputa_chargeback_tarjeta_abono_90(driver, base_url):
    """GTN-TC-007 / TL-GTN-107: Registro de Disputa / Chargeback de tarjeta con abono provisional del 90%."""
    page = ServiciosClientesPage(driver, base_url).open()
    resultado = page.registrar_disputa_tarjeta(
        nif="12345678Z",
        programa_visible="Getnet Corporate Premier (90% Abono Provisional)",
        importe="250.00",
        iban="ES9121000418450200051332",
    )
    assert "DSP-2026-" in resultado
    assert "225.00 EUR" in resultado


@pytest.mark.xray("GTN-TC-008")
def test_tc008_disputa_chargeback_iban_invalido(driver, base_url):
    """GTN-TC-008 / TL-GTN-108: Validación de IBAN incorrecto en solicitud de Disputa / Chargeback de tarjeta."""
    page = ServiciosClientesPage(driver, base_url).open()
    resultado = page.registrar_disputa_tarjeta(
        nif="12345678Z",
        programa_visible="Getnet Tarjeta Estándar (80% Abono Provisional)",
        importe="120.00",
        iban="ES1234",
    )
    assert "Error en disputa de tarjeta" in resultado
    assert "IBAN" in resultado


@pytest.mark.xray("GTN-TC-009")
def test_tc009_login_titular_wallet_tarjeta_digital(driver, base_url):
    """GTN-TC-009 / TL-GTN-109: Acceso al Área Titular de Tarjetas y visualización de Tarjeta Digital Tokenizada."""
    page = ServiciosClientesPage(driver, base_url).open()
    resultado = page.login_area_titular("12345678Z", "Getnet2026!")
    assert "Carlos Martínez Gómez" in resultado
    assert "CTR-GTN-908122" in resultado
    assert "4548123456789012" in resultado


@pytest.mark.xray("GTN-TC-010")
def test_tc010_soporte_criptografico_emv_hsm_24h(driver, base_url):
    """GTN-TC-010 / TL-GTN-110: Reserva de Sesión de Soporte Criptográfico EMV y HSM Thales 24h."""
    page = ServiciosClientesPage(driver, base_url).open()
    resultado = page.solicitar_soporte_tarjetas(
        unidad_visible="Criptografía EMV & HSM Thales (24h)",
        motivo="Verificación de criptograma ARQC y reverso MTI 0420 en tarjeta corporativa",
    )
    assert "SOP-2026-" in resultado
    assert "Ing. Patricia Navarro Solís" in resultado


@pytest.mark.xray("GTN-TC-013")
def test_tc013_incidencia_funcional_tarjeta_getnet_atm_autofix(driver, base_url):
    """
    GTN-TC-013 / TL-GTN-113: Ciclo completo de Incidencia Funcional de Bloqueo de Tarjeta desde ATM (Getnet_ATM)
    -> Detección (HTTP 409) -> Consulta Playbook RAG-PB-ATM-001 -> Auto-Fix EMV 0420 -> Verificación UI/API (HTTP 201).
    """
    inj = requests.post(f"{base_url}/api/v1/alm/inject-incidents", timeout=5)
    assert inj.status_code == 200

    res_fail = requests.post(
        f"{base_url}/api/v1/tarjetas/bloqueo",
        json={
            "numTarjeta": "4548 1234 5678 9012",
            "atmId": "ATM-GTN-MAD-0042",
            "ubicacion": "Sucursal Getnet Gran Vía 28, Madrid",
            "motivoBloqueo": "SOSPECHA_SKIMMING_RANURA",
        },
        timeout=5,
    )
    assert res_fail.status_code == 409
    fail_json = res_fail.json()
    assert fail_json["incidentKey"] == "GTN-INC-ATM-001"
    assert "9012" in fail_json["operacion"]["panEnmascarado"]
    assert "4548 1234" not in fail_json["operacion"]["panEnmascarado"]

    auto_res = requests.post(f"{base_url}/api/v1/alm/autonomous-cycle", timeout=10)
    assert auto_res.status_code == 200
    auto_data = auto_res.json()
    assert auto_data["ok"] is True
    assert "RAG-PB-ATM-001" in auto_data.get("ragPlaybooksApplied", [])
    assert auto_data["atmIncidentStatus"] == "RESOLVED (AUTO-REDEPLOYED)"

    page = ServiciosClientesPage(driver, base_url).open()
    alert_text = page.procesar_bloqueo_tarjeta_atm(
        num_tarjeta="4548 1234 5678 9012",
        atm_id="ATM-GTN-MAD-0042",
        ubicacion="Sucursal Getnet Gran Vía 28, Madrid",
    )
    assert "BLOQUEO_PREVENTIVO_CON_REVERSO_EMV_0420" in alert_text
    assert "REV-EMV-2026-" in alert_text


@pytest.mark.xray("GTN-TC-014")
def test_tc014_incidencia_sistemas_dynatrace_cloudwatch_mcp_autofix(base_url):
    """
    GTN-TC-014 / TL-GTN-114: Ciclo completo de Incidencia de Sistemas en Producción desde Dynatrace Davis AI
    (DT-PROB-2026-8841) y AWS CloudWatch (CW-ALARM-GTN-CARDLOCK-P99) + Playbook RAG-PB-SYS-002 -> Auto-Fix Redis TTL=3000ms.
    """
    requests.post(f"{base_url}/api/v1/alm/inject-incidents", timeout=5)
    obs_before = requests.get(f"{base_url}/api/v1/observability/status", timeout=5).json()
    alarms_before = obs_before["cloudwatch"]["alarms"]
    dt_problems_before = obs_before["dynatrace"]["problems"]
    assert any(a["alarmName"] == "CW-ALARM-GTN-CARDLOCK-P99" and a["state"] == "ALARM" for a in alarms_before)
    assert any(p["problemId"] == "DT-PROB-2026-8841" and p["status"] == "OPEN" for p in dt_problems_before)

    # Verificar conexión MCP interactiva con Dynatrace y consulta RAG
    mcp_dt = requests.post(
        f"{base_url}/api/v1/mcp/connect",
        json={"provider": "dynatrace", "query": "fetch spans | limit 5"},
        timeout=5,
    ).json()
    assert mcp_dt["ok"] is True

    rag_res = requests.post(
        f"{base_url}/api/v1/rag/query",
        json={"query": "Dynatrace Davis AI deadlock Redis TTL 0 HikariCP"},
        timeout=5,
    ).json()
    assert rag_res["ragResult"]["agenticSynthesis"]["selectedPlaybookId"] == "RAG-PB-SYS-002"

    cycle = requests.post(f"{base_url}/api/v1/alm/autonomous-cycle", timeout=10).json()
    assert cycle["ok"] is True
    assert cycle["sysIncidentStatus"] == "RESOLVED (AUTO-REDEPLOYED)"
    assert cycle["deployedRelease"] == "v2026.11.2-AUTONOMOUS-PRO"

    obs_after = requests.get(f"{base_url}/api/v1/observability/status", timeout=5).json()
    alarms_after = obs_after["cloudwatch"]["alarms"]
    dt_problems_after = obs_after["dynatrace"]["problems"]
    assert all(a["state"] == "OK" for a in alarms_after)
    assert all(p["status"] == "CLOSED" for p in dt_problems_after)
    assert obs_after["prometheus"]["metrics"]["getnet_card_block_latency_p95_ms"] < 100.0
    assert obs_after["prometheus"]["metrics"]["getnet_redis_mutex_deadlocks_total"] == 0
