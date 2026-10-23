"""Tests for fail-closed live protection and order-state classification."""
import unittest
from unittest.mock import patch
from order_safety import ProtectionUnavailable, require_exchange_protection, order_is_filled

class OrderSafetyTests(unittest.TestCase):
    def test_live_mode_fails_closed_without_native_oco(self):
        with patch("order_safety.config.mode", "live"):
            with self.assertRaises(ProtectionUnavailable):
                require_exchange_protection("kraken")

    def test_paper_mode_does_not_require_native_oco(self):
        with patch("order_safety.config.mode", "paper"):
            require_exchange_protection("kraken")

    def test_partial_fill_is_not_treated_as_fully_filled(self):
        self.assertFalse(order_is_filled({"status":"open","amount":10,"filled":4}))
        self.assertFalse(order_is_filled({"status":"closed","amount":10,"filled":4}))
        self.assertTrue(order_is_filled({"status":"closed","amount":10,"filled":10}))

if __name__ == "__main__":
    unittest.main()
