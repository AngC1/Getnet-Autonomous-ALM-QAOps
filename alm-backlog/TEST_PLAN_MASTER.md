# Plan Maestro de Pruebas QAOps & Autonomous ALM — Tarjetas Bancarias Getnet (Grupo Santander)

Este documento certifica la cobertura **100% enfocada en Tarjetas Bancarias** (`GTN-TC-001` a `GTN-TC-014`), la orquestación de los **5 Agentes Autónomos**, los conectores **MCP Server (`Dynatrace Davis AI`, `AWS CloudWatch`, `Prometheus`, `Getnet ATM ATM`)** y el **Motor RAG de Comportamiento de Incidencias (`rag-knowledge-base/`)**.

## Matriz de 14 Casos de Prueba de Tarjetas Bancarias (`Jira Xray` / `TestLink` / `Redmine`)

| Clave Jira Xray | ID TestLink | Caso de Prueba de Tarjetas Bancarias | Tipo | Estado |
| :--- | :--- | :--- | :--- | :--- |
| **`GTN-TC-001`** | `TL-GTN-101` | Catálogo de 6 módulos operativos de tarjetas bancarias Getnet y KPIs | E2E Selenium | `PASSED` |
| **`GTN-TC-002`** | `TL-GTN-102` | Consulta de Parque de Tarjetas Bancarias en Madrid (`Visa Débito EMV`) | E2E Selenium | `PASSED` |
| **`GTN-TC-003`** | `TL-GTN-103` | Consulta de nodos `Guardia ATM 24h` en programa `Red Euro6000 ATM` | E2E Selenium | `PASSED` |
| **`GTN-TC-004`** | `TL-GTN-104` | Autorización online `ISO-8583` (`MTI 0110`) con tarjeta bancaria válida (`4548123456789012`) | E2E Selenium | `PASSED` |
| **`GTN-TC-005`** | `TL-GTN-105` | Rechazo de autorización `ISO-8583` con PAN inválido (`12345`) | Negativo E2E | `PASSED` |
| **`GTN-TC-006`** | `TL-GTN-106` | Derivación de operación de tarjeta de alto riesgo a `PENDIENTE_REVISION_RIESGOS` | API / Regla | `PASSED` |
| **`GTN-TC-007`** | `TL-GTN-107` | Registro de Disputa / Chargeback de tarjeta bancaria con abono provisional del `90%` (`225,00 EUR`) | E2E Selenium | `PASSED` |
| **`GTN-TC-008`** | `TL-GTN-108` | Rechazo de Disputa / Chargeback de tarjeta con IBAN inválido (`ES1234`) | Negativo E2E | `PASSED` |
| **`GTN-TC-009`** | `TL-GTN-109` | Login en Área Titular (`12345678Z` / `Getnet2026!`) y Tarjeta Bancaria Digital Tokenizada | E2E Selenium | `PASSED` |
| **`GTN-TC-010`** | `TL-GTN-110` | Solicitud de sesión de Soporte Criptográfico EMV, PIN Block HSM y 3DS2 24h | E2E Selenium | `PASSED` |
| **`GTN-TC-011`** | `TL-GTN-111` | Rendimiento JMeter IA en Parque de Tarjetas y Bloqueo ATM (`P95 < 450 ms`) | JMeter AI | `PASSED` |
| **`GTN-TC-012`** | `TL-GTN-112` | Stress Test JMeter IA en Autorización `ISO-8583` y Chargebacks (`0% HTTP 500`) | JMeter AI | `PASSED` |
| **`GTN-TC-013`** | `TL-GTN-113` | Ciclo ALM Zero-Touch: Incidencia funcional de tarjeta en ATM (`Getnet_ATM`) + `RAG-PB-ATM-001` | Autonomous ALM | `PASSED` |
| **`GTN-TC-014`** | `TL-GTN-114` | Ciclo ALM Zero-Touch: Incidencia de sistemas en Dynatrace (`DT-PROB-2026-8841`) y CloudWatch + `RAG-PB-SYS-002` | Autonomous ALM | `PASSED` |
