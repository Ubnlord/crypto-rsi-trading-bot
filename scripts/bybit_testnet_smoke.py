"""Opt-in authenticated Bybit testnet smoke test.

This is deliberately separate from the bot's paper-mode unit tests. It submits one
small, real testnet limit order with exchange-native TP/SL fields, verifies the
exchange-reported order state and attached protection, then cancels any still-open
entry. It never targets mainnet. Configure BYBIT_TESTNET=true and testnet-only keys.
"""
from __future__ import annotations

import os
import sys
import time
import uuid

import ccxt


def main() -> int:
    if os.getenv("BYBIT_TESTNET", "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise SystemExit("REFUSED: set BYBIT_TESTNET=true; this test never runs against mainnet.")
    key = os.getenv("API_KEY", "").strip()
    secret = os.getenv("API_SECRET", "").strip()
    if not key or not secret:
        raise SystemExit("Set API_KEY and API_SECRET to Bybit TESTNET-only credentials locally.")
    symbol = os.getenv("BYBIT_TEST_SYMBOL", "BTC/USDT").strip()
    amount_raw = os.getenv("BYBIT_TEST_AMOUNT", "").strip()
    if not amount_raw:
        raise SystemExit("Set BYBIT_TEST_AMOUNT to a deliberately tiny valid base-asset amount.")

    exchange = ccxt.bybit({
        "apiKey": key,
        "secret": secret,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    exchange.set_sandbox_mode(True)
    exchange.load_markets()
    market = exchange.market(symbol)
    if not market.get("spot"):
        raise SystemExit(f"REFUSED: {symbol} is not a spot market.")
    amount = float(exchange.amount_to_precision(symbol, float(amount_raw)))
    if amount <= 0:
        raise SystemExit("BYBIT_TEST_AMOUNT rounds to zero at market precision.")

    ticker = exchange.fetch_ticker(symbol)
    last = float(ticker.get("last") or 0)
    if last <= 0:
        raise SystemExit("Could not obtain a valid testnet last price.")
    # A far-below-market limit buy is designed to remain open so we can inspect
    # and cancel it; the API still may execute if the market moves sharply.
    entry = float(exchange.price_to_precision(symbol, last * 0.50))
    take_profit = float(exchange.price_to_precision(symbol, last * 1.08))
    stop_loss = float(exchange.price_to_precision(symbol, last * 0.95))
    client_id = "rsi-test-" + uuid.uuid4().hex[:20]
    order = None
    try:
        order = exchange.create_order(
            symbol, "limit", "buy", amount, entry,
            {
                "orderLinkId": client_id,
                "takeProfit": str(take_profit),
                "stopLoss": str(stop_loss),
                "tpOrderType": "Market",
                "slOrderType": "Market",
            },
        )
        order_id = order.get("id")
        if not order_id:
            raise RuntimeError(f"Create response did not include order ID: {order!r}")
        time.sleep(1.0)
        observed = exchange.fetch_order(str(order_id), symbol)
        info = observed.get("info") or {}
        # CCXT's normalized response may not expose TP/SL uniformly; inspect both
        # normalized fields and raw Bybit response fields.
        tp = observed.get("takeProfit") or info.get("takeProfit")
        sl = observed.get("stopLoss") or info.get("stopLoss")
        print({
            "testnet": True,
            "symbol": symbol,
            "client_order_id": client_id,
            "exchange_order_id": order_id,
            "status": observed.get("status"),
            "filled": observed.get("filled"),
            "exchange_take_profit": tp,
            "exchange_stop_loss": sl,
        })
        if not tp or not sl:
            raise RuntimeError(
                "Exchange order state did not confirm both TP and SL. "
                "Protection is NOT verified; inspect Bybit testnet order history."
            )
        print("PASS: Bybit testnet order state reported both TP and SL fields.")
    finally:
        if order and order.get("id"):
            try:
                current = exchange.fetch_order(str(order["id"]), symbol)
                if current.get("status") in {"open", "new"}:
                    exchange.cancel_order(str(order["id"]), symbol)
                    print("Entry order cancellation requested; verify final state in testnet order history.")
            except Exception as exc:
                print(f"WARNING: unable to confirm/cancel test entry; manually inspect testnet order {order.get('id')}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
