import unittest
from unittest.mock import patch

import bot as bot_module


class BotRestartRecoveryTests(unittest.TestCase):
    def test_existing_persisted_position_restores_strategy_exit_state(self):
        exchange = unittest.mock.Mock()
        exchange.get_position_amount.return_value = 0.25
        with patch.object(bot_module.config, "validate"), \
             patch.object(bot_module, "Exchange", return_value=exchange), \
             patch.object(bot_module.signal, "signal"):
            bot = bot_module.TradingBot()
        self.assertTrue(bot.strategy.in_position)

    def test_flat_persisted_portfolio_restores_flat_strategy_state(self):
        exchange = unittest.mock.Mock()
        exchange.get_position_amount.return_value = 0.0
        with patch.object(bot_module.config, "validate"), \
             patch.object(bot_module, "Exchange", return_value=exchange), \
             patch.object(bot_module.signal, "signal"):
            bot = bot_module.TradingBot()
        self.assertFalse(bot.strategy.in_position)


if __name__ == "__main__":
    unittest.main()
