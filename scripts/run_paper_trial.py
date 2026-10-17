"""Replay historical candles through the durable paper execution engine.

This is an accelerated, deterministic paper trial, not a live market process.
It persists portfolio+journal state, reloads it at each UTC day boundary, and
writes an audit report covering gaps, rejected fills, exceptions, fees and P&L.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from backtest import load_ohlcv
from exchange import Exchange
from paper_state import default_state, load_state, save_state
from strategy import compute_ema, compute_rsi

LOG = logging.getLogger("paper_trial")


def make_engine(path: Path, cash: float, fee_pct: float, slippage_pct: float) -> Exchange:
    engine = Exchange.__new__(Exchange)
    engine.config = SimpleNamespace(
        is_live=False, stop_loss_pct=2.0, take_profit_pct=4.0
    )
    engine.paper_state_path = path
    engine.paper_fee_pct = fee_pct
    engine.paper_slippage_pct = slippage_pct
    engine.paper_state = load_state(path, initial_cash=cash)
    engine.paper_balance = float(engine.paper_state["cash"])
    engine.paper_positions = {
        symbol: float(position["amount"])
        for symbol, position in engine.paper_state["positions"].items()
    }
    engine.paper_entry_price = {
        symbol: float(position["entry_price"])
        for symbol, position in engine.paper_state["positions"].items()
    }
    engine.exchange = SimpleNamespace(fetch_ticker=lambda symbol: {"last": 1.0})
    return engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--state", default="paper-trial-state.json")
    parser.add_argument("--report", default="paper-trial-report.json")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--fee-pct", type=float, default=0.1)
    parser.add_argument("--slippage-pct", type=float, default=0.05)
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--oversold", type=float, default=30.0)
    parser.add_argument("--overbought", type=float, default=70.0)
    parser.add_argument("--ema-period", type=int, default=200)
    args = parser.parse_args()

    if not math.isfinite(args.cash) or args.cash <= 0:
        raise ValueError("cash must be finite and positive")
    if not 0 <= args.fee_pct < 100 or not 0 <= args.slippage_pct < 100:
        raise ValueError("fee and slippage must be in [0, 100)")
    if args.rsi_period < 2 or args.ema_period < 2:
        raise ValueError("indicator periods must be at least 2")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    data = load_ohlcv(args.csv)
    if "timestamp" not in data.columns:
        raise ValueError("Paper trial requires timestamped OHLCV")
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True, errors="raise")
    if data["timestamp"].duplicated().any() or not data["timestamp"].is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(data) < max(args.rsi_period + 2, args.ema_period) + 2:
        raise ValueError("not enough candles for indicator warmup")

    state_path = Path(args.state)
    report_path = Path(args.report)
    if state_path.exists():
        raise RuntimeError(f"Refusing to overwrite existing trial state: {state_path}. Use a fresh path.")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    save_state(state_path, default_state(args.cash))

    close = data["close"].astype(float)
    rsi = compute_rsi(close, args.rsi_period)
    ema = compute_ema(close, args.ema_period)
    engine = make_engine(state_path, args.cash, args.fee_pct, args.slippage_pct)
    counters: dict[str, Any] = {
        "candles_seen": 0, "timestamp_gaps": 0, "daily_restarts": 0,
        "protective_exit_attempts": 0, "protective_exits_filled": 0,
        "signal_entries": 0, "signal_exits": 0, "rejected_fills": 0,
        "exceptions": [], "missed_candle_timestamps": [],
    }
    last_day = None
    last_timestamp = None
    equity_peak = args.cash
    max_drawdown_pct = 0.0

    for i, candle in data.iterrows():
        timestamp = candle["timestamp"]
        day = timestamp.date().isoformat()
        if last_day is not None and day != last_day:
            # Daily restart: discard in-memory caches and rebuild exclusively
            # from the atomically persisted state/journal.
            engine = make_engine(state_path, args.cash, args.fee_pct, args.slippage_pct)
            counters["daily_restarts"] += 1
        last_day = day
        if last_timestamp is not None:
            delta = timestamp - last_timestamp
            if delta != pd.Timedelta(hours=1):
                counters["timestamp_gaps"] += 1
                counters["missed_candle_timestamps"].append({
                    "after": str(last_timestamp), "before": str(timestamp),
                    "gap_seconds": int(delta.total_seconds()),
                    "expected_candles_missing": max(0, int(delta.total_seconds() // 3600) - 1),
                })
        last_timestamp = timestamp
        counters["candles_seen"] += 1

        try:
            if i < max(args.rsi_period + 2, args.ema_period):
                continue
            price = float(candle["close"])
            position = engine.paper_state["positions"].get(args.symbol)

            # Protective exit logic is evaluated against each candle's OHLC.
            if position:
                counters["protective_exit_attempts"] += 1
                before = len(engine.paper_state["trade_journal"])
                result = engine.check_paper_protective_exit(
                    args.symbol, price, candle_open=float(candle["open"]),
                    candle_high=float(candle["high"]), candle_low=float(candle["low"]),
                )
                if result and result.get("status") == "closed":
                    counters["protective_exits_filled"] += 1
                    engine.paper_state["trade_journal"][-1]["timestamp"] = timestamp.isoformat()
                    save_state(state_path, engine.paper_state)
                    continue
                if result and result.get("status") == "rejected":
                    counters["rejected_fills"] += 1
                if len(engine.paper_state["trade_journal"]) != before:
                    continue

            previous_rsi = float(rsi.iloc[i - 1])
            current_rsi = float(rsi.iloc[i])
            trend = float(ema.iloc[i - 1])
            prior_close = float(close.iloc[i - 1])
            buy_signal = (
                not position and math.isfinite(previous_rsi) and math.isfinite(current_rsi)
                and math.isfinite(trend) and previous_rsi <= args.oversold
                and current_rsi > args.oversold and price > float(ema.iloc[i])
            )
            sell_signal = (
                position and math.isfinite(previous_rsi) and math.isfinite(current_rsi)
                and previous_rsi <= args.overbought and current_rsi > args.overbought
            )
            # Signal generated by the prior completed candle fills at this
            # candle's open; indicators only look backward.
            if i > 0:
                prior_prev_rsi = float(rsi.iloc[i - 2]) if i >= 2 else float("nan")
                signal_buy = (
                    not position and math.isfinite(prior_prev_rsi) and math.isfinite(previous_rsi)
                    and math.isfinite(float(ema.iloc[i - 1]))
                    and prior_prev_rsi <= args.oversold and previous_rsi > args.oversold
                    and prior_close > float(ema.iloc[i - 1])
                )
                signal_sell = (
                    position and math.isfinite(prior_prev_rsi) and math.isfinite(previous_rsi)
                    and prior_prev_rsi <= args.overbought and previous_rsi > args.overbought
                )
            else:
                signal_buy = signal_sell = False

            if signal_buy:
                # 10% of cash notional cap; never leverage the paper account.
                open_price = float(candle["open"])
                amount = min(engine.paper_balance / (open_price * (1 + args.fee_pct / 100)), engine.paper_balance * 0.10 / open_price)
                if amount <= 0 or not math.isfinite(amount):
                    counters["rejected_fills"] += 1
                else:
                    result = engine._paper_fill(args.symbol, "buy", amount, execution_price=open_price)
                    if result.get("status") == "closed":
                        counters["signal_entries"] += 1
                        engine.paper_state["trade_journal"][-1]["timestamp"] = timestamp.isoformat()
                        save_state(state_path, engine.paper_state)
                    else:
                        counters["rejected_fills"] += 1
            elif signal_sell and position:
                result = engine._paper_fill(args.symbol, "sell", float(position["amount"]), execution_price=float(candle["open"]))
                if result.get("status") == "closed":
                    counters["signal_exits"] += 1
                    engine.paper_state["trade_journal"][-1]["timestamp"] = timestamp.isoformat()
                    save_state(state_path, engine.paper_state)
                else:
                    counters["rejected_fills"] += 1
        except Exception as exc:
            counters["exceptions"].append({"timestamp": timestamp.isoformat(), "type": type(exc).__name__, "message": str(exc)})
            LOG.exception("Paper trial exception at %s", timestamp)

        # Reconcile from disk periodically and after every UTC day boundary.
        try:
            saved = load_state(state_path)
            if abs(float(saved["cash"]) - float(engine.paper_balance)) > 1e-8:
                raise RuntimeError("persisted cash differs from engine cash")
            for symbol, saved_position in saved["positions"].items():
                if abs(float(saved_position["amount"]) - engine.paper_positions.get(symbol, 0.0)) > 1e-8:
                    raise RuntimeError(f"persisted quantity mismatch for {symbol}")
        except Exception as exc:
            counters["exceptions"].append({"timestamp": timestamp.isoformat(), "type": type(exc).__name__, "message": f"reconciliation: {exc}"})
            raise

    engine = make_engine(state_path, args.cash, args.fee_pct, args.slippage_pct)
    state = load_state(state_path)
    final_price = float(data["close"].iloc[-1])
    open_positions_value = sum(float(p["amount"]) * final_price for p in state["positions"].values())
    final_equity = float(state["cash"]) + open_positions_value
    pnl = final_equity - args.cash
    journal = state["trade_journal"]
    fees = sum(float(record["fee"]) for record in journal)
    ids = [record["id"] for record in journal]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate trade journal IDs found at trial end")
    if journal and abs(float(journal[-1]["cash_after"]) - float(state["cash"])) > 1e-8:
        raise RuntimeError("final cash does not reconcile to last journal record")
    report = {
        "trial_type": "accelerated historical paper replay with daily persisted-state restarts",
        "live_exchange_orders_sent": False,
        "start_timestamp": data["timestamp"].iloc[0].isoformat(),
        "end_timestamp": data["timestamp"].iloc[-1].isoformat(),
        "candles_seen": counters["candles_seen"],
        "unique_candles": int(data["timestamp"].nunique()),
        "timestamp_gaps": counters["timestamp_gaps"],
        "missed_candle_timestamps": counters["missed_candle_timestamps"],
        "daily_restarts": counters["daily_restarts"],
        "rejected_fills": counters["rejected_fills"],
        "exceptions": counters["exceptions"],
        "trade_journal_entries": len(journal),
        "unique_trade_ids": len(set(ids)),
        "fees_paid": round(fees, 8),
        "starting_cash": args.cash,
        "ending_cash": round(float(state["cash"]), 8),
        "open_position_mark_to_market": round(open_positions_value, 8),
        "ending_equity": round(final_equity, 8),
        "net_pnl": round(pnl, 8),
        "net_return_pct": round(pnl / args.cash * 100, 6),
        "closed_trades": len(journal) // 2,
        "signal_entries": counters["signal_entries"],
        "signal_exits": counters["signal_exits"],
        "protective_exit_attempts": counters["protective_exit_attempts"],
        "protective_exits_filled": counters["protective_exits_filled"],
        "journal_reconciled": True,
        "warning": "Accelerated historical replay is not a real-time multi-session paper trial and does not validate exchange execution.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
