import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import run_paper_trial


class PaperTrialRunnerTests(unittest.TestCase):
    def test_timestamped_trial_persists_and_reports_daily_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = 520
            x = np.arange(rows, dtype=float)
            close = 100.0 + x * 0.015 + 4.0 * np.sin(x / 5.0)
            open_price = np.concatenate(([close[0]], close[:-1]))
            high = np.maximum(open_price, close) + 0.8
            low = np.minimum(open_price, close) - 0.8
            frame = pd.DataFrame({
                "timestamp": pd.date_range("2025-01-01", periods=rows, freq="h", tz="UTC"),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.full(rows, 10.0),
            })
            csv_path = root / "ohlcv.csv"
            state_path = root / "state.json"
            report_path = root / "report.json"
            frame.to_csv(csv_path, index=False)
            argv = [
                "run_paper_trial.py", "--csv", str(csv_path), "--state", str(state_path),
                "--report", str(report_path), "--cash", "10000",
            ]
            with patch("sys.argv", argv):
                run_paper_trial.main()
            report = json.loads(report_path.read_text(encoding="utf-8"))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(report["candles_seen"], rows)
            self.assertEqual(report["daily_restarts"], 21)
            self.assertEqual(report["timestamp_gaps"], 0)
            self.assertEqual(report["exceptions"], [])
            self.assertTrue(report["journal_reconciled"])
            self.assertEqual(report["trade_journal_entries"], len(state["trade_journal"]))
            self.assertEqual(report["unique_trade_ids"], len(set(
                item["id"] for item in state["trade_journal"]
            )))
            self.assertAlmostEqual(report["ending_cash"], state["cash"])


if __name__ == "__main__":
    unittest.main()
