import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from exchange import Exchange
from paper_state import append_trade_record, default_state, load_state, validate_state


class DurablePaperJournalTests(unittest.TestCase):
    def make_exchange(self, path):
        exchange = Exchange.__new__(Exchange)
        exchange.config = SimpleNamespace(stop_loss_pct=2.0, take_profit_pct=4.0, is_live=False)
        exchange.paper_fee_pct = 0.1
        exchange.paper_slippage_pct = 0.05
        exchange.paper_state_path = Path(path)
        exchange.paper_state = default_state(1_000.0)
        exchange.paper_balance = 1_000.0
        exchange.paper_positions = {}
        exchange.paper_entry_price = {}
        exchange.exchange = SimpleNamespace(fetch_ticker=lambda symbol: {"last": 100.0})
        return exchange

    def test_fill_and_journal_survive_restart_as_one_atomic_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper-state.json"
            first = self.make_exchange(path)
            order = first._paper_fill("BTC/USD", "buy", 1.0)
            self.assertEqual(order["status"], "closed")
            self.assertEqual(len(first.paper_state["trade_journal"]), 1)
            self.assertEqual(first.paper_state["trade_journal"][0]["id"], order["id"])
            self.assertIn(order["id"], first.paper_state["processed_order_ids"])

            # Recreate the in-memory exchange cache exactly as startup does.
            restored = load_state(path)
            second_cash = float(restored["cash"])
            second_positions = {
                symbol: float(position["amount"])
                for symbol, position in restored["positions"].items()
            }
            self.assertAlmostEqual(second_cash, first.paper_balance)
            self.assertEqual(second_positions, first.paper_positions)
            self.assertEqual(len(restored["trade_journal"]), 1)
            self.assertEqual(restored["trade_journal"][0]["id"], order["id"])
            self.assertAlmostEqual(
                restored["trade_journal"][0]["cash_after"], restored["cash"]
            )

    def test_duplicate_fill_event_is_idempotent(self):
        state = default_state(100.0)
        record = {
            "id": "paper-test-1",
            "timestamp": "2026-10-17T00:00:00+00:00",
            "symbol": "BTC/USD",
            "side": "buy",
            "amount": 0.1,
            "price": 100.0,
            "fee": 0.01,
            "cash_after": 89.99,
        }
        self.assertTrue(append_trade_record(state, record))
        self.assertFalse(append_trade_record(state, record))
        self.assertEqual(len(state["trade_journal"]), 1)
        self.assertEqual(state["processed_order_ids"], ["paper-test-1"])

    def test_invalid_or_duplicate_journal_ids_fail_closed(self):
        state = default_state()
        record = {
            "id": "paper-test-1",
            "timestamp": "2026-10-17T00:00:00+00:00",
            "symbol": "BTC/USD",
            "side": "buy",
            "amount": 0.1,
            "price": 100.0,
            "fee": 0.01,
            "cash_after": 89.99,
        }
        append_trade_record(state, record)
        state["trade_journal"].append(dict(record))
        with self.assertRaisesRegex(RuntimeError, "duplicate or invalid trade journal ID"):
            validate_state(state)


    def test_repeated_fill_restart_cycles_keep_journal_and_balances_reconciled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper-state.json"
            exchange = self.make_exchange(path)
            for cycle in range(40):
                buy = exchange._paper_fill("BTC/USD", "buy", 0.01, execution_price=100.0)
                self.assertEqual(buy["status"], "closed")
                # Simulate process restart after every buy by reconstructing from disk.
                restored = load_state(path)
                exchange = self.make_exchange(path)
                exchange.paper_state = restored
                exchange.paper_balance = float(restored["cash"])
                exchange.paper_positions = {
                    symbol: float(position["amount"])
                    for symbol, position in restored["positions"].items()
                }
                exchange.paper_entry_price = {
                    symbol: float(position["entry_price"])
                    for symbol, position in restored["positions"].items()
                }
                sell = exchange._paper_fill("BTC/USD", "sell", 0.01, execution_price=101.0)
                self.assertEqual(sell["status"], "closed")
                restored = load_state(path)
                self.assertEqual(restored["positions"], {})
                self.assertEqual(len(restored["trade_journal"]), (cycle + 1) * 2)
                self.assertEqual(len(restored["processed_order_ids"]), (cycle + 1) * 2)
                self.assertAlmostEqual(
                    restored["cash"], restored["trade_journal"][-1]["cash_after"]
                )
                # Recreate the process after each completed round trip as well.
                exchange = self.make_exchange(path)
                exchange.paper_state = restored
                exchange.paper_balance = float(restored["cash"])
                exchange.paper_positions = {}
                exchange.paper_entry_price = {}
            final = load_state(path)
            ids = [record["id"] for record in final["trade_journal"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(len(ids), 80)
            self.assertEqual(final["positions"], {})

    def test_legacy_state_without_journal_keeps_existing_cash(self):
        state = default_state(500.0)
        del state["trade_journal"]
        validate_state(state)
        self.assertEqual(state["cash"], 500.0)
        self.assertEqual(state["trade_journal"], [])


if __name__ == "__main__":
    unittest.main()
