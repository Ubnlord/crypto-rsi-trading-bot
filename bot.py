"""
Main trading bot loop.
Paper mode remains the default. Live execution has not been verified.
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
            ema_period=config.ema_period,
        )
        self.running = True
        self.symbol = config.symbol
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
        logger.info(
            f"Strategy : RSI({config.rsi_period}) recovery + EMA({config.ema_period}) "
            f"trend filter [{config.rsi_oversold}/{config.rsi_overbought}]"
        )
        logger.info("=" * 60)

        while self.running:
            try:
                self._tick()
            except Exception as exc:
                logger.exception("Error in main loop: %s", exc)
            time.sleep(config.poll_interval_seconds)
        logger.info("Bot stopped.")

    def _tick(self):
        df = self.exchange.fetch_ohlcv(
            self.symbol, config.timeframe, limit=config.candle_limit
        )
        if df.empty or len(df) < 2:
            logger.warning("Insufficient OHLCV data received")
            return

        # CCXT commonly includes the still-forming candle as the last row.
        # Exclude it so strategy decisions use completed candles only.
        df = df.iloc[:-1].copy()
        if len(df) < max(config.rsi_period + 2, config.ema_period):
            logger.warning("Waiting for enough completed candles to warm up indicators")
            return

        signal, price, rsi = self.strategy.evaluate(df)
        quote_currency = self.symbol.split("/")[1].split(":")[0]
        equity = self.exchange.get_balance(quote_currency)
        position = self.exchange.get_position_amount(self.symbol)
        logger.info(
            f"{self.symbol} | Price: {price:.8g} | RSI: {rsi:.1f} | "
            f"Signal: {signal} | Equity: {equity:.2f} {quote_currency} | Pos: {position:.8g}"
        )

        # Paper-mode protection is evaluated on every completed-candle close,
        # not only when the strategy emits an RSI exit.
        protective_exit = self.exchange.check_paper_protective_exit(self.symbol, price)
        if protective_exit and protective_exit.get("status") == "closed":
            self.strategy.on_filled("sell")
            logger.info("Paper protective exit completed for %s", self.symbol)
            return

        if signal == "BUY":
            self._handle_buy(price, equity, position)
        elif signal == "SELL":
            self._handle_sell(price, position)

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
        if order and order.get("status") in ("closed", "filled", None):
            self.strategy.on_filled("buy")
            logger.info("Entered long position: %s %s", amount, self.symbol)

    def _handle_sell(self, price: float, current_position: float):
        if current_position <= 0:
            logger.debug("No position to sell")
            return
        amount = self.exchange.amount_to_precision(self.symbol, current_position)
        order = self.exchange.place_market_order(self.symbol, "sell", amount)
        if order and order.get("status") in ("closed", "filled", None):
            self.strategy.on_filled("sell")
            logger.info("Closed position: %s %s", amount, self.symbol)


def main():
    TradingBot().run()


if __name__ == "__main__":
    main()
