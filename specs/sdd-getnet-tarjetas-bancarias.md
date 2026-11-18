# Especificación SDD — Operativa Funcional de Tarjetas Bancarias Getnet (Grupo Santander)

## 1. Alcance Funcional Exclusivo: Tarjetas Bancarias EMV y Red de Cajeros ATM

Toda la aplicación (`/servicios-para-clientes` en `portal-getnet/app.py`) y la matriz de pruebas (`GTN-TC-001` a `GTN-TC-014`) cubren exclusivamente el ciclo de vida de **Tarjetas Bancarias Getnet**:

1. **Parque de Tarjetas Bancarias EMV & Red de Cajeros ATM (`GET /api/v1/tarjetas/parque`)**:
   - Consulta de nodos emisores, tipos de tarjeta (`Visa Débito EMV`, `Mastercard Crédito Corporativa`, `Visa Platinum Contactless`, `Mastercard Prepago Tokenizada`, `Guardia ATM 24h`) y programas (`Getnet Corporate Premier`, `Santander One Tarjetas`, `Visa Infinite Business`, `Red Euro6000 ATM`).
2. **Autorización Online de Tarjetas Bancarias ISO-8583 & 3DS2 (`POST /api/v1/tarjetas/autorizaciones`)**:
   - Validación de PAN numérico de 12 a 16 dígitos.
   - Emisión de autorización `MTI 0110 (RC 00)` (`AUTORIZADA`, código `AUT-2026-XXXXX`) o derivación a `PENDIENTE_REVISION_RIESGOS` para operaciones internacionales de alto riesgo.
3. **Disputas, Contracargos (Chargebacks) y Fraude en Tarjetas (`POST /api/v1/tarjetas/disputas`)**:
   - Validación de NIF/NIE/CIF, rango de importe (`0 < importe <= 15.000 EUR`) y cuenta IBAN (`ES` + 22 dígitos).
   - Cálculo determinista de abono provisional del `90%` (`Getnet Corporate Premier`) u `80%` (`Estándar`), generando expediente `DSP-2026-XXXXX`.
4. **Área Titular y Tarjeta Bancaria Digital Tokenizada (`POST /api/v1/auth/login`)**:
   - Autenticación del titular (`12345678Z` / `Getnet2026!`), contrato `CTR-GTN-908122` y visualización de tarjeta digital tokenizada (`4548123456789012`).
5. **Soporte Criptográfico EMV, PIN Block HSM y 3DS2 24h (`POST /api/v1/tarjetas/soporte`)**:
   - Reserva de sesión remota con ingeniería de criptografía EMV/HSM (`SOP-2026-XXXXX`).
6. **Bloqueo Preventivo de Tarjetas en Cajero ATM (`POST /api/v1/tarjetas/bloqueo` · Motor `Getnet_ATM`)**:
   - Validación con `brand_verifier.incident.validate_incident`, enmascarado PCI-DSS con `redact_pan` (`4548 **** **** 9012`), emisión de reverso `ISO-8583 MTI 0420` (`REV-EMV-2026-XXXXX`) y provisión de token digital en Wallet (`TOK-GTN-WALLET-9012`).
