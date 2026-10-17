"""Run a historical backtest and attribute closed trades to market regimes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import BacktestConfig, load_ohlcv, run_backtest
from strategy import compute_ema


def trade_group(trades: list[dict], labels: pd.Series) -> list[dict]:
    output = []
    for label in sorted(labels.dropna().unique()):
        selected = [t for t in trades if pd.notna(labels.iloc[int(t["entry_index"])]) and labels.iloc[int(t["entry_index"])] == label]
        pnl = [float(t["pnl"]) for t in selected]
        gross_wins = sum(x for x in pnl if x > 0)
        gross_losses = abs(sum(x for x in pnl if x < 0))
        output.append({
            "regime": str(label),
            "trades": len(selected),
            "net_pnl": round(sum(pnl), 2),
            "win_rate_pct": round(sum(x > 0 for x in pnl) / len(pnl) * 100, 2) if pnl else 0.0,
            "profit_factor": round(gross_wins / gross_losses, 3) if gross_losses else (None if not gross_wins else "infinite"),
            "average_trade_pnl": round(float(np.mean(pnl)), 2) if pnl else 0.0,
        })
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="data/BTCUSDT_1h.csv")
    parser.add_argument("--output", default="backtest-report.json")
    parser.add_argument("--cash", type=float, default=10000)
    parser.add_argument("--fee-pct", type=float, default=0.1)
    parser.add_argument("--slippage-pct", type=float, default=0.05)
    args = parser.parse_args()

    data = load_ohlcv(args.csv)
    if "timestamp" not in data:
        raise ValueError("Research evaluation requires timestamped market data")
    if data["timestamp"].duplicated().any() or not data["timestamp"].is_monotonic_increasing:
        raise ValueError("Timestamped data must be unique and strictly chronological")

    cfg = BacktestConfig(
        initial_cash=args.cash,
        fee_pct=args.fee_pct,
        slippage_pct=args.slippage_pct,
    )
    result = run_backtest(data, cfg)
    ema = compute_ema(data["close"], cfg.ema_period)
    returns = data["close"].pct_change()
    # 30-day realised volatility annualised from hourly close-to-close returns.
    vol = returns.rolling(24 * 30, min_periods=24 * 15).std() * np.sqrt(24 * 365)
    vol_cut = float(vol.dropna().median()) if vol.notna().any() else float("nan")
    trend_labels = pd.Series(
        np.where(data["close"] >= ema, "close_at_or_above_ema200", "close_below_ema200"),
        index=data.index,
    ).where(ema.notna())
    vol_labels = pd.Series(
        np.where(vol >= vol_cut, "high_realised_volatility", "low_realised_volatility"),
        index=data.index,
    ).where(vol.notna())
    combined_labels = (trend_labels.astype("string") + " / " + vol_labels.astype("string")).where(
        trend_labels.notna() & vol_labels.notna()
    )

    for trade in result["trades"]:
        idx = int(trade["entry_index"])
        trade["entry_trend_regime"] = str(trend_labels.iloc[idx]) if pd.notna(trend_labels.iloc[idx]) else "warmup"
        trade["entry_volatility_regime"] = str(vol_labels.iloc[idx]) if pd.notna(vol_labels.iloc[idx]) else "warmup"
        trade["entry_combined_regime"] = str(combined_labels.iloc[idx]) if pd.notna(combined_labels.iloc[idx]) else "warmup"

    result["data_quality"] = {
        "source_expected": "Binance Vision official monthly spot kline archives",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "candles": len(data),
        "start_utc": data["timestamp"].iloc[0].isoformat(),
        "end_utc": data["timestamp"].iloc[-1].isoformat(),
        "duplicate_timestamps": int(data["timestamp"].duplicated().sum()),
        "timestamp_gaps": int((data["timestamp"].diff().dropna() != pd.Timedelta(hours=1)).sum()),
        "gap_intervals_utc": [
            {"last_available": data["timestamp"].iloc[i - 1].isoformat(),
             "next_available": data["timestamp"].iloc[i].isoformat()}
            for i in range(1, len(data))
            if data["timestamp"].iloc[i] - data["timestamp"].iloc[i - 1] != pd.Timedelta(hours=1)
        ],
        "gap_policy": "No candles are fabricated; the backtester exits an open position at the next available open and suppresses new entries on that gap bar.",
        "note": "Archive gaps are reported and handled conservatively rather than silently forward-filled.",
    }
    result["market_regime_analysis"] = {
        "classification_method": "At trade entry: close vs EMA200; high/low realised volatility split at full-sample median of annualised 30-day hourly volatility. Retrospective descriptive grouping, not a predictive signal.",
        "volatility_median_annualised": round(vol_cut, 6) if np.isfinite(vol_cut) else None,
        "by_trend": trade_group(result["trades"], trend_labels),
        "by_volatility": trade_group(result["trades"], vol_labels),
        "by_combined_regime": trade_group(result["trades"], combined_labels),
    }
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "data_quality": result["data_quality"],
        "summary": result["summary"],
        "market_regime_analysis": result["market_regime_analysis"],
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
