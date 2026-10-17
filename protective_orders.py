"""Fail-closed native OCO protection adapter.

An exchange-specific adapter must expose create_oco_order and return two order
IDs. This intentionally refuses to emulate exchange-native protection with two
independent spot sell orders, which can over-sell or race. Live execution is
disabled in config.py until an exchange-specific sandbox test is completed.
"""
from __future__ import annotations

from typing import Any


class ProtectionUnavailable(RuntimeError):
    pass


def place_and_verify_oco(
    exchange: Any,
    symbol: str,
    amount: float,
    stop_price: float,
    take_profit_price: float,
) -> dict[str, Any]:
    if amount <= 0 or stop_price <= 0 or take_profit_price <= stop_price:
        raise ValueError("Invalid OCO amount or price levels")
    create_oco = getattr(exchange, "create_oco_order", None)
    if not callable(create_oco):
        raise ProtectionUnavailable(
            "This CCXT exchange adapter has no verified native OCO API; refusing to "
            "pretend separate orders provide atomic stop/target protection."
        )

    response = create_oco(
        symbol=symbol,
        side="sell",
        amount=amount,
        stop_price=stop_price,
        take_profit_price=take_profit_price,
    )
    if not isinstance(response, dict):
        raise ProtectionUnavailable("Native OCO API returned an unrecognized response")
    order_ids = response.get("order_ids")
    if not isinstance(order_ids, list) or len(order_ids) != 2 or not all(order_ids):
        raise ProtectionUnavailable("Native OCO response must include both stop and target order IDs")

    verified = []
    for order_id in order_ids:
        order = exchange.fetch_order(order_id, symbol)
        if not isinstance(order, dict) or str(order.get("id")) != str(order_id):
            raise ProtectionUnavailable(f"Could not verify protective order {order_id}")
        if str(order.get("status", "")).lower() in {"rejected", "canceled", "expired"}:
            raise ProtectionUnavailable(f"Protective order {order_id} is not active")
        verified.append({
            "id": str(order_id),
            "status": str(order.get("status", "unknown")),
        })
    return {
        "symbol": symbol,
        "amount": amount,
        "stop_price": stop_price,
        "take_profit_price": take_profit_price,
        "orders": verified,
        "verified": True,
    }
