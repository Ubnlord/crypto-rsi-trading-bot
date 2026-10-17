import unittest

from config import Config, LIVE_EXECUTION_ENABLED


class LiveExecutionGateTests(unittest.TestCase):
    def test_live_execution_is_disabled_in_this_build(self):
        candidate = Config(mode="live", api_key="placeholder", api_secret="placeholder")
        self.assertFalse(LIVE_EXECUTION_ENABLED)
        self.assertFalse(candidate.is_live)
        with self.assertRaisesRegex(ValueError, "Live execution is disabled"):
            candidate.validate()


if __name__ == "__main__":
    unittest.main()
