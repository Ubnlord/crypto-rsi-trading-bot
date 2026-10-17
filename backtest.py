"""Deterministic OHLCV backtester for the RSI + EMA trend-filter strategy.

Signals are evaluated on a completed candle and orders execute at the next candle's
open. Stop/target checks use the subsequent candle's high/low; if both levels are
touched in one candle, the stop is assumed first (conservative ordering).
This is a research tool, not a guarantee of live execution or profitability.
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


def load_ohlcv(path: str | Path) -> pd.DataFrame:
    """Load CSV with timestamp, open, high, low, close, volume columns."""
    df = pd.read_csv(path)
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns.str.lower())
    if missing:
        raise ValueError(f"CSV is missing required OHLCV columns: {sorted(missing)}")
    df.columns = [str(c).lower() for c in df.columns]
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="raise")
        df = df.sort_values("timestamp")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="raise")
    if df[list(required)].isna().any().any():
        raise ValueError("OHLCV data contains missing values")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (df["high"] < df[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("Invalid OHLC row: high is below another price")
    if (df["low"] > df[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("Invalid OHLC row: low is above another price")
    if len(df) < 3:
        raise ValueError("At least three candles are required")
    return df.reset_index(drop=True)


def run_backtest(df: pd.DataFrame, config: BacktestConfig = BacktestConfig()) -> dict[str, Any]:
    """Run a long-only, spot-style backtest with fees, slippage and risk sizing."""
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

    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        raise ValueError(f"DataFrame must contain {sorted(required)}")
    data = df.copy().reset_index(drop=True)
    for col in required:
        data[col] = pd.to_numeric(data[col], errors="raise")
    if len(data) < max(config.rsi_period + 5, 3):
        raise ValueError("Not enough candles for the selected RSI period")

    cash = float(config.initial_cash)
    qty = 0.0
    entry_price = 0.0
    stop_price = 0.0
    target_price = 0.0
    entry_fee = 0.0
    trades: list[dict[str, Any]] = []
    equity_curve: list[float] = [cash]
    fee_rate = config.fee_pct / 100.0
    slippage_rate = config.slippage_pct / 100.0

    def close_position(raw_price: float, timestamp: Any, reason: str) -> None:
        nonlocal cash, qty, entry_price, stop_price, target_price, entry_fee
        exit_price = raw_price * (1.0 - slippage_rate)
        gross_proceeds = qty * exit_price
        exit_fee = gross_proceeds * fee_rate
        cash += gross_proceeds - exit_fee
        pnl = (exit_price - entry_price) * qty - entry_fee - exit_fee
        trades.append({
            "entry_price": round(entry_price, 8),
            "exit_price": round(exit_price, 8),
            "quantity": round(qty, 8),
            "pnl": round(pnl, 8),
            "return_pct": round((pnl / max(entry_price * qty, 1e-12)) * 100, 6),
            "exit_reason": reason,
            "exit_index": int(i),
            "exit_timestamp": str(timestamp),
        })
        qty = 0.0
        entry_price = stop_price = target_price = entry_fee = 0.0

    # i is the candle whose OHLC data is being processed; signals from i-1
    # are executed at i's open, so no signal uses the future candle's close.
    for i in range(1, len(data)):
        row = data.iloc[i]
        timestamp = row["timestamp"] if "timestamp" in data.columns else i

        if qty > 0:
            # Gap-aware stop/target execution. Stop takes precedence if both
            # levels are touched in the same bar, avoiding optimistic bias.
            if float(row["open"]) <= stop_price:
                close_position(float(row["open"]), timestamp, "stop_gap")
            elif float(row["open"]) >= target_price:
                close_position(float(row["open"]), timestamp, "take_profit_gap")
            elif float(row["low"]) <= stop_price:
                close_position(stop_price, timestamp, "stop_loss")
            elif float(row["high"]) >= target_price:
                close_position(target_price, timestamp, "take_profit")

        if qty == 0:
            history = data.iloc[:i]
            signal, _, _ = generate_signal(
                history,
                rsi_period=config.rsi_period,
                oversold=config.oversold,
                overbought=config.overbought,
                ema_period=config.ema_period,
            )
            if signal == "BUY":
                fill_price = float(row["open"]) * (1.0 + slippage_rate)
                risk_cash = cash * config.risk_per_trade_pct / 100.0
                risk_distance = fill_price * config.stop_loss_pct / 100.0
                size_by_risk = risk_cash / risk_distance
                size_by_cap = (cash * config.max_position_pct / 100.0) / fill_price
                affordable = cash / (fill_price * (1.0 + fee_rate))
                new_qty = max(0.0, min(size_by_risk, size_by_cap, affordable))
                if new_qty > 0:
                    entry_fee = new_qty * fill_price * fee_rate
                    total_cost = new_qty * fill_price + entry_fee
                    if total_cost <= cash:
                        cash -= total_cost
                        qty = new_qty
                        entry_price = fill_price
                        stop_price = fill_price * (1.0 - config.stop_loss_pct / 100.0)
                        target_price = fill_price * (1.0 + config.take_profit_pct / 100.0)
                        trades.append({
                            "entry_price": round(entry_price, 8),
                            "quantity": round(qty, 8),
                            "entry_fee": round(entry_fee, 8),
                            "entry_index": int(i),
                            "entry_timestamp": str(timestamp),
                            "type": "entry",
                        })

        # Mark-to-market at close; cash excludes any open position's value.
        equity_curve.append(cash + qty * float(row["close"]))

    if qty > 0:
        last = data.iloc[-1]
        close_position(float(last["close"]), last.get("timestamp", len(data) - 1), "end_of_data")
        equity_curve.append(cash)

    # Pair entry and exit records for concise trade stats.
    entries = [t for t in trades if t.get("type") == "entry"]
    exits = [t for t in trades if "pnl" in t]
    final_equity = cash
    net_profit = final_equity - config.initial_cash
    wins = [t for t in exits if t["pnl"] > 0]
    losses = [t for t in exits if t["pnl"] <= 0]
    peak = config.initial_cash
    max_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak * 100.0)

    return {
        "config": asdict(config),
        "summary": {
            "initial_cash": round(config.initial_cash, 2),
            "final_equity": round(final_equity, 2),
            "net_profit": round(net_profit, 2),
            "return_pct": round(net_profit / config.initial_cash * 100.0, 4),
            "closed_trades": len(exits),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(exits) * 100.0, 2) if exits else 0.0,
            "max_drawdown_pct": round(max_drawdown, 4),
            "fees_and_slippage": "fees and configured slippage applied on entry and exit",
        },
        "trades": trades,
        "equity_curve": [round(x, 8) for x in equity_curve],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the RSI + EMA strategy on OHLCV CSV.")
    parser.add_argument("--csv", required=True, help="CSV with timestamp,open,high,low,close,volume")
    parser.add_argument("--output", default="backtest-results.json", help="Output JSON path")
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--fee-pct", type=float, default=0.1, help="Fee percent per side; 0.1 means 0.1%%")
    parser.add_argument("--slippage-pct", type=float, default=0.05, help="Slippage percent per side")
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--ema-period", type=int, default=200)
    args = parser.parse_args()
    data = load_ohlcv(args.csv)
    cfg = BacktestConfig(
        initial_cash=args.cash,
        fee_pct=args.fee_pct,
        slippage_pct=args.slippage_pct,
        rsi_period=args.rsi_period,
        ema_period=args.ema_period,
    )
    result = run_backtest(data, cfg)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Full trades/equity report written to {args.output}")


if __name__ == "__main__":
    main()
