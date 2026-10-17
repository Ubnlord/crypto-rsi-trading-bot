"""Crash-safe persistence for the paper portfolio only.

This file never stores API credentials and is not used as authority for live
exchange balances. Writes are atomic to avoid partially-written JSON on restart.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any


def _finite_number(value: Any) -> bool:
    # bool is a subclass of int, but must not be accepted as a monetary value.
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def default_state(initial_cash: float = 10_000.0) -> dict[str, Any]:
    if not _finite_number(initial_cash) or initial_cash < 0:
        raise ValueError("Initial paper cash must be a finite non-negative number")
    return {
        "schema_version": 1,
        "cash": float(initial_cash),
        "positions": {},
        "processed_order_ids": [],
    }


def validate_state(state: Any) -> dict[str, Any]:
    """Validate every persisted value before it can become portfolio state."""
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise RuntimeError("Unsupported or invalid paper state schema; refusing to reset portfolio")
    cash = state.get("cash")
    if not _finite_number(cash) or cash < 0:
        raise RuntimeError("Paper state has invalid cash balance")
    positions = state.get("positions")
    if not isinstance(positions, dict):
        raise RuntimeError("Paper state has invalid positions map")
    order_ids = state.get("processed_order_ids")
    if not isinstance(order_ids, list) or not all(isinstance(item, str) and item for item in order_ids):
        raise RuntimeError("Paper state has invalid processed order ID ledger")
    if len(order_ids) != len(set(order_ids)):
        raise RuntimeError("Paper state contains duplicate processed order IDs")

    for symbol, position in positions.items():
        if not isinstance(symbol, str) or not symbol or not isinstance(position, dict):
            raise RuntimeError(f"Invalid paper position record for {symbol}")
        for key in ("amount", "entry_price", "stop_price", "take_profit_price"):
            value = position.get(key)
            if not _finite_number(value) or value <= 0:
                raise RuntimeError(f"Invalid {key} in paper position for {symbol}")
        if position["stop_price"] >= position["entry_price"]:
            raise RuntimeError(f"Stop price must be below entry price for {symbol}")
        if position["take_profit_price"] <= position["entry_price"]:
            raise RuntimeError(f"Take-profit price must be above entry price for {symbol}")
    return state


def load_state(path: str | Path, initial_cash: float = 10_000.0) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return default_state(initial_cash)
    try:
        state = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Paper state file is unreadable; refusing to reset portfolio: {target}") from exc
    return validate_state(state)


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    validate_state(state)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + f".{os.getpid()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
        # Best-effort directory sync makes the rename more durable across crashes.
        try:
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def cumulative_fill_delta(previous_filled: float, order_update: dict[str, Any]) -> float:
    """Return only newly filled quantity from a CCXT-style cumulative update."""
    filled = order_update.get("filled")
    if not _finite_number(previous_filled) or previous_filled < 0:
        raise ValueError("Previous cumulative fill must be finite and non-negative")
    if not _finite_number(filled) or filled < 0:
        raise ValueError("Order update must contain a finite non-negative cumulative 'filled' amount")
    if filled + 1e-12 < previous_filled:
        raise ValueError("Cumulative filled amount moved backwards; reconciliation required")
    return max(0.0, float(filled) - float(previous_filled))


def protective_levels(entry_price: float, stop_loss_pct: float, take_profit_pct: float) -> tuple[float, float]:
    if (
        not _finite_number(entry_price) or entry_price <= 0
        or not _finite_number(stop_loss_pct) or not 0 < stop_loss_pct < 100
        or not _finite_number(take_profit_pct) or take_profit_pct <= 0
    ):
        raise ValueError("Invalid entry price or protective-order percentages")
    return (
        entry_price * (1 - stop_loss_pct / 100),
        entry_price * (1 + take_profit_pct / 100),
    )
