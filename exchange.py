"""
Exchange connector using ccxt.
Supports paper mode (simulated fills) and live mode (real orders).
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Dict, Any

import ccxt
import pandas as pd

from config import config

logger = logging.getLogger(__name__)


class Exchange:
    def __init__(self):
        self.config = config
        exchange_class = getattr(ccxt, config.exchange_id)
        params: Dict[str, Any] = {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},  # change to "future" if needed
        }
        if config.api_key and config.api_secret:
            params["apiKey"] = config.api_key
            params["secret"] = config.api_secret
            if config.api_passphrase:
                params["password"] = config.api_passphrase

        self.exchange: ccxt.Exchange = exchange_class(params)
        self.paper_balance = 10_000.0  # starting USDT for paper mode
        self.paper_positions: Dict[str, float] = {}  # symbol -> amount
        self.paper_entry_price: Dict[str, float] = {}

        if not config.is_live:
            logger.info("Running in PAPER mode (no real orders will be sent)")
        else:
            logger.warning("LIVE mode active — real orders will be placed")

        # Load markets once
        try:
            self.exchange.load_markets()
        except Exception as e:
            logger.error(f"Failed to load markets: {e}")
            raise

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def get_balance(self, currency: str = "USDT") -> float:
        if not self.config.is_live:
            return self.paper_balance
        balance = self.exchange.fetch_balance()
        return float(balance.get("free", {}).get(currency, 0.0))

    def get_position_amount(self, symbol: str) -> float:
        if not self.config.is_live:
            return self.paper_positions.get(symbol, 0.0)
        # For spot we approximate by free base currency
        base = symbol.split("/")[0]
        balance = self.exchange.fetch_balance()
        return float(balance.get("free", {}).get(base, 0.0))

    def place_market_order(
        self, symbol: str, side: str, amount: float
    ) -> Optional[Dict[str, Any]]:
        side = side.lower()
        if amount <= 0:
            logger.warning("Order amount <= 0, skipping")
            return None

        if not self.config.is_live:
            return self._paper_fill(symbol, side, amount)

        try:
            order = self.exchange.create_order(
                symbol=symbol,
                type="market",
                side=side,
                amount=amount,
            )
            logger.info(f"LIVE order placed: {side.upper()} {amount} {symbol} → {order.get('id')}")
            return order
        except Exception as e:
            logger.error(f"Order failed: {e}")
            return None

    def _paper_fill(self, symbol: str, side: str, amount: float) -> Dict[str, Any]:
        ticker = self.exchange.fetch_ticker(symbol)
        price = float(ticker["last"])
        cost = amount * price

        if side == "buy":
            if cost > self.paper_balance:
                logger.warning("Paper: insufficient balance")
                return {"status": "rejected", "reason": "insufficient balance"}
            self.paper_balance -= cost
            self.paper_positions[symbol] = self.paper_positions.get(symbol, 0.0) + amount
            self.paper_entry_price[symbol] = price
            logger.info(
                f"[PAPER] BUY {amount:.6f} {symbol} @ {price:.2f} | "
                f"Balance left: {self.paper_balance:.2f}"
            )
        else:  # sell
            held = self.paper_positions.get(symbol, 0.0)
            if amount > held:
                amount = held
            if amount <= 0:
                return {"status": "rejected", "reason": "no position"}
            proceeds = amount * price
            self.paper_balance += proceeds
            self.paper_positions[symbol] = held - amount
            entry = self.paper_entry_price.get(symbol, price)
            pnl = (price - entry) * amount
            logger.info(
                f"[PAPER] SELL {amount:.6f} {symbol} @ {price:.2f} | "
                f"PnL: {pnl:+.2f} | Balance: {self.paper_balance:.2f}"
            )
            if self.paper_positions[symbol] <= 0:
                self.paper_positions.pop(symbol, None)
                self.paper_entry_price.pop(symbol, None)

        return {
            "id": f"paper-{int(time.time())}",
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "status": "closed",
            "mode": "paper",
        }

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        try:
            return float(self.exchange.amount_to_precision(symbol, amount))
        except Exception:
            return round(amount, 6)

    def price_to_precision(self, symbol: str, price: float) -> float:
        try:
            return float(self.exchange.price_to_precision(symbol, price))
        except Exception:
            return round(price, 2)
