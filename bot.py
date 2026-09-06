"""
Main trading bot loop.
RSI Mean-Reversion on crypto via ccxt.
"""

from __future__ import annotations

import logging
import time
import signal
import sys
from datetime import datetime, timezone

from config import config
from exchange import Exchange
from strategy import RSIMeanReversion
from risk import calculate_position_size, should_allow_new_position

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bot")


class TradingBot:
    def __init__(self):
        config.validate()
        self.exchange = Exchange()
        self.strategy = RSIMeanReversion(
            rsi_period=config.rsi_period,
            oversold=config.rsi_oversold,
            overbought=config.rsi_overbought,
        )
        self.running = True
        self.symbol = config.symbol

        # Graceful shutdown
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, *args):
        logger.info("Shutdown signal received. Stopping bot...")
        self.running = False

    def run(self):
        logger.info("=" * 60)
        logger.info("Trading Bot starting")
        logger.info(f"Exchange : {config.exchange_id}")
        logger.info(f"Symbol   : {self.symbol}")
        logger.info(f"Timeframe: {config.timeframe}")
        logger.info(f"Mode     : {'LIVE' if config.is_live else 'PAPER'}")
        logger.info(f"Strategy : RSI({config.rsi_period}) mean-reversion "
                    f"[{config.rsi_oversold}/{config.rsi_overbought}]")
        logger.info("=" * 60)

        while self.running:
            try:
                self._tick()
            except Exception as e:
                logger.exception(f"Error in main loop: {e}")
            time.sleep(config.poll_interval_seconds)

        logger.info("Bot stopped.")

    def _tick(self):
        # 1. Fetch data
        df = self.exchange.fetch_ohlcv(
            self.symbol, config.timeframe, limit=config.candle_limit
        )
        if df.empty:
            logger.warning("No OHLCV data received")
            return

        # 2. Generate signal
        signal, price, rsi = self.strategy.evaluate(df)
        equity = self.exchange.get_balance("USDT")
        position = self.exchange.get_position_amount(self.symbol)

        logger.info(
            f"{self.symbol} | Price: {price:.2f} | RSI: {rsi:.1f} | "
            f"Signal: {signal} | Equity: {equity:.2f} | Pos: {position:.6f}"
        )

        # 3. Act on signal
        if signal == "BUY":
            self._handle_buy(price, equity, position)
        elif signal == "SELL":
            self._handle_sell(price, position)

    def _handle_buy(self, price: float, equity: float, current_position: float):
        if current_position > 0:
            logger.debug("Already in position, skipping BUY")
            return
        if not should_allow_new_position(1 if current_position > 0 else 0):
            logger.info("Max open positions reached")
            return

        amount = calculate_position_size(equity, price)
        amount = self.exchange.amount_to_precision(self.symbol, amount)
        if amount <= 0:
            logger.warning("Calculated size is zero")
            return

        order = self.exchange.place_market_order(self.symbol, "buy", amount)
        if order and order.get("status") in ("closed", "filled", None):
            self.strategy.on_filled("buy")
            logger.info(f"Entered long position: {amount} {self.symbol}")

    def _handle_sell(self, price: float, current_position: float):
        if current_position <= 0:
            logger.debug("No position to sell")
            return

        amount = self.exchange.amount_to_precision(self.symbol, current_position)
        order = self.exchange.place_market_order(self.symbol, "sell", amount)
        if order and order.get("status") in ("closed", "filled", None):
            self.strategy.on_filled("sell")
            logger.info(f"Closed position: {amount} {self.symbol}")


def main():
    bot = TradingBot()
    bot.run()


if __name__ == "__main__":
    main()
