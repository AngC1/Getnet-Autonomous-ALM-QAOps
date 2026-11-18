"""
Page Object Model (POM) con Motor de Auto-Curación (Self-Healing Locators)
para el Portal Operativo de Tarjetas Bancarias Getnet (Grupo Santander) (/servicios-para-clientes).
"""

from __future__ import annotations

from typing import List, Tuple
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


class ServiciosClientesPage:
    """Page Object del portal de Tarjetas Bancarias Getnet (/servicios-para-clientes) con soporte Self-Healing."""

    def __init__(self, driver: WebDriver, base_url: str = "http://127.0.0.1:8080") -> None:
        self.driver = driver
        self.base_url = base_url.rstrip("/")
        self.wait = WebDriverWait(driver, 10)
        self.healing_events: List[str] = []

    def find_healed(self, candidates: List[Tuple[str, str]]) -> WebElement:
        last_exc = None
        for idx, (by, value) in enumerate(candidates):
            try:
                el = self.wait.until(EC.presence_of_element_located((by, value)))
                if idx > 0:
                    self.healing_events.append(
                        f"Self-Healed locator: primary {candidates[0]} -> fallback {(by, value)}"
                    )
                return el
            except Exception as exc:
                last_exc = exc
        raise RuntimeError(f"No se pudo localizar el elemento con candidatos: {candidates}") from last_exc

    def open(self) -> "ServiciosClientesPage":
        self.driver.get(f"{self.base_url}/servicios-para-clientes")
        self.find_healed(
            [
                (By.ID, "hero-title"),
                (By.CSS_SELECTOR, "[data-testid='hero-title']"),
                (By.TAG_NAME, "h1"),
            ]
        )
        return self

    def get_hero_title(self) -> str:
        return self.find_healed([(By.ID, "hero-title"), (By.CSS_SELECTOR, "[data-testid='hero-title']")]).text

    def get_service_cards_count(self) -> int:
        cards = self.driver.find_elements(By.CSS_SELECTOR, "#catalogo-servicios-grid .service-card")
        return len(cards)

    def switch_tab(self, tab_btn_id: str) -> None:
        btn = self.find_healed(
            [
                (By.ID, tab_btn_id),
                (By.CSS_SELECTOR, f"[data-testid='{tab_btn_id}']"),
            ]
        )
        btn.click()

    # --- 1. Flujo Parque de Tarjetas Bancarias EMV & Red ATM ---
    def buscar_parque_tarjetas(
        self,
        provincia: str = "Todas",
        tipo_tarjeta: str = "Todas",
        programa: str = "Todas",
        texto: str = "",
    ) -> int:
        self.switch_tab("btn-tab-cuadro")
        Select(self.find_healed([(By.ID, "cm-provincia")])).select_by_visible_text(
            "Todas las provincias" if provincia == "Todas" else provincia
        )
        Select(self.find_healed([(By.ID, "trj-tipo")])).select_by_visible_text(
            "Todos los tipos de tarjeta" if tipo_tarjeta == "Todas" else tipo_tarjeta
        )
        Select(self.find_healed([(By.ID, "trj-programa")])).select_by_visible_text(
            "Todos los programas de tarjeta" if programa == "Todas" else programa
        )
        q_input = self.find_healed([(By.ID, "cm-query")])
        q_input.clear()
        if texto:
            q_input.send_keys(texto)

        self.find_healed([(By.ID, "btn-buscar-cuadro")]).click()
        self.wait.until(lambda d: "Mostrando" in d.find_element(By.ID, "cm-contador").text)
        cards = self.driver.find_elements(By.CSS_SELECTOR, "[data-testid='center-card-item']")
        return len(cards)

    # --- 2. Flujo Autorización Online de Tarjetas Bancarias ISO-8583 ---
    def solicitar_autorizacion_tarjeta(
        self,
        num_tarjeta: str,
        tipo_operacion_visible: str,
        codigo_referencia: str,
        nodo_atm_comercio: str,
    ) -> str:
        self.switch_tab("btn-tab-autorizaciones")
        tarjeta_el = self.find_healed([(By.ID, "aut-tarjeta")])
        tarjeta_el.clear()
        tarjeta_el.send_keys(num_tarjeta)

        Select(self.find_healed([(By.ID, "aut-tipo-acto")])).select_by_visible_text(tipo_operacion_visible)

        pres_el = self.find_healed([(By.ID, "aut-prescripcion")])
        pres_el.clear()
        pres_el.send_keys(codigo_referencia)

        centro_el = self.find_healed([(By.ID, "aut-centro")])
        centro_el.clear()
        centro_el.send_keys(nodo_atm_comercio)

        self.find_healed([(By.ID, "btn-solicitar-autorizacion")]).click()
        alert = self.wait.until(
            lambda d: d.find_element(By.ID, "aut-resultado-alert")
            if "show" in d.find_element(By.ID, "aut-resultado-alert").get_attribute("class")
            else False
        )
        return alert.text

    # --- 3. Flujo Disputas, Contracargos (Chargebacks) y Fraude en Tarjetas ---
    def registrar_disputa_tarjeta(
        self,
        nif: str,
        programa_visible: str,
        importe: str,
        iban: str,
    ) -> str:
        self.switch_tab("btn-tab-disputas")
        nif_el = self.find_healed([(By.ID, "rmb-nif")])
        nif_el.clear()
        nif_el.send_keys(nif)

        Select(self.find_healed([(By.ID, "rmb-modalidad")])).select_by_visible_text(programa_visible)

        imp_el = self.find_healed([(By.ID, "rmb-importe")])
        imp_el.clear()
        imp_el.send_keys(importe)

        iban_el = self.find_healed([(By.ID, "rmb-iban")])
        iban_el.clear()
        iban_el.send_keys(iban)

        self.find_healed([(By.ID, "btn-enviar-disputa")]).click()
        alert = self.wait.until(
            lambda d: d.find_element(By.ID, "rmb-resultado-alert")
            if "show" in d.find_element(By.ID, "rmb-resultado-alert").get_attribute("class")
            else False
        )
        return alert.text

    # --- 4. Flujo Área Titular & Tarjeta Bancaria Digital Tokenizada ---
    def login_area_titular(self, nif: str, password: str) -> str:
        self.switch_tab("btn-tab-area-cliente")
        nif_el = self.find_healed([(By.ID, "login-nif")])
        nif_el.clear()
        nif_el.send_keys(nif)

        pwd_el = self.find_healed([(By.ID, "login-password")])
        pwd_el.clear()
        pwd_el.send_keys(password)

        self.find_healed([(By.ID, "btn-login-cliente")]).click()
        alert = self.wait.until(
            lambda d: d.find_element(By.ID, "login-resultado-alert")
            if "show" in d.find_element(By.ID, "login-resultado-alert").get_attribute("class")
            else False
        )
        return alert.text

    # --- 5. Flujo Soporte Criptográfico EMV, PIN Block HSM y 3DS2 24h ---
    def solicitar_soporte_tarjetas(self, unidad_visible: str, motivo: str) -> str:
        self.switch_tab("btn-tab-videoconsulta")
        Select(self.find_healed([(By.ID, "sop-unidad")])).select_by_visible_text(unidad_visible)

        motivo_el = self.find_healed([(By.ID, "vc-motivo")])
        motivo_el.clear()
        motivo_el.send_keys(motivo)

        self.find_healed([(By.ID, "btn-reservar-vc")]).click()
        alert = self.wait.until(
            lambda d: d.find_element(By.ID, "vc-resultado-alert")
            if "show" in d.find_element(By.ID, "vc-resultado-alert").get_attribute("class")
            else False
        )
        return alert.text

    # --- 6. Flujo Bloqueo Preventivo de Tarjeta en Cajero ATM (Getnet_ATM) ---
    def procesar_bloqueo_tarjeta_atm(
        self,
        num_tarjeta: str = "4548 1234 5678 9012",
        atm_id: str = "ATM-GTN-MAD-0042",
        ubicacion: str = "Sucursal Getnet Gran Vía 28, Madrid",
    ) -> str:
        self.switch_tab("btn-tab-bloqueo-atm")
        pan_el = self.find_healed([(By.ID, "blk-tarjeta"), (By.CSS_SELECTOR, "[data-testid='input-blk-tarjeta']")])
        pan_el.clear()
        pan_el.send_keys(num_tarjeta)

        atm_el = self.find_healed([(By.ID, "blk-atm-id"), (By.CSS_SELECTOR, "[data-testid='input-blk-atm-id']")])
        atm_el.clear()
        atm_el.send_keys(atm_id)

        ubic_el = self.find_healed([(By.ID, "blk-ubicacion"), (By.CSS_SELECTOR, "[data-testid='input-blk-ubicacion']")])
        ubic_el.clear()
        ubic_el.send_keys(ubicacion)

        self.find_healed([(By.ID, "btn-ejecutar-bloqueo-atm"), (By.CSS_SELECTOR, "[data-testid='btn-ejecutar-bloqueo-atm']")]).click()
        alert = self.wait.until(
            lambda d: d.find_element(By.ID, "atm-bloqueo-alert")
            if "REV-EMV-2026-" in d.find_element(By.ID, "atm-bloqueo-alert").text
            or "ATM_CARD_TRAPPED" in d.find_element(By.ID, "atm-bloqueo-alert").text
            else False
        )
        return alert.text
