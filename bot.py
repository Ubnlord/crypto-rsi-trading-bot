"""Main RSI bot loop with persistent history and conservative order handling."""
from __future__ import annotations
import logging, signal, time
from config import config
from exchange import Exchange
from strategy import RSIMeanReversion
from risk import calculate_position_size
from trading_store import TradingStore
from order_safety import require_exchange_protection, order_is_filled

logging.basicConfig(level=getattr(logging, config.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
logger = logging.getLogger("bot")

class TradingBot:
    def __init__(self):
        config.validate()
        require_exchange_protection(config.exchange_id)
        self.exchange = Exchange()
        self.strategy = RSIMeanReversion(rsi_period=config.rsi_period,
            oversold=config.rsi_oversold, overbought=config.rsi_overbought)
        self.store = TradingStore()
        self.running = True
        self.symbol = config.symbol
        self.quote_currency = self.symbol.split("/")[-1].split(":")[0]
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, *_):
        self.running = False
        logger.info("Shutdown requested")

    def run(self):
        logger.info("Starting RSI bot mode=%s exchange=%s symbol=%s", config.mode, config.exchange_id, self.symbol)
        while self.running:
            try:
                self._tick()
            except Exception as exc:
                logger.exception("Tick failed; no blind order retry: %s", exc)
                self.store.record_event("Tick failed", level="ERROR", details={"error": str(exc)})
            if self.running:
                time.sleep(config.poll_interval_seconds)
        logger.info("Bot stopped")

    def _tick(self):
        df = self.exchange.fetch_ohlcv(self.symbol, config.timeframe, config.candle_limit)
        if df.empty or len(df) < config.rsi_period + 2:
            self.store.record_event("Insufficient market data", level="WARNING")
            return
        closed = df.iloc[:-1]
        if closed.empty:
            return
        position = self.exchange.get_position_amount(self.symbol)
        cash = self.exchange.get_balance(self.quote_currency)
        self.strategy.in_position = position > 0
        signal_name, price, rsi = self.strategy.evaluate(closed)
        entry_price = self.exchange.get_entry_price(self.symbol) if position > 0 else None
        if position > 0 and entry_price and entry_price > 0:
            if price <= entry_price * (1 - config.stop_loss_pct / 100):
                signal_name = "SELL"
                self.store.record_event("Bot-side stop-loss threshold reached", level="WARNING",
                    details={"price": price, "entry_price": entry_price})
            elif price >= entry_price * (1 + config.take_profit_pct / 100):
                signal_name = "SELL"
                self.store.record_event("Bot-side take-profit threshold reached",
                    details={"price": price, "entry_price": entry_price})
        self.store.record_snapshot(mode=config.mode, quote_currency=self.quote_currency,
            cash_balance=cash, position_amount=position, mark_price=price, equity=cash + position * price)
        self.store.record_event("Market tick", details={"symbol":self.symbol,"price":price,"rsi":rsi,"signal":signal_name})
        logger.info("%s price=%.8f RSI=%.2f signal=%s cash=%.2f position=%.8f", self.symbol, price, rsi, signal_name, cash, position)
        if signal_name == "BUY" and position <= 0:
            self._buy(price, cash)
        elif signal_name == "SELL" and position > 0:
            self._sell(position)

    def _buy(self, price, cash):
        amount = self.exchange.amount_to_precision(self.symbol, calculate_position_size(cash, price))
        if amount <= 0:
            self.store.record_event("Buy skipped: size rounds to zero", level="WARNING")
            return
        order = self.exchange.place_market_order(self.symbol, "buy", amount)
        if order.get("status") == "rejected":
            self.store.record_event("Buy rejected", level="WARNING", details=order)
            return
        if not order_is_filled(order):
            self._reconcile_order(order)
            return
        fill_price = float(order.get("average") or order.get("price") or price)
        filled = float(order.get("filled") or amount)
        self.store.record_trade(symbol=self.symbol, side="buy", amount=filled, price=fill_price,
            mode=config.mode, status="closed", exchange_order_id=order.get("id"),
            fee=float((order.get("fee") or {}).get("cost") or 0))
        logger.info("Confirmed buy fill amount=%s price=%s", filled, fill_price)

    def _sell(self, position):
        amount = self.exchange.amount_to_precision(self.symbol, position)
        if amount <= 0:
            return
        order = self.exchange.place_market_order(self.symbol, "sell", amount)
        if order.get("status") == "rejected":
            self.store.record_event("Sell rejected", level="ERROR", details=order)
            return
        if not order_is_filled(order):
            self._reconcile_order(order)
            return
        price = float(order.get("average") or order.get("price") or 0)
        filled = float(order.get("filled") or amount)
        if price > 0:
            self.store.record_trade(symbol=self.symbol, side="sell", amount=filled, price=price,
                mode=config.mode, status="closed", exchange_order_id=order.get("id"),
                fee=float((order.get("fee") or {}).get("cost") or 0))
        logger.info("Confirmed sell fill amount=%s price=%s", filled, price)

    def _reconcile_order(self, order):
        order_id = order.get("id")
        if not order_id:
            self.store.record_event("Order has no ID; manual reconciliation required", level="CRITICAL", details={"order":order})
            return
        try:
            current = self.exchange.fetch_order(str(order_id), self.symbol)
            self.store.record_event("Order reconciled", details={"order_id":order_id,"status":current.get("status"),"filled":current.get("filled"),"remaining":current.get("remaining")})
            if str(current.get("status","")).lower() not in {"closed","canceled","cancelled","rejected","expired"}:
                logger.warning("Order %s remains nonterminal; no duplicate order submitted", order_id)
        except Exception as exc:
            self.store.record_event("Order reconciliation failed; manual check required", level="CRITICAL", details={"order_id":order_id,"error":str(exc)})
            logger.exception("Could not reconcile order %s", order_id)

def main():
    TradingBot().run()

if __name__ == "__main__":
    main()
