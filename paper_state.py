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
        "trade_journal": [],
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

    # Older schema-v1 state files predate the embedded journal; preserve their
    # balances and add an empty journal rather than resetting portfolio state.
    journal = state.setdefault("trade_journal", [])
    if not isinstance(journal, list):
        raise RuntimeError("Paper state has invalid trade journal")
    journal_ids: set[str] = set()
    for record in journal:
        if not isinstance(record, dict):
            raise RuntimeError("Paper state has invalid trade journal record")
        required = ("id", "timestamp", "symbol", "side", "amount", "price", "fee", "cash_after")
        if any(key not in record for key in required):
            raise RuntimeError("Paper state has incomplete trade journal record")
        if not isinstance(record["id"], str) or not record["id"] or record["id"] in journal_ids:
            raise RuntimeError("Paper state has duplicate or invalid trade journal ID")
        if not isinstance(record["timestamp"], str) or not record["timestamp"]:
            raise RuntimeError("Paper state has invalid trade journal timestamp")
        if not isinstance(record["symbol"], str) or not record["symbol"]:
            raise RuntimeError("Paper state has invalid trade journal symbol")
        if record["side"] not in ("buy", "sell"):
            raise RuntimeError("Paper state has invalid trade journal side")
        for key in ("amount", "price", "fee", "cash_after"):
            value = record[key]
            if not _finite_number(value) or value < 0 or (key in ("amount", "price") and value == 0):
                raise RuntimeError(f"Paper state has invalid trade journal {key}")
        if "position_after" in record and (not _finite_number(record["position_after"]) or record["position_after"] < 0):
            raise RuntimeError("Paper state has invalid trade journal position_after")
        journal_ids.add(record["id"])
    if journal and abs(float(journal[-1]["cash_after"]) - float(cash)) > 1e-8:
        raise RuntimeError("Paper cash balance does not reconcile to the latest trade journal record")
    last_position_record: dict[str, dict[str, Any]] = {}
    for record in journal:
        if "position_after" in record:
            last_position_record[record["symbol"]] = record
    for symbol, record in last_position_record.items():
        persisted_amount = float(positions.get(symbol, {}).get("amount", 0.0))
        if abs(persisted_amount - float(record["position_after"])) > 1e-8:
            raise RuntimeError(f"Paper position for {symbol} does not reconcile to trade journal")
    if not journal_ids.issubset(set(order_ids)):
        raise RuntimeError("Paper trade journal and processed order IDs disagree")

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


def append_trade_record(state: dict[str, Any], record: dict[str, Any]) -> bool:
    """Add a paper fill to the same atomically persisted state as its balances.

    Returns False for an already-recorded ID, preventing duplicate journal entries
    when an identical fill event is retried by a caller.
    """
    validate_state(state)
    order_id = record.get("id")
    if not isinstance(order_id, str) or not order_id:
        raise ValueError("Trade journal record requires a non-empty id")
    if order_id in state["processed_order_ids"]:
        return False
    candidate = dict(state)
    candidate["trade_journal"] = list(state["trade_journal"])
    candidate["processed_order_ids"] = list(state["processed_order_ids"])
    candidate["trade_journal"].append(dict(record))
    candidate["processed_order_ids"].append(order_id)
    validate_state(candidate)
    state["trade_journal"] = candidate["trade_journal"]
    state["processed_order_ids"] = candidate["processed_order_ids"]
    return True
