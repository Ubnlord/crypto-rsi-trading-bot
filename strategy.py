"""RSI mean-reversion with an EMA trend filter.

Long entry: RSI crosses back up through the oversold threshold while the
completed candle closes above the trend EMA. This avoids blindly buying while
RSI is falling and avoids entries below the selected trend filter.
Exit: RSI crosses above overbought. Hard stop and take-profit execution belong
to the execution/risk layer; the live bot must not assume these are exchange-side
protective orders unless it actually places and verifies them.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

Signal = Literal["BUY", "SELL", "HOLD"]


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder-style RSI using exponential smoothing."""
    if period < 2:
        raise ValueError("RSI period must be at least 2")
    delta = series.astype(float).diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    # An uninterrupted rise has RSI 100; a flat series has neutral RSI 50.
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return rsi


def compute_ema(series: pd.Series, period: int = 200) -> pd.Series:
    """EMA with a full-period warmup to avoid premature trend signals."""
    if period < 2:
        raise ValueError("EMA period must be at least 2")
    return series.astype(float).ewm(span=period, adjust=False, min_periods=period).mean()


def generate_signal(
    df: pd.DataFrame,
    rsi_period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
    ema_period: int = 200,
) -> tuple[Signal, float, float]:
    """Return signal, latest close and latest RSI using only supplied candles."""
    if not 0 < oversold < overbought < 100:
        raise ValueError("Require 0 < oversold < overbought < 100")
    if "close" not in df.columns or df.empty:
        raise ValueError("DataFrame must contain non-empty close prices")
    close = pd.to_numeric(df["close"], errors="raise")
    price = float(close.iloc[-1])
    if len(df) < max(rsi_period + 2, ema_period):
        return "HOLD", price, 50.0

    rsi = compute_rsi(close, rsi_period)
    ema = compute_ema(close, ema_period)
    current_rsi = float(rsi.iloc[-1])
    previous_rsi = float(rsi.iloc[-2])
    trend_ema = float(ema.iloc[-1])
    if not np.isfinite([current_rsi, previous_rsi, trend_ema, price]).all():
        return "HOLD", price, current_rsi if np.isfinite(current_rsi) else 50.0

    # Wait for RSI to recover from oversold; do not buy a falling RSI knife.
    if previous_rsi <= oversold and current_rsi > oversold and price > trend_ema:
        return "BUY", price, current_rsi
    # Exit on a fresh move into overbought. The execution layer handles stops.
    if previous_rsi <= overbought and current_rsi > overbought:
        return "SELL", price, current_rsi
    return "HOLD", price, current_rsi


class RSIMeanReversion:
    """Stateful signal wrapper preserving the bot's existing interface."""

    def __init__(
        self,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        ema_period: int = 200,
    ):
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.ema_period = ema_period
        self.in_position = False

    def evaluate(self, df: pd.DataFrame) -> tuple[Signal, float, float]:
        signal, price, rsi = generate_signal(
            df,
            rsi_period=self.rsi_period,
            oversold=self.oversold,
            overbought=self.overbought,
            ema_period=self.ema_period,
        )
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
