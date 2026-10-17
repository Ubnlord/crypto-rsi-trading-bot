"""
Exchange connector using ccxt.
Supports paper mode (simulated fills) and live mode (real orders).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any

import ccxt
import pandas as pd

from config import config
from paper_state import load_state, save_state, protective_levels
from protective_orders import place_and_verify_oco

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
        self.paper_state_path = Path(os.getenv("PAPER_STATE_PATH", "data/paper-state.json"))
        self.paper_fee_pct = float(os.getenv("PAPER_FEE_PCT", "0.1"))
        self.paper_slippage_pct = float(os.getenv("PAPER_SLIPPAGE_PCT", "0.05"))
        if not (0 <= self.paper_fee_pct < 100 and 0 <= self.paper_slippage_pct < 100):
            raise ValueError("PAPER_FEE_PCT and PAPER_SLIPPAGE_PCT must be between 0 and 100")
        self.paper_state = load_state(self.paper_state_path, initial_cash=10_000.0)
        self.paper_balance = float(self.paper_state["cash"])
        self.paper_positions: Dict[str, float] = {
            symbol: float(position["amount"])
            for symbol, position in self.paper_state["positions"].items()
        }
        self.paper_entry_price: Dict[str, float] = {
            symbol: float(position["entry_price"])
            for symbol, position in self.paper_state["positions"].items()
        }

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

    def place_protective_oco(
        self, symbol: str, amount: float, entry_price: float
    ) -> Dict[str, Any]:
        """Place and verify native exchange OCO protection; never emulate it."""
        if not self.config.is_live:
            raise RuntimeError("Native exchange orders are unavailable in paper mode")
        stop_price, target_price = protective_levels(
            entry_price, self.config.stop_loss_pct, self.config.take_profit_pct
        )
        stop_price = self.price_to_precision(symbol, stop_price)
        target_price = self.price_to_precision(symbol, target_price)
        return place_and_verify_oco(
            self.exchange, symbol, amount, stop_price, target_price
        )

    def _paper_fill(
        self, symbol: str, side: str, amount: float, execution_price: Optional[float] = None
    ) -> Dict[str, Any]:
        if execution_price is None:
            ticker = self.exchange.fetch_ticker(symbol)
            price = float(ticker["last"])
        else:
            price = float(execution_price)
        if not (price > 0 and amount > 0):
            return {"status": "rejected", "reason": "invalid paper execution price or amount"}
        side = side.lower()
        if side not in ("buy", "sell"):
            return {"status": "rejected", "reason": "unsupported paper order side"}
        # Apply adverse slippage before computing fees and cash movements.
        slippage = self.paper_slippage_pct / 100
        execution_price = price * (1 + slippage) if side == "buy" else price * (1 - slippage)
        gross = amount * execution_price
        fee = gross * self.paper_fee_pct / 100

        if side == "buy":
            total_cost = gross + fee
            if total_cost > self.paper_balance:
                logger.warning("Paper: insufficient balance")
                return {"status": "rejected", "reason": "insufficient balance"}
            old_amount = self.paper_positions.get(symbol, 0.0)
            old_entry = self.paper_entry_price.get(symbol, execution_price)
            new_amount = old_amount + amount
            average_entry = ((old_amount * old_entry) + (amount * execution_price)) / new_amount
            self.paper_balance -= total_cost
            self.paper_positions[symbol] = new_amount
            self.paper_entry_price[symbol] = average_entry
            stop_price, target_price = protective_levels(
                average_entry, self.config.stop_loss_pct, self.config.take_profit_pct
            )
            self.paper_state["positions"][symbol] = {
                "amount": new_amount,
                "entry_price": average_entry,
                "stop_price": stop_price,
                "take_profit_price": target_price,
            }
            self._persist_paper_state()
            logger.info(
                f"[PAPER] BUY {amount:.6f} {symbol} @ {execution_price:.8g} "
                f"(fee {fee:.4f}, slippage {self.paper_slippage_pct:.3g}%) | "
                f"Balance left: {self.paper_balance:.2f}"
            )
        else:  # sell
            held = self.paper_positions.get(symbol, 0.0)
            if amount > held:
                amount = held
            if amount <= 0:
                return {"status": "rejected", "reason": "no position"}
            proceeds = gross - fee
            self.paper_balance += proceeds
            self.paper_positions[symbol] = held - amount
            entry = self.paper_entry_price.get(symbol, execution_price)
            pnl = (execution_price - entry) * amount - fee
            logger.info(
                f"[PAPER] SELL {amount:.6f} {symbol} @ {execution_price:.8g} "
                f"(fee {fee:.4f}, slippage {self.paper_slippage_pct:.3g}%) | "
                f"PnL: {pnl:+.2f} | Balance: {self.paper_balance:.2f}"
            )
            if self.paper_positions[symbol] <= 1e-12:
                self.paper_positions.pop(symbol, None)
                self.paper_entry_price.pop(symbol, None)
                self.paper_state["positions"].pop(symbol, None)
            else:
                remaining = self.paper_positions[symbol]
                self.paper_state["positions"][symbol]["amount"] = remaining
            self._persist_paper_state()

        return {
            "id": f"paper-{int(time.time())}",
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": execution_price,
            "fee": fee,
            "status": "closed",
            "mode": "paper",
        }

    def _persist_paper_state(self) -> None:
        self.paper_state["cash"] = float(self.paper_balance)
        save_state(self.paper_state_path, self.paper_state)

    def check_paper_protective_exit(
        self,
        symbol: str,
        mark_price: float,
        *,
        candle_open: Optional[float] = None,
        candle_high: Optional[float] = None,
        candle_low: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Simulate protective exits using completed-candle OHLC, not just its close.

        If both stop and target are touched within one candle and the open is
        between them, assume the stop was hit first (conservative, since OHLC
        does not reveal intrabar ordering). Gaps fill at the candle open.
        This is paper simulation only, never exchange-side protection.
        """
        if self.config.is_live:
            return None
        position = self.paper_state["positions"].get(symbol)
        if not position or not mark_price > 0:
            return None
        stop = float(position["stop_price"])
        target = float(position["take_profit_price"])
        open_price = float(candle_open) if candle_open is not None else mark_price
        high = float(candle_high) if candle_high is not None else mark_price
        low = float(candle_low) if candle_low is not None else mark_price
        if min(open_price, high, low, mark_price) <= 0 or low > high:
            logger.error("[PAPER] Invalid OHLC values; refusing protective exit evaluation")
            return None

        # Stop takes precedence when both barriers are crossed in the same bar.
        if open_price <= stop:
            logger.warning("[PAPER] Stop gapped through; simulated fill at candle open %.8g", open_price)
            return self._paper_fill(symbol, "sell", float(position["amount"]), open_price)
        if open_price >= target:
            logger.info("[PAPER] Target gapped through; simulated fill at candle open %.8g", open_price)
            return self._paper_fill(symbol, "sell", float(position["amount"]), open_price)
        if low <= stop:
            logger.warning("[PAPER] Protective stop touched; simulated fill at %.8g", stop)
            return self._paper_fill(symbol, "sell", float(position["amount"]), stop)
        if high >= target:
            logger.info("[PAPER] Take-profit touched; simulated fill at %.8g", target)
            return self._paper_fill(symbol, "sell", float(position["amount"]), target)
        return None

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
