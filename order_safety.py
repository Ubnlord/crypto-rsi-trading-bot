"""Exchange-specific protection policy.

Bybit's public help documentation states OCO orders are not available to API users.
The bot therefore refuses live spot trading until a verified atomic protection path is
available; independent stop and take-profit orders are not treated as equivalent.
"""
from __future__ import annotations

from config import config


class ProtectionUnavailable(RuntimeError):
    """Live order placement is blocked because protective execution is unverified."""


def require_exchange_protection(exchange_id: str, *, market_type: str = "spot") -> None:
    if not config.is_live:
        return
    exchange_id = exchange_id.lower()
    # This bot currently sizes and reconciles spot inventory. Bybit API OCO is not
    # available, and the strategy currently submits market entries without attached
    # exchange TP/SL. Do not imply that local monitoring is exchange-side protection.
    if exchange_id == "bybit" and market_type == "spot":
        raise ProtectionUnavailable(
            "Bybit live spot trading is disabled: API OCO is not available and this "
            "bot does not yet have a verified atomic entry-with-TP/SL workflow. "
            "Use MODE=paper and BYBIT_TESTNET=true for sandbox integration tests."
        )
    raise ProtectionUnavailable(
        f"Live trading is disabled until an exchange-native protective-order adapter "
        f"is implemented and verified for {exchange_id}/{market_type}."
    )


def order_is_filled(order: dict) -> bool:
    status = str(order.get("status") or "").lower()
    amount = float(order.get("amount") or 0)
    filled = float(order.get("filled") or 0)
    return status == "closed" and (amount <= 0 or filled >= amount * 0.999)


def order_is_terminal(order: dict) -> bool:
    return str(order.get("status") or "").lower() in {
        "closed", "canceled", "cancelled", "rejected", "expired"
    }
