import unittest
from types import SimpleNamespace

from exchange import Exchange


class PaperProtectiveExitTests(unittest.TestCase):
    def make_exchange(self):
        exchange = Exchange.__new__(Exchange)
        exchange.config = SimpleNamespace(is_live=False)
        exchange.paper_state = {
            "positions": {
                "BTC/USDT": {
                    "amount": 0.1,
                    "entry_price": 100.0,
                    "stop_price": 95.0,
                    "take_profit_price": 110.0,
                }
            }
        }
        exchange._paper_fill = lambda symbol, side, amount, execution_price=None: {
            "status": "closed",
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": execution_price,
        }
        return exchange

    def test_intrabar_stop_is_detected_even_when_close_recovers(self):
        exchange = self.make_exchange()
        result = exchange.check_paper_protective_exit(
            "BTC/USDT", 101.0, candle_open=100.0, candle_high=103.0, candle_low=94.0
        )
        self.assertEqual(result["price"], 95.0)
        self.assertEqual(result["side"], "sell")

    def test_intrabar_target_is_detected_even_when_close_recedes(self):
        exchange = self.make_exchange()
        result = exchange.check_paper_protective_exit(
            "BTC/USDT", 101.0, candle_open=100.0, candle_high=111.0, candle_low=99.0
        )
        self.assertEqual(result["price"], 110.0)

    def test_stop_wins_when_both_barriers_touched_in_same_candle(self):
        exchange = self.make_exchange()
        result = exchange.check_paper_protective_exit(
            "BTC/USDT", 101.0, candle_open=100.0, candle_high=112.0, candle_low=94.0
        )
        self.assertEqual(result["price"], 95.0)

    def test_gap_below_stop_fills_at_open_not_stop(self):
        exchange = self.make_exchange()
        result = exchange.check_paper_protective_exit(
            "BTC/USDT", 90.0, candle_open=90.0, candle_high=92.0, candle_low=88.0
        )
        self.assertEqual(result["price"], 90.0)

    def test_no_exit_when_barrier_not_touched(self):
        exchange = self.make_exchange()
        result = exchange.check_paper_protective_exit(
            "BTC/USDT", 101.0, candle_open=100.0, candle_high=105.0, candle_low=98.0
        )
        self.assertIsNone(result)

    def test_invalid_ohlc_range_fails_closed(self):
        exchange = self.make_exchange()
        result = exchange.check_paper_protective_exit(
            "BTC/USDT", 101.0, candle_open=120.0, candle_high=110.0, candle_low=99.0
        )
        self.assertIsNone(result)

    def test_live_mode_never_uses_paper_protection(self):
        exchange = self.make_exchange()
        exchange.config.is_live = True
        result = exchange.check_paper_protective_exit(
            "BTC/USDT", 90.0, candle_open=90.0, candle_high=92.0, candle_low=88.0
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
