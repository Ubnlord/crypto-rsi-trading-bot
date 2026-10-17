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
        self.symbol = config.symbol
        # Rebuild strategy position state from the durable paper portfolio on
        # restart so an existing position can still receive RSI exit signals.
        self.strategy.in_position = self.exchange.get_position_amount(self.symbol) > 0
        self.running = True
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
        logger.info(f"Mode     : {'LIVE' if config.is_live else ('BYBIT DEMO DATA + PAPER FILLS' if config.mode == 'demo' else 'PAPER')}")
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

        # Evaluate barriers against the completed candle's full range. OHLC
        # cannot reveal intrabar ordering, so the paper simulator assumes stop
        # first when both stop and target are touched within the same candle.
        last_candle = df.iloc[-1]
        protective_exit = self.exchange.check_paper_protective_exit(
            self.symbol,
            price,
            candle_open=float(last_candle["open"]),
            candle_high=float(last_candle["high"]),
            candle_low=float(last_candle["low"]),
        )
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
        if order and order.get("status") in ("closed", "filled"):
            filled_amount = float(order.get("filled") or order.get("amount") or amount)
            average_price = float(order.get("average") or order.get("price") or price)
            if filled_amount <= 0:
                logger.error("Buy order reported filled status without a positive filled amount")
                return
            if config.is_live:
                try:
                    protection = self.exchange.place_protective_oco(
                        self.symbol, filled_amount, average_price
                    )
                    logger.info("Verified exchange-native OCO protection: %s", protection["orders"])
                except Exception:
                    # Fail closed. Live mode is disabled in this branch; if the
                    # release gate is ever changed, do not continue unprotected.
                    logger.exception("CRITICAL: protective OCO could not be verified; stopping bot")
                    self.running = False
                    return
            self.strategy.on_filled("buy")
            logger.info("Entered long position: %s %s", filled_amount, self.symbol)
        elif order and float(order.get("filled") or 0) > 0:
            # Do not pretend a partially filled order is fully reconciled.
            # A future live release must reconcile/cancel the remainder and
            # protect the confirmed filled quantity before trading can continue.
            logger.critical(
                "Order %s has partial fill %.8g with status %s; live release is blocked pending reconciliation",
                order.get("id"), float(order.get("filled") or 0), order.get("status")
            )
            self.running = False

    def _handle_sell(self, price: float, current_position: float):
        if current_position <= 0:
            logger.debug("No position to sell")
            return
        amount = self.exchange.amount_to_precision(self.symbol, current_position)
        order = self.exchange.place_market_order(self.symbol, "sell", amount)
        if order and order.get("status") in ("closed", "filled"):
            filled_amount = float(order.get("filled") or order.get("amount") or amount)
            if filled_amount <= 0:
                logger.error("Sell order reported filled status without a positive filled amount")
                return
            if filled_amount + 1e-12 < current_position:
                logger.critical(
                    "Sell order only filled %.8g of %.8g; position reconciliation required. Stopping bot.",
                    filled_amount, current_position
                )
                self.running = False
                return
            self.strategy.on_filled("sell")
            logger.info("Closed position: %s %s", filled_amount, self.symbol)
        elif order and float(order.get("filled") or 0) > 0:
            logger.critical(
                "Sell order %s has partial fill %.8g with status %s; stopping pending reconciliation",
                order.get("id"), float(order.get("filled") or 0), order.get("status")
            )
            self.running = False


def main():
    TradingBot().run()


if __name__ == "__main__":
    main()
