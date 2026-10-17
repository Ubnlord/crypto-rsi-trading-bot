"""Read-only MetaTrader 5 connector for a verified demo account.

This module intentionally exposes no order_send or order-modification method.
The Python package requires a supported local MT5 terminal, usually Windows;
GitHub Codespaces/Linux is not a supported MT5 execution host.
"""
from __future__ import annotations
import os
from typing import Any

class MT5DemoError(RuntimeError):
    pass

class MT5ReadOnly:
    def __init__(self, terminal_path: str | None = None):
        self.terminal_path = terminal_path or os.getenv("MT5_TERMINAL_PATH") or None
        self.mt5: Any = None

    def connect(self) -> dict[str, Any]:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise MT5DemoError(
                "MetaTrader5 package is unavailable. Use a supported Windows host "
                "with the MT5 terminal installed; Codespaces/Linux cannot provide "
                "a normal local MT5 terminal connection."
            ) from exc
        self.mt5 = mt5
        ok = mt5.initialize(path=self.terminal_path) if self.terminal_path else mt5.initialize()
        if not ok:
            self.mt5 = None
            raise MT5DemoError(f"MT5 initialize failed: {mt5.last_error()}")
        account = mt5.account_info()
        if account is None:
            mt5.shutdown()
            self.mt5 = None
            raise MT5DemoError(f"MT5 account_info failed: {mt5.last_error()}")
        server = str(getattr(account, "server", "")).lower()
        if getattr(account, "trade_mode", None) != 0 or "demo" not in server:
            mt5.shutdown()
            self.mt5 = None
            raise MT5DemoError(
                "Refusing MT5 connection: account must report demo trade_mode=0 "
                "and a server name containing 'demo'. No orders were sent."
            )
        return {"connected": True, "mode": "demo-read-only", "server": str(account.server),
                "currency": str(account.currency), "balance": float(account.balance),
                "equity": float(account.equity)}

    def fetch_rates(self, symbol: str, timeframe_name: str = "M15", count: int = 300):
        if self.mt5 is None:
            raise MT5DemoError("Call connect() and verify the demo account first")
        if not symbol or count < 2:
            raise ValueError("A symbol and at least two bars are required")
        timeframe = getattr(self.mt5, f"TIMEFRAME_{timeframe_name}", None)
        if timeframe is None:
            raise ValueError(f"Unsupported MT5 timeframe: {timeframe_name}")
        if not self.mt5.symbol_select(symbol, True):
            raise MT5DemoError(f"Could not select MT5 symbol {symbol}")
        rates = self.mt5.copy_rates_from_pos(symbol, timeframe, 1, count)
        if rates is None or len(rates) == 0:
            raise MT5DemoError(f"No completed MT5 bars returned: {self.mt5.last_error()}")
        return rates

    def close(self) -> None:
        if self.mt5 is not None:
            self.mt5.shutdown()
            self.mt5 = None
