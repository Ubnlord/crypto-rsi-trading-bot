"""Fail-closed risk sizing helpers shared by crypto and forex.

Risk budget is capped at 0.25% of equity per trade in this build. These
helpers size a proposed trade only; they do not submit orders or guarantee
realized loss stays below budget (gaps, slippage and fees can exceed it).
"""
from __future__ import annotations
import math

MAX_RISK_PER_TRADE_PCT = 0.25

def risk_budget(equity: float, risk_pct: float = MAX_RISK_PER_TRADE_PCT) -> float:
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError("Equity must be finite and positive")
    if not math.isfinite(risk_pct) or not 0 < risk_pct <= MAX_RISK_PER_TRADE_PCT:
        raise ValueError("Risk per trade must be greater than 0 and at most 0.25%")
    return equity * risk_pct / 100.0

def crypto_amount_from_stop(equity: float, entry_price: float, stop_price: float, *,
                            risk_pct: float = MAX_RISK_PER_TRADE_PCT,
                            max_notional_pct: float = 10.0,
                            fee_buffer_pct: float = 0.2) -> float:
    """Return base-asset quantity, capped by stop risk and notional allocation."""
    if not all(math.isfinite(x) for x in (entry_price, stop_price, max_notional_pct, fee_buffer_pct)):
        raise ValueError("Prices and caps must be finite")
    if entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
        raise ValueError("Long spot trade requires 0 < stop < entry")
    if not 0 < max_notional_pct <= 100 or not 0 <= fee_buffer_pct < 10:
        raise ValueError("Invalid notional or fee buffer cap")
    budget = risk_budget(equity, risk_pct)
    loss_per_unit = (entry_price - stop_price) * (1.0 + fee_buffer_pct / 100.0)
    by_risk = budget / loss_per_unit
    by_notional = equity * max_notional_pct / 100.0 / entry_price
    return max(0.0, min(by_risk, by_notional))

def forex_volume_from_stop(equity: float, loss_per_lot_at_stop: float, *,
                           risk_pct: float = MAX_RISK_PER_TRADE_PCT,
                           min_volume: float = 0.01, max_volume: float = 100.0,
                           volume_step: float = 0.01) -> float:
    """Size MT5 lots from broker-calculated account-currency loss per lot."""
    vals = (loss_per_lot_at_stop, min_volume, max_volume, volume_step)
    if not all(math.isfinite(x) for x in vals):
        raise ValueError("Forex sizing inputs must be finite")
    if loss_per_lot_at_stop <= 0 or min_volume <= 0 or max_volume < min_volume or volume_step <= 0:
        raise ValueError("Invalid broker loss or volume limits")
    raw = min(risk_budget(equity, risk_pct) / loss_per_lot_at_stop, max_volume)
    steps = math.floor((raw + 1e-12) / volume_step)
    volume = round(steps * volume_step, 8)
    if volume + 1e-12 < min_volume:
        return 0.0
    return min(volume, max_volume)
