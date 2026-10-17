import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path

import pandas as pd

from backtest import BacktestConfig, load_ohlcv, run_backtest
from strategy import compute_ema, compute_rsi, generate_signal


def candles(closes):
    return pd.DataFrame({
        "open": closes,
        "high": [p * 1.01 for p in closes],
        "low": [p * 0.99 for p in closes],
        "close": closes,
        "volume": [1.0] * len(closes),
    })


class StrategyTests(unittest.TestCase):
    def test_rsi_stays_in_valid_range(self):
        close = pd.Series([100 + i * 0.25 for i in range(80)])
        rsi = compute_rsi(close, 14).dropna()
        self.assertTrue(((rsi >= 0) & (rsi <= 100)).all())
        self.assertAlmostEqual(float(rsi.iloc[-1]), 100.0)

    def test_ema_requires_warmup(self):
        close = pd.Series(range(1, 50), dtype=float)
        ema = compute_ema(close, 20)
        self.assertTrue(ema.iloc[:19].isna().all())
        self.assertTrue(pd.notna(ema.iloc[19]))

    def test_short_history_never_trades(self):
        signal, _, _ = generate_signal(candles(list(range(100, 130))), ema_period=200)
        self.assertEqual(signal, "HOLD")


class BacktestTests(unittest.TestCase):
    def test_backtest_is_deterministic_and_applies_costs(self):
        data = candles([100, 100, 100, 100, 100, 100])
        config = BacktestConfig(
            initial_cash=1000, risk_per_trade_pct=1, max_position_pct=50,
            stop_loss_pct=10, take_profit_pct=20, fee_pct=0.1,
            slippage_pct=0, rsi_period=2, ema_period=2,
        )
        # At execution index 4, completed candles show RSI recovering above
        # oversold with price above EMA. The open position closes at end of data.
        rsi_values = pd.Series([50.0, 25.0, 25.0, 35.0, 40.0, 40.0])
        ema_values = pd.Series([100.0] * len(data))
        with patch("backtest.compute_rsi", return_value=rsi_values), patch("backtest.compute_ema", return_value=ema_values):
            first = run_backtest(data, config)
        with patch("backtest.compute_rsi", return_value=rsi_values), patch("backtest.compute_ema", return_value=ema_values):
            second = run_backtest(data, config)
        self.assertEqual(first, second)
        self.assertEqual(first["summary"]["closed_trades"], 1)
        self.assertLess(first["summary"]["final_equity"], 1000)

    def test_csv_loader_rejects_invalid_ohlcv(self):
        data = candles([100, 101, 102])
        data.loc[1, "high"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            data.to_csv(path, index=False)
            with self.assertRaises(ValueError):
                load_ohlcv(path)

    def test_csv_loader_rejects_missing_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text("close,open\n1,1\n2,2\n3,3\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_ohlcv(path)


if __name__ == "__main__":
    unittest.main()
