"""Deterministic OHLCV backtester for the RSI recovery + EMA trend strategy.

Signals use completed candles and execute at the next candle open. Stop/target
checks use that candle's high/low. If both levels are touched, stop wins.
Research tool only; results are not a promise of live performance.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from strategy import generate_signal


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 10_000.0
    risk_per_trade_pct: float = 1.0
    max_position_pct: float = 10.0
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 4.0
    fee_pct: float = 0.1
    slippage_pct: float = 0.05
    rsi_period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0
    ema_period: int = 200


def _validate_ohlcv(df: pd.DataFrame) -> None:
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        raise ValueError(f"DataFrame must contain {sorted(required)}")
    if len(df) < 3:
        raise ValueError("At least three candles are required")
    for col in required:
        if df[col].isna().any():
            raise ValueError(f"OHLCV column {col} contains missing values")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (df["high"] < df[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("Invalid OHLC row: high is below another price")
    if (df["low"] > df[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("Invalid OHLC row: low is above another price")


def load_ohlcv(path: str | Path) -> pd.DataFrame:
    """Load and validate CSV with timestamp (optional) and OHLCV columns."""
    df = pd.read_csv(path)
    df.columns = [str(c).lower() for c in df.columns]
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required OHLCV columns: {sorted(missing)}")
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="raise")
        df = df.sort_values("timestamp")
    for col in required:
        df[col] = pd.to_numeric(df[col], errors="raise")
    _validate_ohlcv(df)
    return df.reset_index(drop=True)


def run_backtest(df: pd.DataFrame, config: BacktestConfig = BacktestConfig()) -> dict[str, Any]:
    """Run a long-only spot simulation with fees, slippage and capped risk sizing."""
    if config.initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if not 0 < config.risk_per_trade_pct <= 100:
        raise ValueError("risk_per_trade_pct must be in (0, 100]")
    if not 0 < config.max_position_pct <= 100:
        raise ValueError("max_position_pct must be in (0, 100]")
    if not 0 < config.stop_loss_pct < 100 or config.take_profit_pct <= 0:
        raise ValueError("stop_loss_pct must be in (0, 100) and take_profit_pct positive")
    if min(config.fee_pct, config.slippage_pct) < 0:
        raise ValueError("fees and slippage cannot be negative")
    if config.rsi_period < 2 or config.ema_period < 2:
        raise ValueError("RSI and EMA periods must be at least 2")

    data = df.copy().reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        if col in data:
            data[col] = pd.to_numeric(data[col], errors="raise")
    _validate_ohlcv(data)
    if len(data) < max(config.rsi_period + 2, config.ema_period):
        raise ValueError("Not enough candles for selected RSI/EMA periods")

    cash = float(config.initial_cash)
    qty = entry_price = stop_price = target_price = entry_fee = 0.0
    trades: list[dict[str, Any]] = []
    equity_curve = [cash]
    fee_rate = config.fee_pct / 100.0
    slip_rate = config.slippage_pct / 100.0

    def close_position(raw_price: float, timestamp: Any, index: int, reason: str) -> None:
        nonlocal cash, qty, entry_price, stop_price, target_price, entry_fee
        exit_price = raw_price * (1.0 - slip_rate)
        proceeds = qty * exit_price
        exit_fee = proceeds * fee_rate
        cash += proceeds - exit_fee
        pnl = (exit_price - entry_price) * qty - entry_fee - exit_fee
        trades.append({
            "entry_index": entry_index,
            "exit_index": int(index),
            "entry_timestamp": str(entry_timestamp),
            "exit_timestamp": str(timestamp),
            "entry_price": round(entry_price, 8),
            "exit_price": round(exit_price, 8),
            "quantity": round(qty, 8),
            "entry_fee": round(entry_fee, 8),
            "exit_fee": round(exit_fee, 8),
            "pnl": round(pnl, 8),
            "return_pct": round(pnl / max(entry_price * qty, 1e-12) * 100.0, 6),
            "exit_reason": reason,
        })
        qty = entry_price = stop_price = target_price = entry_fee = 0.0

    entry_index = 0
    entry_timestamp: Any = None
    for i in range(1, len(data)):
        row = data.iloc[i]
        timestamp = row["timestamp"] if "timestamp" in data.columns else i
        # Only candles strictly before this execution candle are used for signals.
        signal, _, _ = generate_signal(
            data.iloc[:i],
            rsi_period=config.rsi_period,
            oversold=config.oversold,
            overbought=config.overbought,
            ema_period=config.ema_period,
        )
        exited_this_bar = False

        if qty > 0:
            if float(row["open"]) <= stop_price:
                close_position(float(row["open"]), timestamp, i, "stop_gap")
                exited_this_bar = True
            elif float(row["open"]) >= target_price:
                close_position(float(row["open"]), timestamp, i, "take_profit_gap")
                exited_this_bar = True
            elif float(row["low"]) <= stop_price:
                close_position(stop_price, timestamp, i, "stop_loss")
                exited_this_bar = True
            elif float(row["high"]) >= target_price:
                close_position(target_price, timestamp, i, "take_profit")
                exited_this_bar = True
            elif signal == "SELL":
                close_position(float(row["open"]), timestamp, i, "rsi_exit")
                exited_this_bar = True

        if qty == 0 and not exited_this_bar and signal == "BUY":
            fill = float(row["open"]) * (1.0 + slip_rate)
            risk_cash = cash * config.risk_per_trade_pct / 100.0
            risk_distance = fill * config.stop_loss_pct / 100.0
            size_risk = risk_cash / risk_distance
            size_cap = cash * config.max_position_pct / 100.0 / fill
            size_affordable = cash / (fill * (1.0 + fee_rate))
            new_qty = max(0.0, min(size_risk, size_cap, size_affordable))
            cost = new_qty * fill
            fee = cost * fee_rate
            if new_qty > 0 and cost + fee <= cash:
                cash -= cost + fee
                qty = new_qty
                entry_price = fill
                entry_fee = fee
                stop_price = fill * (1.0 - config.stop_loss_pct / 100.0)
                target_price = fill * (1.0 + config.take_profit_pct / 100.0)
                entry_index, entry_timestamp = i, timestamp

        equity_curve.append(cash + qty * float(row["close"]))

    if qty > 0:
        last = data.iloc[-1]
        close_position(float(last["close"]), last.get("timestamp", len(data) - 1),
                       len(data) - 1, "end_of_data")
        equity_curve.append(cash)

    wins = [trade for trade in trades if trade["pnl"] > 0]
    losses = [trade for trade in trades if trade["pnl"] <= 0]
    peak = float(config.initial_cash)
    max_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak * 100.0)
    net_profit = cash - config.initial_cash
    return {
        "config": asdict(config),
        "summary": {
            "initial_cash": round(config.initial_cash, 2),
            "final_equity": round(cash, 2),
            "net_profit": round(net_profit, 2),
            "return_pct": round(net_profit / config.initial_cash * 100.0, 4),
            "closed_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(trades) * 100.0, 2) if trades else 0.0,
            "max_drawdown_pct": round(max_drawdown, 4),
            "cost_model": "fee and slippage charged on entry and exit",
        },
        "trades": trades,
        "equity_curve": [round(value, 8) for value in equity_curve],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest RSI recovery + EMA trend strategy.")
    parser.add_argument("--csv", required=True, help="CSV: timestamp,open,high,low,close,volume")
    parser.add_argument("--output", default="backtest-results.json")
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--fee-pct", type=float, default=0.1, help="Per-side fee percentage")
    parser.add_argument("--slippage-pct", type=float, default=0.05, help="Per-side slippage percentage")
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--ema-period", type=int, default=200)
    args = parser.parse_args()
    result = run_backtest(load_ohlcv(args.csv), BacktestConfig(
        initial_cash=args.cash, fee_pct=args.fee_pct, slippage_pct=args.slippage_pct,
        rsi_period=args.rsi_period, ema_period=args.ema_period,
    ))
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Full report written to {args.output}")


if __name__ == "__main__":
    main()
