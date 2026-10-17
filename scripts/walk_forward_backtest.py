"""Chronological holdout experiment for RSI/EMA strategy research.

Parameters are selected on the training segment only. The final holdout is not
used to choose parameters. The holdout is prefixed with pre-split candles only
for indicator warmup; trading begins at the split boundary.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from backtest import BacktestConfig, load_ohlcv, run_backtest


def score(summary: dict) -> float:
    """Simple train-only ranking: return less a conservative drawdown penalty."""
    return float(summary["return_pct"]) - 0.5 * float(summary["max_drawdown_pct"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--output", default="walk-forward-report.json")
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--fee-pct", type=float, default=0.1)
    parser.add_argument("--slippage-pct", type=float, default=0.05)
    parser.add_argument("--train-fraction", type=float, default=0.7)
    args = parser.parse_args()
    if not 0.5 <= args.train_fraction <= 0.85:
        raise ValueError("train-fraction must be between 0.5 and 0.85")

    data = load_ohlcv(args.csv)
    split = int(len(data) * args.train_fraction)
    if split < 400 or len(data) - split < 400:
        raise ValueError("Not enough candles for training and held-out evaluation")
    train = data.iloc[:split].reset_index(drop=True)

    # A small, predeclared grid avoids silently searching the held-out period.
    candidates = []
    for ema_period in (100, 200, 300):
        for oversold in (25.0, 30.0):
            cfg = BacktestConfig(
                initial_cash=args.cash,
                fee_pct=args.fee_pct,
                slippage_pct=args.slippage_pct,
                rsi_period=14,
                oversold=oversold,
                overbought=70.0,
                ema_period=ema_period,
            )
            result = run_backtest(train, cfg)
            candidates.append({
                "config": asdict(cfg),
                "training_summary": result["summary"],
                "training_score": round(score(result["summary"]), 6),
            })
    candidates.sort(key=lambda item: item["training_score"], reverse=True)
    selected = candidates[0]["config"]
    baseline = BacktestConfig(
        initial_cash=args.cash, fee_pct=args.fee_pct, slippage_pct=args.slippage_pct,
        rsi_period=14, oversold=30.0, overbought=70.0, ema_period=200,
    )

    # Include only pre-split candles needed to warm up indicators. With the
    # backtest's full-period EMA warmup, the first possible trade is at split.
    warmup = max(baseline.ema_period, selected["ema_period"], baseline.rsi_period + 2) + 2
    holdout_start = max(0, split - warmup)
    holdout = data.iloc[holdout_start:].reset_index(drop=True)
    baseline_result = run_backtest(holdout, baseline)
    selected_result = run_backtest(holdout, BacktestConfig(**selected))

    report = {
        "method": "chronological single holdout; small predeclared parameter grid; no holdout tuning",
        "data_start": str(data["timestamp"].iloc[0]) if "timestamp" in data.columns else None,
        "data_end": str(data["timestamp"].iloc[-1]) if "timestamp" in data.columns else None,
        "candles": len(data),
        "split_index": split,
        "train_fraction": args.train_fraction,
        "training_candidates_ranked": candidates,
        "selected_config_from_training_only": selected,
        "holdout": {
            "evaluation_start_index": split,
            "warmup_prefix_candles_not_intended_for_trading": split - holdout_start,
            "baseline_config": asdict(baseline),
            "baseline_summary": baseline_result["summary"],
            "selected_config_summary": selected_result["summary"],
            "selected_minus_baseline_return_percentage_points": round(
                selected_result["summary"]["return_pct"] - baseline_result["summary"]["return_pct"], 4
            ),
            "warning": "The holdout is one historical sample, not proof of future profitability. Do not retune against it.",
        },
    }
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["holdout"], indent=2))
    print(f"Full walk-forward report written to {args.output}")


if __name__ == "__main__":
    main()
