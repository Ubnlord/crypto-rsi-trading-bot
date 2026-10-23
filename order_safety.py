"""Conservative order lifecycle helpers.

Live trading is blocked unless an exchange-specific OCO adapter is implemented and
explicitly enabled. Two independent sell orders are not a safe substitute for OCO.
"""
from __future__ import annotations
from config import config

class ProtectionUnavailable(RuntimeError):
    pass

def require_exchange_protection(exchange_id: str) -> None:
    if config.is_live:
        raise ProtectionUnavailable(
            f"Live trading is fail-closed: native OCO/bracket protection has not been "
            f"implemented and verified for {exchange_id}. Use MODE=paper."
        )

def order_is_filled(order: dict) -> bool:
    status = str(order.get("status") or "").lower()
    amount = float(order.get("amount") or 0)
    filled = float(order.get("filled") or 0)
    return status == "closed" and (amount <= 0 or filled >= amount * 0.999)

def order_is_terminal(order: dict) -> bool:
    return str(order.get("status") or "").lower() in {"closed", "canceled", "cancelled", "rejected", "expired"}
