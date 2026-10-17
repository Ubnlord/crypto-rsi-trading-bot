import unittest
from unittest.mock import patch

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
        # Force one entry on the first available signal check; later calls HOLD.
        with patch("backtest.generate_signal", side_effect=[
            ("BUY", 100, 25), ("HOLD", 100, 40), ("HOLD", 100, 45),
            ("HOLD", 100, 50), ("HOLD", 100, 50),
        ]):
            first = run_backtest(data, config)
        with patch("backtest.generate_signal", side_effect=[
            ("BUY", 100, 25), ("HOLD", 100, 40), ("HOLD", 100, 45),
            ("HOLD", 100, 50), ("HOLD", 100, 50),
        ]):
            second = run_backtest(data, config)
        self.assertEqual(first, second)
        self.assertEqual(first["summary"]["closed_trades"], 1)
        self.assertLess(first["summary"]["final_equity"], 1000)

    def test_bad_ohlcv_is_rejected(self):
        data = candles([100, 101, 102])
        data.loc[1, "high"] = 1
        with self.assertRaises(ValueError):
            run_backtest(data, BacktestConfig(rsi_period=2, ema_period=2))

    def test_csv_loader_rejects_missing_columns(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text("close,open\n1,1\n2,2\n3,3\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_ohlcv(path)


if __name__ == "__main__":
    unittest.main()
