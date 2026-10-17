import unittest
from config import Config, LIVE_EXECUTION_ENABLED, MAX_RISK_PER_TRADE_PCT
from risk import calculate_position_size

class DemoSafetyTests(unittest.TestCase):
    def test_live_gate_is_hard_disabled(self):
        self.assertFalse(LIVE_EXECUTION_ENABLED)
        cfg = Config(mode="live", exchange_id="bybit", api_key="x", api_secret="y")
        with self.assertRaisesRegex(ValueError, "Live execution is disabled"):
            cfg.validate()

    def test_demo_only_accepts_bybit_and_quarter_percent_risk(self):
        Config(mode="demo", exchange_id="bybit", risk_per_trade_pct=0.25).validate()
        with self.assertRaisesRegex(ValueError, "supports Bybit"):
            Config(mode="demo", exchange_id="kraken").validate()
        with self.assertRaisesRegex(ValueError, "at most 0.25"):
            Config(mode="paper", exchange_id="bybit", risk_per_trade_pct=0.5).validate()
        self.assertEqual(MAX_RISK_PER_TRADE_PCT, 0.25)

    def test_existing_crypto_sizer_rejects_higher_risk(self):
        with self.assertRaisesRegex(ValueError, "at most 0.25"):
            calculate_position_size(10000, 100, risk_pct=1.0)

if __name__ == "__main__":
    unittest.main()
