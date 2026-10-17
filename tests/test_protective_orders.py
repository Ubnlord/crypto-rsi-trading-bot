import unittest

from protective_orders import ProtectionUnavailable, place_and_verify_oco


class MockExchange:
    def __init__(self, status="open"):
        self.status = status
        self.created = None

    def create_oco_order(self, **kwargs):
        self.created = kwargs
        return {"order_ids": ["stop-1", "target-1"]}

    def fetch_order(self, order_id, symbol):
        return {"id": order_id, "symbol": symbol, "status": self.status}


class ProtectiveOrderTests(unittest.TestCase):
    def test_native_oco_orders_must_both_be_verifiable(self):
        exchange = MockExchange()
        result = place_and_verify_oco(exchange, "BTC/USD", 0.01, 98000, 104000)
        self.assertTrue(result["verified"])
        self.assertEqual(len(result["orders"]), 2)
        self.assertEqual(exchange.created["side"], "sell")

    def test_refuses_exchange_without_native_oco(self):
        with self.assertRaisesRegex(ProtectionUnavailable, "no verified native OCO"):
            place_and_verify_oco(object(), "BTC/USD", 0.01, 98, 104)

    def test_refuses_rejected_protective_order(self):
        with self.assertRaisesRegex(ProtectionUnavailable, "not active"):
            place_and_verify_oco(MockExchange(status="rejected"), "BTC/USD", 0.01, 98, 104)

    def test_rejects_invalid_price_levels(self):
        with self.assertRaises(ValueError):
            place_and_verify_oco(MockExchange(), "BTC/USD", 0.01, 104, 98)


if __name__ == "__main__":
    unittest.main()
