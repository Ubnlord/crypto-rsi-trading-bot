"""ccxt exchange adapter with persistent paper balances and conservative live execution."""
from __future__ import annotations
import logging, time, uuid
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
        # CCXT requires sandbox mode to be selected before load_markets/other calls.
        if config.exchange_id == "bybit" and config.bybit_testnet:
            self.exchange.set_sandbox_mode(True)
            logger.warning("Bybit testnet enabled; orders are sent to the test environment")
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

    def fetch_order(self, order_id: str | None, symbol: str, params: dict | None = None) -> dict[str, Any]:
        return self.exchange.fetch_order(order_id, symbol, params or {})

    def reconcile_pending_orders(self) -> list[dict[str, Any]]:
        """Query exchange state for every persisted nonterminal order intent."""
        reconciled = []
        for intent in self.store.pending_order_intents():
            params = {}
            if self.config.exchange_id == "bybit":
                params["orderLinkId"] = intent["client_order_id"]
            try:
                order_id = intent.get("exchange_order_id")
                order = self.fetch_order(str(order_id) if order_id else None,
                                         intent["symbol"], params)
                status = str(order.get("status") or "unknown").lower()
                if status not in {"closed","canceled","cancelled","rejected","expired","open"}:
                    status = "unknown"
                if status == "closed" and float(order.get("filled") or 0) > 0:
                    amount = float(order.get("filled") or 0)
                    price = float(order.get("average") or order.get("price") or 0)
                    if price > 0:
                        self.store.record_trade(symbol=intent["symbol"], side=intent["side"],
                            amount=amount, price=price, mode="live", status="closed",
                            exchange_order_id=str(order.get("id") or intent.get("exchange_order_id") or "") or None,
                            fee=float((order.get("fee") or {}).get("cost") or 0),
                            metadata={"reconciled": True, "client_order_id": intent["client_order_id"]})
                elif float(order.get("filled") or 0) > 0:
                    status = "partially_filled"
                self.store.update_order_intent(intent["client_order_id"], status=status,
                    exchange_order_id=str(order.get("id") or "") or None, response=order)
                reconciled.append(order)
            except Exception as exc:
                self.store.update_order_intent(intent["client_order_id"], status="unknown",
                    last_error=str(exc))
                logger.warning("Order intent %s remains unresolved: %s",
                               intent["client_order_id"], exc)
        return reconciled

    def place_market_order(self, symbol: str, side: str, amount: float) -> dict[str, Any] | None:
        side = side.lower()
        if side not in ("buy", "sell") or amount <= 0:
            raise ValueError("A valid side and positive order amount are required")
        amount = self.amount_to_precision(symbol, amount)
        if amount <= 0:
            raise ValueError("Order amount rounds below exchange precision")
        if not self.config.is_live:
            return self._paper_fill(symbol, side, amount)
        # Stable client ID is stored before network I/O. A timeout is UNKNOWN, never
        # an invitation to submit a second order. Bybit calls this orderLinkId.
        client_id = "rsi-" + uuid.uuid4().hex[:24]
        self.store.create_order_intent(client_id, symbol, side, amount)
        params: dict[str, Any] = {}
        if config.exchange_id == "bybit":
            params["orderLinkId"] = client_id
        else:
            params["clientOrderId"] = client_id
        try:
            order = self.exchange.create_order(symbol, "market", side, amount, None, params)
            if not order or not order.get("id"):
                self.store.update_order_intent(client_id, status="unknown",
                    last_error="Exchange returned no order ID", response=order or {})
                raise RuntimeError("Exchange returned no order ID; reconcile before submitting another order")
            status = str(order.get("status") or "unknown").lower()
            if status not in {"closed", "canceled", "cancelled", "rejected", "expired", "open"}:
                status = "unknown"
            self.store.update_order_intent(client_id, status=status,
                exchange_order_id=str(order["id"]), response=order)
            logger.info("Submitted %s %s %s order=%s status=%s client_id=%s",
                        side, amount, symbol, order["id"], order.get("status"), client_id)
            order["clientOrderId"] = client_id
            return order
        except (ccxt.NetworkError, ccxt.RequestTimeout) as exc:
            self.store.update_order_intent(client_id, status="unknown", last_error=str(exc))
            logger.error("Order outcome uncertain; client ID=%s. Do not resubmit automatically.", client_id)
            raise RuntimeError(f"Order outcome uncertain (client ID {client_id}); reconcile before any new order") from exc
        except ccxt.BaseError as exc:
            self.store.update_order_intent(client_id, status="rejected", last_error=str(exc))
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
