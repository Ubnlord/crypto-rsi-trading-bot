import unittest
from risk_controls import MAX_RISK_PER_TRADE_PCT, crypto_amount_from_stop, forex_volume_from_stop, risk_budget

class RiskControlsTests(unittest.TestCase):
    def test_budget_is_capped_at_quarter_percent(self):
        self.assertEqual(risk_budget(10000), 25.0)
        with self.assertRaises(ValueError):
            risk_budget(10000, 0.5)

    def test_rejects_invalid_equity_and_prices(self):
        for equity in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                risk_budget(equity)
        with self.assertRaises(ValueError):
            crypto_amount_from_stop(10000, 100, 100)

    def test_crypto_size_respects_stop_risk_and_notional_cap(self):
        equity, entry, stop = 10000.0, 100.0, 98.0
        amount = crypto_amount_from_stop(equity, entry, stop)
        self.assertGreater(amount, 0)
        self.assertLessEqual(amount * (entry - stop) * 1.002, 25.0 + 1e-9)
        self.assertLessEqual(amount * entry, 1000.0 + 1e-9)

    def test_forex_volume_floors_to_step_and_budget(self):
        volume = forex_volume_from_stop(10000, 1000, min_volume=0.01, volume_step=0.01)
        self.assertEqual(volume, 0.02)
        self.assertLessEqual(volume * 1000, 25.0 + 1e-9)

    def test_forex_returns_zero_if_minimum_exceeds_budget(self):
        self.assertEqual(forex_volume_from_stop(100, 1000, min_volume=0.01, volume_step=0.01), 0.0)

    def test_invalid_risk_above_hard_cap_is_rejected(self):
        with self.assertRaises(ValueError):
            forex_volume_from_stop(10000, 100, risk_pct=MAX_RISK_PER_TRADE_PCT + 0.01)

if __name__ == "__main__":
    unittest.main()
