import unittest

from service.order_state import (
    InvalidOrderTransition, OrderStatus, may_submit_again, transition,
)


class OrderStateTests(unittest.TestCase):
    def test_normal_lifecycle(self):
        self.assertEqual(transition("pending", "submitting"), OrderStatus.SUBMITTING)
        self.assertEqual(transition("submitting", "accepted"), OrderStatus.ACCEPTED)
        self.assertEqual(transition("accepted", "partially_filled"), OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(transition("partially_filled", "filled"), OrderStatus.FILLED)

    def test_unknown_submission_requires_reconciliation(self):
        self.assertEqual(transition("submitting", "unknown"), OrderStatus.UNKNOWN)
        self.assertFalse(may_submit_again("unknown"))
        self.assertFalse(may_submit_again("submitting"))
        self.assertTrue(may_submit_again("pending"))

    def test_terminal_states_cannot_be_reopened(self):
        for status in ("filled", "cancelled", "rejected", "failed"):
            with self.subTest(status=status):
                with self.assertRaises(InvalidOrderTransition):
                    transition(status, "submitting")

    def test_unknown_cannot_be_marked_failed_without_provider_evidence(self):
        with self.assertRaises(InvalidOrderTransition):
            transition("unknown", "failed")

    def test_unknown_values_fail_closed(self):
        with self.assertRaises(InvalidOrderTransition):
            transition("unexpected", "filled")
        self.assertFalse(may_submit_again("unexpected"))


if __name__ == "__main__":
    unittest.main()
