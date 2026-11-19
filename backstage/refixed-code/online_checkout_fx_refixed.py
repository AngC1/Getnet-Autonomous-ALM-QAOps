"""
===============================================================================
ARCHIVO DE CÓDIGO RE-FIXEADO EN PRODUCCIÓN (PAGOS ONLINE & GESTIÓN DEL DINERO)
===============================================================================
Componente Backstage : component:default/getnet-ecommerce-checkout-fx
Incidencias Resueltas: GTN-INC-ONL-011..014 (Pagos Online, Checkout, Link & Pay, Social Selling)
                       GTN-INC-CTA-015 (Cuentas T+0) · GTN-INC-PAG-016 (Pagos) · GTN-INC-FX-017 (FX DCC)
Playbooks RAG        : RAG-PB-ONL-011 .. RAG-PB-FX-017
Agente Autor         : Self-Healing-Patch-Agent (Zero Human-in-the-Loop)
Ruta en Repositorio  : backstage/refixed-code/online_checkout_fx_refixed.py
===============================================================================
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Dict

# Configuración Re-Fixeada para Pagos Online y Gestión del Dinero (Tesorería & FX)
REFIXED_ONLINE_AND_MONEY_CONFIG: Dict[str, Dict[str, Any]] = {
    "PROD-ONL-METHODS": {
        "apms_async_webhook_idempotency": True,
        "apm_reconciliation_window_sec": 15,
    },
    "PROD-ONL-CHECKOUT": {
        "acs_3ds2_timeout_ms": 2500,
        "enable_tra_frictionless_fallback": True,
    },
    "PROD-ONL-LINKPAY": {
        "hmac_clock_skew_tolerance_sec": 30,
        "enforce_single_use_nonce": True,
    },
    "PROD-ONL-SOCIAL": {
        "social_webhook_async_queue": True,
        "webhook_backoff_initial_ms": 250,
        "max_retry_attempts": 8,
    },
    "PROD-MON-CUENTAS": {
        "settlement_decimal_rounding": "ROUND_HALF_EVEN",
        "instant_payout_t0_enabled": True,
    },
    "PROD-MON-PAGOS": {
        "iso20022_strict_utf8_sanitizer": True,
        "sepa_instant_fallback_enabled": True,
    },
    "PROD-MON-FX": {
        "dcc_rate_lock_window_sec": 180,
        "fx_secondary_liquidity_failover": True,
    },
}


def compute_refixed_settlement_t0(gross_amount_eur: str, mdr_rate_pct: str) -> Dict[str, str]:
    """Cálculo contable exacto con Decimal ROUND_HALF_EVEN (corrige GTN-INC-CTA-015)."""
    gross = Decimal(gross_amount_eur)
    rate = Decimal(mdr_rate_pct) / Decimal("100")
    fee = (gross * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    net = (gross - fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    return {
        "grossEur": str(gross),
        "mdrFeeEur": str(fee),
        "netSettlementT0Eur": str(net),
        "roundingMode": "ROUND_HALF_EVEN",
    }
