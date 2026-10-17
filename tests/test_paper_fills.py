import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from exchange import Exchange
from paper_state import default_state


class PaperFillAccountingTests(unittest.TestCase):
    def make_exchange(self, cash=1_000.0, fee_pct=0.1, slippage_pct=0.05):
        exchange = Exchange.__new__(Exchange)
        exchange.config = SimpleNamespace(stop_loss_pct=2.0, take_profit_pct=4.0, is_live=False)
        exchange.paper_fee_pct = fee_pct
        exchange.paper_slippage_pct = slippage_pct
        exchange.paper_state_path = Path(tempfile.gettempdir()) / "unused-paper-state-test.json"
        exchange.paper_state = default_state(cash)
        exchange.paper_balance = cash
        exchange.paper_positions = {}
        exchange.paper_entry_price = {}
        exchange._persist_paper_state = lambda: None
        exchange.exchange = SimpleNamespace(fetch_ticker=lambda symbol: {"last": 100.0})
        return exchange

    def test_buy_applies_adverse_slippage_and_fee_to_cash(self):
        exchange = self.make_exchange()
        order = exchange._paper_fill("BTC/USD", "buy", 1.0)
        expected_price = 100.0 * 1.0005
        expected_fee = expected_price * 0.001
        self.assertAlmostEqual(order["price"], expected_price)
        self.assertAlmostEqual(order["fee"], expected_fee)
        self.assertAlmostEqual(exchange.paper_balance, 1_000.0 - expected_price - expected_fee)
        self.assertAlmostEqual(exchange.paper_positions["BTC/USD"], 1.0)

    def test_sell_applies_adverse_slippage_and_fee_to_proceeds(self):
        exchange = self.make_exchange(cash=0.0)
        exchange.paper_positions["BTC/USD"] = 1.0
        exchange.paper_entry_price["BTC/USD"] = 100.0
        exchange.paper_state["positions"]["BTC/USD"] = {
            "amount": 1.0, "entry_price": 100.0,
            "stop_price": 98.0, "take_profit_price": 104.0,
        }
        order = exchange._paper_fill("BTC/USD", "sell", 1.0, execution_price=110.0)
        expected_price = 110.0 * 0.9995
        expected_fee = expected_price * 0.001
        self.assertAlmostEqual(order["price"], expected_price)
        self.assertAlmostEqual(order["fee"], expected_fee)
        self.assertAlmostEqual(exchange.paper_balance, expected_price - expected_fee)
        self.assertNotIn("BTC/USD", exchange.paper_positions)

    def test_sell_request_larger_than_position_cannot_create_extra_proceeds(self):
        exchange = self.make_exchange(cash=0.0)
        exchange.paper_positions["BTC/USD"] = 0.25
        exchange.paper_entry_price["BTC/USD"] = 100.0
        exchange.paper_state["positions"]["BTC/USD"] = {
            "amount": 0.25, "entry_price": 100.0,
            "stop_price": 98.0, "take_profit_price": 104.0,
        }
        order = exchange._paper_fill("BTC/USD", "sell", 99.0, execution_price=110.0)
        expected_price = 110.0 * 0.9995
        expected_gross = 0.25 * expected_price
        expected_fee = expected_gross * 0.001
        self.assertAlmostEqual(order["amount"], 0.25)
        self.assertAlmostEqual(exchange.paper_balance, expected_gross - expected_fee)

    def test_insufficient_cash_including_fee_rejects_buy(self):
        exchange = self.make_exchange(cash=100.0, fee_pct=1.0, slippage_pct=1.0)
        order = exchange._paper_fill("BTC/USD", "buy", 1.0)
        self.assertEqual(order["status"], "rejected")
        self.assertEqual(exchange.paper_balance, 100.0)
        self.assertEqual(exchange.paper_positions, {})

    def test_invalid_side_and_amount_rejected(self):
        exchange = self.make_exchange()
        self.assertEqual(exchange._paper_fill("BTC/USD", "hold", 1.0)["status"], "rejected")
        self.assertEqual(exchange._paper_fill("BTC/USD", "buy", 0.0)["status"], "rejected")
        self.assertEqual(exchange.paper_balance, 1_000.0)


if __name__ == "__main__":
    unittest.main()
