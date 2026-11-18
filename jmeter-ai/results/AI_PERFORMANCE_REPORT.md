# Informe de Rendimiento JMeter Asistido por IA — Operativa de Tarjetas Bancarias Getnet

- **Fecha de Ejecución**: `2026-11-18 21:57:25 UTC`
- **Escenario**: Pico Transaccional de Tarjetas Bancarias Getnet & Card Blocker - Ejecución JMeter AI
- **Estado del Quality Gate (SLA P95 < 450ms)**: **PASSED**

## 1. Métricas Globales de Rendimiento

| Métrica | Valor Obtenido | Umbral SLA Getnet |
| :--- | :--- | :--- |
| Muestras Totales | `60` | >= 50 |
| Throughput | `120.0 req/s` | >= 15 req/s |
| Tiempo Medio (Avg) | `17.5 ms` | < 200 ms |
| Percentil 90 (P90) | `48.0 ms` | < 350 ms |
| Percentil 95 (P95) | `54.89 ms` | **< 450 ms** |
| Percentil 99 (P99) | `58.23 ms` | < 800 ms |
| Tasa de Error | `0.0%` | <= 1.0% |
| Índice Apdex | `1.0` | >= 0.90 |

## 2. Desglose por Transacción de Tarjetas Bancarias

| Endpoint / Transacción | Muestras | Media (ms) | P95 (ms) | Error % |
| :--- | :--- | :--- | :--- | :--- |
| `POST /api/v1/tarjetas/autorizaciones (ISO-8583 MTI 0100)` | 12 | 8.74 ms | **15.0 ms** | 0.0% |
| `POST /api/v1/tarjetas/bloqueo (ATM Card Blocker Kiro)` | 12 | 9.07 ms | **17.44 ms** | 0.0% |
| `GET /api/v1/tarjetas/parque (Parque Tarjetas EMV)` | 12 | 9.13 ms | **17.14 ms** | 0.0% |
| `POST /api/v1/tarjetas/disputas (Chargeback Visa/Mastercard)` | 12 | 10.12 ms | **21.1 ms** | 0.0% |
| `POST /api/v1/tarjetas/autorizaciones (Control Antifraude)` | 12 | 50.46 ms | **58.28 ms** | 0.0% |

## 3. Diagnóstico Cognitivo del Agente JMeter IA (Getnet QAOps)

- Cumplimiento SLA Global Tarjetas Getnet: APROBADO (P95 = 54.89 ms frente al objetivo < 450.0 ms; Error Rate = 0.0%).
- Índice de satisfacción transaccional Apdex = 1.0 con caudal sostenido de 120.0 req/s (60 operaciones de tarjetas).
- Verificación Post-Hotfix (GTN-INC-SYS-002 & GTN-INC-ATM-001): El servicio getnet-card-blocker-svc procesa bloqueos ATM con reverso EMV 0420 y lock Redis TTL=3000ms con 0% errores.
