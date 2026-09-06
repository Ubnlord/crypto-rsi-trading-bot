"""
Simple risk management helpers.
"""

from __future__ import annotations

import logging
from typing import Optional

from config import config

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
    stop_loss_pct = stop_loss_pct or config.stop_loss_pct
    risk_pct = risk_pct or config.risk_per_trade_pct
    max_position_pct = max_position_pct or config.max_position_pct

    if price <= 0 or stop_loss_pct <= 0:
        return 0.0

    risk_amount = equity * (risk_pct / 100.0)
    stop_distance = price * (stop_loss_pct / 100.0)
    size_by_risk = risk_amount / stop_distance

    max_notional = equity * (max_position_pct / 100.0)
    size_by_max = max_notional / price

    amount = min(size_by_risk, size_by_max)
    return max(0.0, amount)


def should_allow_new_position(current_open_positions: int) -> bool:
    return current_open_positions < config.max_open_positions
