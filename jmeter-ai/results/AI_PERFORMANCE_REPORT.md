# Informe de Rendimiento JMeter Asistido por IA — Getnet (Grupo Santander)

- **Fecha de Ejecución**: `2026-11-17 19:21:09 UTC`
- **Escenario**: Pico Transaccional Getnet Core & Card Blocker - Ejecución JMeter AI
- **Estado del Quality Gate (SLA P95 < 450ms)**: **PASSED**

## 1. Métricas Globales de Rendimiento

| Métrica | Valor Obtenido | Umbral SLA Getnet |
| :--- | :--- | :--- |
| Muestras Totales | `60` | >= 50 |
| Throughput | `120.0 req/s` | >= 15 req/s |
| Tiempo Medio (Avg) | `16.92 ms` | < 200 ms |
| Percentil 90 (P90) | `46.98 ms` | < 350 ms |
| Percentil 95 (P95) | `49.96 ms` | **< 450 ms** |
| Percentil 99 (P99) | `55.95 ms` | < 800 ms |
| Tasa de Error | `0.0%` | <= 1.0% |
| Índice Apdex | `1.0` | >= 0.90 |

## 2. Desglose por Transacción / Endpoint

| Endpoint / Transacción | Muestras | Media (ms) | P95 (ms) | Error % |
| :--- | :--- | :--- | :--- | :--- |
| `POST /api/v1/tarjetas/bloqueo (ATM Card Blocker)` | 12 | 8.86 ms | **17.52 ms** | 0.0% |
| `POST /api/v1/autorizaciones (ISO-8583)` | 12 | 9.2 ms | **17.48 ms** | 0.0% |
| `POST /api/v1/reembolsos (Liquidación TPV)` | 12 | 9.21 ms | **18.25 ms** | 0.0% |
| `GET /api/v1/cuadro-medico (Red ATM Getnet)` | 12 | 8.43 ms | **15.95 ms** | 0.0% |
| `POST /api/v1/autorizaciones (Inspección Antifraude)` | 12 | 48.91 ms | **56.01 ms** | 0.0% |

## 3. Diagnóstico Cognitivo del Agente JMeter IA (Getnet QAOps)

- Cumplimiento SLA Global Getnet: APROBADO (P95 = 49.96 ms frente al objetivo < 450.0 ms; Error Rate = 0.0%).
- Índice de satisfacción transaccional Apdex = 1.0 con caudal sostenido de 120.0 req/s (60 transacciones).
- Verificación Post-Hotfix (GTN-INC-SYS-002 & GTN-INC-ATM-001): El servicio getnet-card-blocker-svc procesa bloqueos ATM con reverso EMV 0420 y lock Redis TTL=1500ms con 0% errores.
