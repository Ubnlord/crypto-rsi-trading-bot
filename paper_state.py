"""Crash-safe persistence for the paper portfolio only.

This file never stores API credentials and is not used as authority for live
exchange balances. Writes are atomic to avoid partially-written JSON on restart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def default_state(initial_cash: float = 10_000.0) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "cash": float(initial_cash),
        "positions": {},
        "processed_order_ids": [],
    }


def load_state(path: str | Path, initial_cash: float = 10_000.0) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return default_state(initial_cash)
    try:
        state = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Paper state file is unreadable; refusing to reset portfolio: {target}") from exc
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise RuntimeError("Unsupported or invalid paper state schema; refusing to reset portfolio")
    if not isinstance(state.get("cash"), (int, float)) or state["cash"] < 0:
        raise RuntimeError("Paper state has invalid cash balance")
    if not isinstance(state.get("positions"), dict):
        raise RuntimeError("Paper state has invalid positions map")
    if not isinstance(state.get("processed_order_ids"), list):
        raise RuntimeError("Paper state has invalid processed order ID ledger")
    for symbol, position in state["positions"].items():
        if not isinstance(position, dict):
            raise RuntimeError(f"Invalid paper position record for {symbol}")
        for key in ("amount", "entry_price"):
            if not isinstance(position.get(key), (int, float)) or position[key] < 0:
                raise RuntimeError(f"Invalid {key} in paper position for {symbol}")
    return state


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + f".{os.getpid()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def cumulative_fill_delta(previous_filled: float, order_update: dict[str, Any]) -> float:
    """Return only newly filled quantity from a CCXT-style cumulative update."""
    filled = order_update.get("filled")
    if not isinstance(filled, (int, float)) or filled < 0:
        raise ValueError("Order update must contain a non-negative cumulative 'filled' amount")
    if filled + 1e-12 < previous_filled:
        raise ValueError("Cumulative filled amount moved backwards; reconciliation required")
    return max(0.0, float(filled) - float(previous_filled))


def protective_levels(entry_price: float, stop_loss_pct: float, take_profit_pct: float) -> tuple[float, float]:
    if entry_price <= 0 or not 0 < stop_loss_pct < 100 or take_profit_pct <= 0:
        raise ValueError("Invalid entry price or protective-order percentages")
    return (
        entry_price * (1 - stop_loss_pct / 100),
        entry_price * (1 + take_profit_pct / 100),
    )
