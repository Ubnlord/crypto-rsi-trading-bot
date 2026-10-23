"""Smoke tests for persistent storage and the backtesting engine."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from trading_store import TradingStore
from backtest import run_backtest


class StoreTests(unittest.TestCase):
    def test_trade_persists_across_store_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "bot.sqlite3")
            first = TradingStore(path)
            trade_id = first.record_trade(symbol="BTC/USD", side="buy", amount=0.01,
                                          price=50000, mode="paper", status="closed")
            second = TradingStore(path)
            trades = second.recent_trades()
            self.assertEqual(trades[0]["id"], trade_id)
            self.assertEqual(trades[0]["symbol"], "BTC/USD")

    def test_order_intent_is_persisted_before_network_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "bot.sqlite3")
            first = TradingStore(path)
            first.create_order_intent("rsi-test-123", "BTC/USDT", "buy", 0.01)
            second = TradingStore(path)
            pending = second.pending_order_intents()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["client_order_id"], "rsi-test-123")
            second.update_order_intent("rsi-test-123", status="unknown",
                                       last_error="simulated timeout")
            self.assertEqual(second.pending_order_intents()[0]["status"], "unknown")

    def test_invalid_trade_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TradingStore(str(Path(directory) / "bot.sqlite3"))
            with self.assertRaises(ValueError):
                store.record_trade(symbol="BTC/USD", side="buy", amount=0, price=100,
                                   mode="paper", status="closed")


class BacktestTests(unittest.TestCase):
    def test_backtest_reports_costs_and_drawdown(self):
        # Oscillating prices provide a deterministic, finite series for the engine.
        prices = [100, 102, 104, 101, 98, 95, 97, 100, 104, 108, 105, 101,
                  97, 94, 98, 103, 107, 110, 106, 101, 96, 92, 97, 103, 109] * 4
        result = run_backtest(pd.DataFrame({"close": prices}), rsi_period=5,
                              oversold=35, overbought=65, fee_rate=0.001,
                              slippage_rate=0.0005)
        self.assertIn("final_equity", result)
        self.assertIn("max_drawdown_pct", result)
        self.assertGreaterEqual(result["fees_paid"], 0)
        self.assertGreaterEqual(result["max_drawdown_pct"], -100)

    def test_bad_input_is_rejected(self):
        with self.assertRaises(ValueError):
            run_backtest(pd.DataFrame({"close": [1, 2]}))


if __name__ == "__main__":
    unittest.main()
