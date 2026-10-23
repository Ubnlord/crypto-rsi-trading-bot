"""
Main trading bot loop.
RSI Mean-Reversion on crypto via ccxt.
"""

from __future__ import annotations

import logging
import signal
import time

from config import config
from exchange import Exchange
from strategy import RSIMeanReversion
from risk import calculate_position_size, should_allow_new_position

logging.basicConfig(
    level=getattr(logging, config.log_level, logging.INFO),
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
        self.quote_currency = self.symbol.split("/")[-1].split(":")[0]

        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, *args):
        logger.info("Shutdown signal received. Stopping bot...")
        self.running = False

    def run(self):
        logger.info("=" * 60)
        logger.info("Trading Bot starting")
        logger.info("Exchange : %s", config.exchange_id)
        logger.info("Symbol   : %s", self.symbol)
        logger.info("Timeframe: %s", config.timeframe)
        logger.info("Mode     : %s", "LIVE" if config.is_live else "PAPER")
        logger.info(
            "Strategy : RSI(%s) mean-reversion [%s/%s]",
            config.rsi_period,
            config.rsi_oversold,
            config.rsi_overbought,
        )
        logger.info("=" * 60)

        while self.running:
            try:
                self._tick()
            except Exception:
                logger.exception("Error in main loop")
            if self.running:
                time.sleep(config.poll_interval_seconds)
        logger.info("Bot stopped.")

    def _tick(self):
        df = self.exchange.fetch_ohlcv(
            self.symbol, config.timeframe, limit=config.candle_limit
        )
        if df.empty:
            logger.warning("No OHLCV data received")
            return

        # Reconcile strategy state with exchange/paper holdings on every tick.
        # This lets a restarted process manage an existing position.
        position = self.exchange.get_position_amount(self.symbol)
        self.strategy.in_position = position > 0
        equity = self.exchange.get_balance(self.quote_currency)

        signal_name, price, rsi = self.strategy.evaluate(df)
        logger.info(
            "%s | Price: %.8f | RSI: %.1f | Signal: %s | %s balance: %.2f | Pos: %.8f",
            self.symbol,
            price,
            rsi,
            signal_name,
            self.quote_currency,
            equity,
            position,
        )

        if signal_name == "BUY":
            self._handle_buy(price, equity, position)
        elif signal_name == "SELL":
            self._handle_sell(position)

    def _handle_buy(self, price: float, equity: float, current_position: float):
        if current_position > 0:
            logger.debug("Already in position, skipping BUY")
            return
        if not should_allow_new_position(0):
            logger.info("Max open positions reached")
            return

        amount = calculate_position_size(equity, price)
        amount = self.exchange.amount_to_precision(self.symbol, amount)
        if amount <= 0:
            logger.warning("Calculated size is zero")
            return

        order = self.exchange.place_market_order(self.symbol, "buy", amount)
        if order and order.get("status") in ("closed", "filled"):
            self.strategy.on_filled("buy")
            logger.info("Entered long position: %s %s", amount, self.symbol)
        elif order:
            logger.warning(
                "Buy order was submitted but is not confirmed filled (status=%s); "
                "position will be reconciled on the next tick.",
                order.get("status"),
            )

    def _handle_sell(self, current_position: float):
        if current_position <= 0:
            logger.debug("No position to sell")
            return

        amount = self.exchange.amount_to_precision(self.symbol, current_position)
        order = self.exchange.place_market_order(self.symbol, "sell", amount)
        if order and order.get("status") in ("closed", "filled"):
            self.strategy.on_filled("sell")
            logger.info("Closed position: %s %s", amount, self.symbol)
        elif order:
            logger.warning(
                "Sell order was submitted but is not confirmed filled (status=%s); "
                "position will be reconciled on the next tick.",
                order.get("status"),
            )


def main():
    bot = TradingBot()
    bot.run()


if __name__ == "__main__":
    main()
