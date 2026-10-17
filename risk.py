"""
Simple risk management helpers.
"""

from __future__ import annotations

import logging
from typing import Optional

from config import MAX_RISK_PER_TRADE_PCT, config

logger = logging.getLogger(__name__)


def calculate_position_size(
    equity: float,
    price: float,
    stop_loss_pct: float = None,
    risk_pct: float = None,
    max_position_pct: float = None,
) -> float:
    """
    Position size based on fixed fractional risk.
    amount = (equity * risk_pct / 100) / (price * stop_loss_pct / 100)
    Capped by max_position_pct of equity.
    """
    stop_loss_pct = config.stop_loss_pct if stop_loss_pct is None else stop_loss_pct
    risk_pct = config.risk_per_trade_pct if risk_pct is None else risk_pct
    max_position_pct = config.max_position_pct if max_position_pct is None else max_position_pct

    if not all(map(lambda x: isinstance(x, (int, float)) and x == x and abs(x) != float("inf"),
                   (equity, price, stop_loss_pct, risk_pct, max_position_pct))):
        raise ValueError("Risk sizing inputs must be finite numbers")
    if equity <= 0 or price <= 0 or stop_loss_pct <= 0:
        return 0.0
    if not 0 < risk_pct <= MAX_RISK_PER_TRADE_PCT:
        raise ValueError("Risk per trade must be greater than 0 and at most 0.25%")
    if not 0 < max_position_pct <= 100:
        raise ValueError("MAX_POSITION_PCT must be greater than 0 and at most 100")

    risk_amount = equity * (risk_pct / 100.0)
    stop_distance = price * (stop_loss_pct / 100.0)
    size_by_risk = risk_amount / stop_distance

    max_notional = equity * (max_position_pct / 100.0)
    size_by_max = max_notional / price

    amount = min(size_by_risk, size_by_max)
    return max(0.0, amount)


def should_allow_new_position(current_open_positions: int) -> bool:
    return current_open_positions < config.max_open_positions
