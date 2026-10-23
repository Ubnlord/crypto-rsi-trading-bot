"""Simple spot RSI backtest with explicit fees, slippage and drawdown reporting.

Uses next-bar execution to avoid filling at the same close that generated a signal.
This is a research aid, not a guarantee of live execution quality.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from strategy import compute_rsi


def run_backtest(df: pd.DataFrame, *, rsi_period: int = 14,
                 oversold: float = 30, overbought: float = 70,
                 initial_cash: float = 10_000, fee_rate: float = 0.001,
                 slippage_rate: float = 0.0005) -> dict:
    if "close" not in df or len(df) < rsi_period + 3:
        raise ValueError("Input needs a close column and sufficient historical candles")
    if initial_cash <= 0 or fee_rate < 0 or slippage_rate < 0:
        raise ValueError("Cash must be positive; fees and slippage cannot be negative")
    prices = pd.to_numeric(df["close"], errors="coerce")
    if prices.isna().any() or (prices <= 0).any():
        raise ValueError("Close prices must be finite and positive")

    rsi = compute_rsi(prices, rsi_period)
    cash, units, entry_cost = float(initial_cash), 0.0, 0.0
    trades, equity_curve = [], []
    for i in range(1, len(df) - 1):
        signal = None
        if pd.notna(rsi.iloc[i]) and pd.notna(rsi.iloc[i - 1]):
            if rsi.iloc[i] < oversold and rsi.iloc[i - 1] >= oversold:
                signal = "buy"
            elif rsi.iloc[i] > overbought and rsi.iloc[i - 1] <= overbought:
                signal = "sell"
        execution_price = float(prices.iloc[i + 1])
        if signal == "buy" and units == 0:
            fill = execution_price * (1 + slippage_rate)
            units = cash / (fill * (1 + fee_rate))
            fee = units * fill * fee_rate
            entry_cost = cash
            cash = 0.0
            trades.append({"side": "buy", "index": int(i + 1), "price": fill,
                           "amount": units, "fee": fee, "pnl": None})
        elif signal == "sell" and units > 0:
            fill = execution_price * (1 - slippage_rate)
            gross = units * fill
            fee = gross * fee_rate
            proceeds = gross - fee
            pnl = proceeds - entry_cost
            cash += proceeds
            trades.append({"side": "sell", "index": int(i + 1), "price": fill,
                           "amount": units, "fee": fee, "pnl": pnl})
            units, entry_cost = 0.0, 0.0
        mark = float(prices.iloc[i + 1])
        equity_curve.append(cash + units * mark)

    if units > 0:
        mark = float(prices.iloc[-1]) * (1 - slippage_rate)
        gross = units * mark
        fee = gross * fee_rate
        proceeds = gross - fee
        trades.append({"side": "sell_end", "index": len(df) - 1, "price": mark,
                       "amount": units, "fee": fee, "pnl": proceeds - entry_cost})
        cash += proceeds
    curve = pd.Series([initial_cash, *equity_curve, cash], dtype=float)
    drawdown = curve / curve.cummax() - 1
    sells = [t for t in trades if t["side"] in ("sell", "sell_end")]
    return {
        "initial_cash": initial_cash, "final_equity": cash,
        "net_return_pct": (cash / initial_cash - 1) * 100,
        "max_drawdown_pct": float(drawdown.min() * 100),
        "closed_trades": len(sells),
        "win_rate_pct": (sum(t["pnl"] > 0 for t in sells) / len(sells) * 100) if sells else 0,
        "fees_paid": sum(t["fee"] for t in trades),
        "assumptions": {"fee_rate": fee_rate, "slippage_rate": slippage_rate,
                        "execution": "next candle close", "open_positions": "one spot position"},
        "trades": trades,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", help="CSV containing a close column")
    parser.add_argument("--cash", type=float, default=10000)
    parser.add_argument("--fee", type=float, default=0.001, help="Fee rate, e.g. 0.001 = 0.1%%")
    parser.add_argument("--slippage", type=float, default=0.0005)
    parser.add_argument("--output", default="backtest-results.json")
    args = parser.parse_args()
    frame = pd.read_csv(Path(args.csv))
    result = run_backtest(frame, initial_cash=args.cash, fee_rate=args.fee,
                          slippage_rate=args.slippage)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "trades"}, indent=2))
    print(f"Detailed results saved to {args.output}")


if __name__ == "__main__":
    main()
