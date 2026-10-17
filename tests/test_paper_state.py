import json
import tempfile
import unittest
from pathlib import Path

from paper_state import (
    cumulative_fill_delta,
    default_state,
    load_state,
    protective_levels,
    save_state,
)


class PaperStateTests(unittest.TestCase):
    def test_portfolio_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper-state.json"
            state = default_state(10_000)
            state["cash"] = 9_000
            state["positions"]["BTC/USD"] = {
                "amount": 0.01,
                "entry_price": 100_000,
                "stop_price": 98_000,
                "take_profit_price": 104_000,
            }
            save_state(path, state)
            restored = load_state(path)
            self.assertEqual(restored["cash"], 9_000)
            self.assertEqual(restored["positions"]["BTC/USD"]["amount"], 0.01)
            self.assertEqual(restored["positions"]["BTC/USD"]["stop_price"], 98_000)

    def test_corrupt_state_fails_closed_instead_of_resetting_balance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper-state.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "refusing to reset"):
                load_state(path)

    def test_partial_fill_cumulative_updates_only_apply_delta(self):
        previous = 0.0
        update_1 = {"filled": 0.25, "status": "open"}
        delta_1 = cumulative_fill_delta(previous, update_1)
        previous += delta_1
        update_2 = {"filled": 0.6, "status": "open"}
        delta_2 = cumulative_fill_delta(previous, update_2)
        previous += delta_2
        duplicate_update = {"filled": 0.6, "status": "open"}
        delta_3 = cumulative_fill_delta(previous, duplicate_update)
        self.assertAlmostEqual(delta_1, 0.25)
        self.assertAlmostEqual(delta_2, 0.35)
        self.assertEqual(delta_3, 0.0)
        with self.assertRaisesRegex(ValueError, "moved backwards"):
            cumulative_fill_delta(previous, {"filled": 0.4})

    def test_protective_levels_are_derived_from_fill_price(self):
        stop, target = protective_levels(100, 2, 4)
        self.assertAlmostEqual(stop, 98)
        self.assertAlmostEqual(target, 104)

    def test_invalid_protective_levels_rejected(self):
        with self.assertRaises(ValueError):
            protective_levels(0, 2, 4)


if __name__ == "__main__":
    unittest.main()
