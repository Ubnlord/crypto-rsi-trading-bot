"""ccxt exchange adapter with persistent paper balances and conservative live execution."""
from __future__ import annotations
import logging, time
from typing import Any
import ccxt
import pandas as pd
from config import config
from trading_store import TradingStore

logger = logging.getLogger(__name__)

class Exchange:
    def __init__(self):
        self.config = config
        exchange_class = getattr(ccxt, config.exchange_id, None)
        if exchange_class is None:
            raise ValueError(f"Unsupported ccxt exchange: {config.exchange_id}")
        params: dict[str, Any] = {"enableRateLimit": True, "options": {"defaultType": "spot"}}
        if config.api_key and config.api_secret:
            params.update(apiKey=config.api_key, secret=config.api_secret)
            if config.api_passphrase:
                params["password"] = config.api_passphrase
        self.exchange = exchange_class(params)
        self.store = TradingStore()
        self.paper_balance = 10_000.0
        self.paper_positions: dict[str, float] = {}
        self.paper_entry_price: dict[str, float] = {}
        if not config.is_live:
            saved = self.store.load_paper_state(config.symbol)
            if saved:
                self.paper_balance = float(saved["cash_balance"])
                if float(saved["position_amount"]) > 0:
                    self.paper_positions[config.symbol] = float(saved["position_amount"])
                    self.paper_entry_price[config.symbol] = float(saved["entry_price"])
        self.exchange.load_markets()
        if config.is_live:
            logger.warning("LIVE mode active; use only restricted trade-only API keys")
        else:
            logger.info("Paper mode active")

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        rows = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(rows, columns=["timestamp","open","high","low","close","volume"])
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df.set_index("timestamp")

    def get_balance(self, currency: str = "USDT") -> float:
        if not self.config.is_live:
            return self.paper_balance
        return float(self.exchange.fetch_balance().get("free", {}).get(currency, 0) or 0)

    def get_position_amount(self, symbol: str) -> float:
        if not self.config.is_live:
            return float(self.paper_positions.get(symbol, 0))
        base = self.exchange.market(symbol)["base"]
        return float(self.exchange.fetch_balance().get("free", {}).get(base, 0) or 0)

    def get_entry_price(self, symbol: str) -> float | None:
        if not self.config.is_live:
            return self.paper_entry_price.get(symbol)
        # Live entries are tracked from the bot's confirmed trade ledger.
        trades = self.store.recent_trades(1000)
        for trade in trades:
            if trade.get("symbol") == symbol and trade.get("side") == "buy" and trade.get("status") == "closed":
                return float(trade["price"])
        return None

    def fetch_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        return self.exchange.fetch_order(order_id, symbol)

    def place_market_order(self, symbol: str, side: str, amount: float) -> dict[str, Any] | None:
        side = side.lower()
        if side not in ("buy", "sell") or amount <= 0:
            raise ValueError("A valid side and positive order amount are required")
        amount = self.amount_to_precision(symbol, amount)
        if amount <= 0:
            raise ValueError("Order amount rounds below exchange precision")
        if not self.config.is_live:
            return self._paper_fill(symbol, side, amount)
        # Do not blindly retry a timed-out order: the exchange may have accepted it.
        try:
            order = self.exchange.create_order(symbol, "market", side, amount)
            if not order or not order.get("id"):
                raise RuntimeError("Exchange returned no order ID; reconcile before submitting another order")
            logger.info("Submitted %s %s %s order=%s status=%s", side, amount, symbol,
                        order["id"], order.get("status"))
            return order
        except (ccxt.NetworkError, ccxt.RequestTimeout) as exc:
            logger.error("Order outcome uncertain (%s). Do not resubmit automatically; reconcile open/recent orders.", exc)
            raise RuntimeError("Order outcome uncertain; manual/exchange reconciliation required") from exc
        except ccxt.BaseError:
            logger.exception("Exchange rejected/failed order")
            raise

    def _paper_fill(self, symbol: str, side: str, amount: float) -> dict[str, Any]:
        price = float(self.exchange.fetch_ticker(symbol)["last"])
        if not price or price <= 0:
            raise RuntimeError("Exchange returned invalid ticker price")
        if side == "buy":
            cost = amount * price
            if cost > self.paper_balance:
                return {"status":"rejected","symbol":symbol,"side":side,"reason":"insufficient balance"}
            old_amount = self.paper_positions.get(symbol, 0.0)
            old_entry = self.paper_entry_price.get(symbol, price)
            total = old_amount + amount
            self.paper_entry_price[symbol] = ((old_amount * old_entry + amount * price) / total) if total else price
            self.paper_positions[symbol] = total
            self.paper_balance -= cost
        else:
            held = self.paper_positions.get(symbol, 0.0)
            amount = min(amount, held)
            if amount <= 0:
                return {"status":"rejected","symbol":symbol,"side":side,"reason":"no position"}
            self.paper_balance += amount * price
            remaining = held - amount
            if remaining <= 1e-12:
                self.paper_positions.pop(symbol, None)
                self.paper_entry_price.pop(symbol, None)
            else:
                self.paper_positions[symbol] = remaining
        self.store.save_paper_state(symbol, self.paper_balance,
            self.paper_positions.get(symbol, 0.0), self.paper_entry_price.get(symbol, 0.0))
        return {"id":f"paper-{time.time_ns()}","symbol":symbol,"side":side,"amount":amount,
                "filled":amount,"average":price,"price":price,"status":"closed","mode":"paper"}

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        return float(self.exchange.amount_to_precision(symbol, amount))

    def price_to_precision(self, symbol: str, price: float) -> float:
        return float(self.exchange.price_to_precision(symbol, price))
