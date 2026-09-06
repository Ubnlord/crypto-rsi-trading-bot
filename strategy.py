"""
RSI Mean-Reversion Strategy.

Buy when RSI crosses below oversold threshold (mean-reversion long).
Sell / close when RSI crosses above overbought threshold.
This is a simple educational starting point — not financial advice.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Optional, Literal

Signal = Literal["BUY", "SELL", "HOLD"]


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder-style RSI (exponential smoothing)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Wilder's smoothing (EMA with alpha = 1/period)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def generate_signal(
    df: pd.DataFrame,
    rsi_period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
) -> tuple[Signal, float, float]:
    """
    Returns (signal, current_price, current_rsi).

    Simple mean-reversion rules:
    - BUY when RSI < oversold
    - SELL when RSI > overbought
    - HOLD otherwise
    """
    if len(df) < rsi_period + 5:
        return "HOLD", float(df["close"].iloc[-1]), 50.0

    df = df.copy()
    df["rsi"] = compute_rsi(df["close"], period=rsi_period)

    current_rsi = float(df["rsi"].iloc[-1])
    current_price = float(df["close"].iloc[-1])
    prev_rsi = float(df["rsi"].iloc[-2]) if len(df) > 1 else current_rsi

    # Cross into oversold → BUY
    if current_rsi < oversold and prev_rsi >= oversold:
        return "BUY", current_price, current_rsi
    # Already deeply oversold (optional stronger entry)
    if current_rsi < oversold - 5:
        return "BUY", current_price, current_rsi

    # Cross into overbought → SELL
    if current_rsi > overbought and prev_rsi <= overbought:
        return "SELL", current_price, current_rsi
    if current_rsi > overbought + 5:
        return "SELL", current_price, current_rsi

    return "HOLD", current_price, current_rsi


class RSIMeanReversion:
    """Stateful wrapper that also tracks whether we currently hold a position."""

    def __init__(
        self,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
    ):
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.in_position = False

    def evaluate(self, df: pd.DataFrame) -> tuple[Signal, float, float]:
        signal, price, rsi = generate_signal(
            df, self.rsi_period, self.oversold, self.overbought
        )

        # Only act if state matches
        if signal == "BUY" and not self.in_position:
            return "BUY", price, rsi
        if signal == "SELL" and self.in_position:
            return "SELL", price, rsi
        return "HOLD", price, rsi

    def on_filled(self, side: str) -> None:
        if side.lower() == "buy":
            self.in_position = True
        elif side.lower() == "sell":
            self.in_position = False
