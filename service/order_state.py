"""Fail-closed order lifecycle rules; this module never contacts a broker."""
from __future__ import annotations

from enum import StrEnum


class OrderStatus(StrEnum):
    PENDING = "pending"
    SUBMITTING = "submitting"
    UNKNOWN = "unknown"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"


_ALLOWED: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset({OrderStatus.SUBMITTING, OrderStatus.CANCELLED, OrderStatus.FAILED}),
    OrderStatus.SUBMITTING: frozenset({
        OrderStatus.UNKNOWN, OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FAILED,
    }),
    # An uncertain submission must be reconciled with the provider before retrying.
    OrderStatus.UNKNOWN: frozenset({
        OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED,
        OrderStatus.CANCELLED, OrderStatus.REJECTED,
    }),
    OrderStatus.ACCEPTED: frozenset({
        OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.UNKNOWN,
    }),
    OrderStatus.PARTIALLY_FILLED: frozenset({
        OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.UNKNOWN,
    }),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.FAILED: frozenset(),
}


class InvalidOrderTransition(ValueError):
    """Raised when an order state change is unsafe or inconsistent."""


def transition(current: OrderStatus | str, target: OrderStatus | str) -> OrderStatus:
    """Validate a state transition without mutating persistence or sending orders."""
    try:
        source = OrderStatus(current)
        destination = OrderStatus(target)
    except ValueError as exc:
        raise InvalidOrderTransition("Unknown order status; fail closed") from exc

    if destination not in _ALLOWED[source]:
        raise InvalidOrderTransition(f"Disallowed order transition: {source.value} -> {destination.value}")
    return destination


def may_submit_again(status: OrderStatus | str) -> bool:
    """Only a never-submitted pending intent may be submitted.

    UNKNOWN is deliberately false: query/reconcile provider state first, and only
    create a new intent after authoritative evidence establishes the prior order
    was never accepted.
    """
    try:
        return OrderStatus(status) is OrderStatus.PENDING
    except ValueError:
        return False
