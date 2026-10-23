"""Regression tests for RSI calculations and signal safety."""

import unittest

import numpy as np
import pandas as pd

from strategy import compute_rsi, generate_signal


class RSIStrategyTests(unittest.TestCase):
    def test_flat_market_returns_neutral_rsi(self):
        values = pd.Series([100.0] * 40)
        rsi = compute_rsi(values, period=14).dropna()
        self.assertTrue((rsi == 50.0).all())

    def test_rising_market_returns_rsi_100(self):
        values = pd.Series(np.arange(1.0, 41.0))
        rsi = compute_rsi(values, period=14).dropna()
        self.assertTrue((rsi == 100.0).all())

    def test_falling_market_returns_rsi_zero(self):
        values = pd.Series(np.arange(40.0, 0.0, -1.0))
        rsi = compute_rsi(values, period=14).dropna()
        self.assertTrue((rsi == 0.0).all())

    def test_insufficient_history_holds(self):
        frame = pd.DataFrame({"close": [100.0 + i for i in range(10)]})
        signal, price, rsi = generate_signal(frame, rsi_period=14)
        self.assertEqual(signal, "HOLD")
        self.assertEqual(price, 109.0)
        self.assertEqual(rsi, 50.0)

    def test_empty_or_missing_close_data_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_signal(pd.DataFrame())
        with self.assertRaises(ValueError):
            generate_signal(pd.DataFrame({"open": [1, 2, 3]}))


if __name__ == "__main__":
    unittest.main()
