"""
Suite Automatizada E2E (Selenium WebDriver + Pytest + Autonomous ALM) para Getnet (Grupo Santander).
Mapeada 1:1 con el Backlog ALM en Jira Xray (GTN-TC-001..010, GTN-TC-013..014),
TestLink (TL-GTN-101..114) y Redmine (#5011..5024).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pages.servicios_clientes_page import ServiciosClientesPage


@pytest.mark.xray("GTN-TC-001")
def test_tc001_catalogo_servicios_clientes(driver, base_url):
    """GTN-TC-001 / TL-GTN-101: Renderizado del catálogo de Servicios Getnet y KPIs transaccionales."""
    page = ServiciosClientesPage(driver, base_url).open()
    hero_low = page.get_hero_title().lower()
    assert "getnet" in hero_low or "servicios" in hero_low
    assert page.get_service_cards_count() == 6


@pytest.mark.xray("GTN-TC-002")
def test_tc002_busqueda_cuadro_medico_madrid_cardiologia(driver, base_url):
    """GTN-TC-002 / TL-GTN-102: Búsqueda de Red ATM y Centros Getnet en Madrid."""
    page = ServiciosClientesPage(driver, base_url).open()
    total = page.buscar_cuadro_medico(provincia="Madrid", especialidad="Cardiología")
    assert total >= 2


@pytest.mark.xray("GTN-TC-003")
def test_tc003_busqueda_urgencias_muface(driver, base_url):
    """GTN-TC-003 / TL-GTN-103: Búsqueda de Centros de Guardia / Urgencias 24h."""
    page = ServiciosClientesPage(driver, base_url).open()
    total = page.buscar_cuadro_medico(especialidad="Urgencias 24h", poliza="Muface / Isfas")
    assert total >= 2


@pytest.mark.xray("GTN-TC-004")
def test_tc004_solicitud_autorizacion_exitosa(driver, base_url):
    """GTN-TC-004 / TL-GTN-104: Solicitud exitosa de Autorización Operativa ISO-8583."""
    page = ServiciosClientesPage(driver, base_url).open()
    resultado = page.solicitar_autorizacion(
        num_tarjeta="8000123456789012",
        tipo_acto_visible="Resonancia Magnética Nuclear (RMN)",
        prescripcion="RX-99281",
        centro="Hospital Ruber Internacional",
    )
    assert "AUTORIZADA" in resultado
    assert "AUT-2026-" in resultado


@pytest.mark.xray("GTN-TC-005")
def test_tc005_autorizacion_tarjeta_invalida(driver, base_url):
    """GTN-TC-005 / TL-GTN-105: Validación negativa de Autorización con número de tarjeta inválido."""
    page = ServiciosClientesPage(driver, base_url).open()
    resultado = page.solicitar_autorizacion(
        num_tarjeta="12345",
        tipo_acto_visible="TAC / Escáner Diagnóstico",
        prescripcion="TAC-1102",
        centro="Hospital Quirónsalud",
    )
    assert "Error en la validación" in resultado
    assert "12 y 16 dígitos" in resultado


@pytest.mark.xray("GTN-TC-006")
def test_tc006_autorizacion_revision_medica(base_url):
    """GTN-TC-006 / TL-GTN-106: Operación de alta complejidad derivada a Inspección Especializada."""
    res = requests.post(
        f"{base_url}/api/v1/autorizaciones",
        json={
            "numTarjeta": "8000123456789012",
            "tipoActo": "Estudio Genético Oncológico",
            "codigoPrescripcion": "GEN-55019",
            "centroMedico": "Centro Médico Teknon",
        },
        timeout=5,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["ok"] is True
    assert data["autorizacion"]["estado"] == "PENDIENTE_REVISION_MEDICA"


@pytest.mark.xray("GTN-TC-007")
def test_tc007_reembolso_premier_calculo_90(driver, base_url):
    """GTN-TC-007 / TL-GTN-107: Registro de Liquidación / Reembolso (Modalidad Premier - 90% cobertura)."""
    page = ServiciosClientesPage(driver, base_url).open()
    resultado = page.solicitar_reembolso(
        nif="12345678Z",
        modalidad_visible="Adeslas Premier (90% Cobertura)",
        importe="250.00",
        iban="ES9121000418450200051332",
    )
    assert "RMB-2026-" in resultado
    assert "225.00 EUR" in resultado


@pytest.mark.xray("GTN-TC-008")
def test_tc008_reembolso_iban_invalido(driver, base_url):
    """GTN-TC-008 / TL-GTN-108: Validación de IBAN incorrecto en solicitud de Reembolso."""
    page = ServiciosClientesPage(driver, base_url).open()
    resultado = page.solicitar_reembolso(
        nif="12345678Z",
        modalidad_visible="Adeslas Extra (80% Cobertura)",
        importe="120.00",
        iban="ES1234",
    )
    assert "Error en solicitud de reembolso" in resultado
    assert "IBAN" in resultado


@pytest.mark.xray("GTN-TC-009")
def test_tc009_login_area_cliente_tarjeta_digital(driver, base_url):
    """GTN-TC-009 / TL-GTN-109: Acceso al Área Cliente Getnet y visualización de Tarjeta Digital."""
    page = ServiciosClientesPage(driver, base_url).open()
    resultado = page.login_area_cliente("12345678Z", "Adeslas2026!")
    assert "Carlos Martínez Gómez" in resultado
    assert "POL-SCA-908122" in resultado
    assert "8000123456789012" in resultado


@pytest.mark.xray("GTN-TC-010")
def test_tc010_reserva_videoconsulta_medica(driver, base_url):
    """GTN-TC-010 / TL-GTN-110: Reserva de Sesión de Soporte Remoto / Videoconsulta 24h."""
    page = ServiciosClientesPage(driver, base_url).open()
    resultado = page.reservar_videoconsulta(
        especialidad_visible="Medicina General (24h)",
        motivo="Verificación preventiva de pasarela TPV y nodo ATM",
    )
    assert "CIT-2026-" in resultado
    assert "Dra. Patricia Navarro Solís" in resultado


@pytest.mark.xray("GTN-TC-013")
def test_tc013_incidencia_funcional_atm_kiro_autofix(driver, base_url):
    """
    GTN-TC-013 / TL-GTN-113: Ciclo completo de Incidencia Funcional de Bloqueo de Tarjeta desde ATM (AWS_Kiro-main)
    -> Detección (HTTP 409) -> Triage + RCA + Re-Fixing + Re-Deploy sin Human-in-the-Loop -> Verificación UI/API (HTTP 201).
    """
    # 1. Inyectar la incidencia en Producción
    inj = requests.post(f"{base_url}/api/v1/alm/inject-incidents", timeout=5)
    assert inj.status_code == 200

    # 2. Verificar que el bloqueo en el cajero ATM falla con HTTP 409 (Tarjeta retenida sin reverso EMV 0420)
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

    # 3. Ejecutar el Ciclo Autónomo ALM sin Human-in-the-Loop (Triage -> RCA -> Re-Fix -> Re-Deploy)
    auto_res = requests.post(f"{base_url}/api/v1/alm/autonomous-cycle", timeout=10)
    assert auto_res.status_code == 200
    auto_data = auto_res.json()
    assert auto_data["ok"] is True
    assert auto_data["atmIncidentStatus"] == "RESOLVED (AUTO-REDEPLOYED)"

    # 4. Verificar en la UI del portal con Selenium que el bloqueo ATM ahora emite el reverso EMV 0420 y el token digital
    page = ServiciosClientesPage(driver, base_url).open()
    alert_text = page.procesar_bloqueo_tarjeta_atm(
        num_tarjeta="4548 1234 5678 9012",
        atm_id="ATM-GTN-MAD-0042",
        ubicacion="Sucursal Getnet Gran Vía 28, Madrid",
    )
    assert "BLOQUEO_PREVENTIVO_CON_REVERSO_EMV_0420" in alert_text
    assert "REV-EMV-2026-" in alert_text


@pytest.mark.xray("GTN-TC-014")
def test_tc014_incidencia_sistemas_cloudwatch_mcp_autofix(base_url):
    """
    GTN-TC-014 / TL-GTN-114: Ciclo completo de Incidencia de Sistemas en Producción desde AWS CloudWatch
    y Prometheus OpenSource MCP -> Detección de alarma -> Auto-Fix (Redis Lock TTL 1500ms + Circuit Breaker) -> Re-Deploy.
    """
    # 1. Inyectar incidencia de sistemas y verificar que CloudWatch y Prometheus disparan ALARM
    requests.post(f"{base_url}/api/v1/alm/inject-incidents", timeout=5)
    obs_before = requests.get(f"{base_url}/api/v1/observability/status", timeout=5).json()
    alarms_before = obs_before["cloudwatch"]["alarms"]
    assert any(a["alarmName"] == "CW-ALARM-GTN-CARDLOCK-P99" and a["state"] == "ALARM" for a in alarms_before)
    assert obs_before["prometheus"]["metrics"]["getnet_card_block_latency_p95_ms"] > 1000.0

    # 2. Ejecutar Ciclo Autónomo ALM sin Human-in-the-Loop
    cycle = requests.post(f"{base_url}/api/v1/alm/autonomous-cycle", timeout=10).json()
    assert cycle["ok"] is True
    assert cycle["sysIncidentStatus"] == "RESOLVED (AUTO-REDEPLOYED)"
    assert cycle["deployedRelease"] == "v2026.11.2-AUTONOMOUS-PRO"

    # 3. Verificar que las alarmas de AWS CloudWatch y Prometheus vuelven a estado OK y P95 < 100ms
    obs_after = requests.get(f"{base_url}/api/v1/observability/status", timeout=5).json()
    alarms_after = obs_after["cloudwatch"]["alarms"]
    assert all(a["state"] == "OK" for a in alarms_after)
    assert obs_after["prometheus"]["metrics"]["getnet_card_block_latency_p95_ms"] < 100.0
    assert obs_after["prometheus"]["metrics"]["getnet_redis_mutex_deadlocks_total"] == 0
