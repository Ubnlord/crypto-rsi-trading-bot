"""Small SQLite persistence layer for bot events and portfolio snapshots.

The module is deliberately independent from exchange execution so callers can
record only confirmed fills and reconciled balances.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TradingStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("DATABASE_PATH", "data/trading_bot.sqlite3")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    amount REAL NOT NULL,
                    price REAL NOT NULL,
                    fee REAL NOT NULL DEFAULT 0,
                    pnl REAL,
                    mode TEXT NOT NULL,
                    exchange_order_id TEXT,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    quote_currency TEXT NOT NULL,
                    cash_balance REAL NOT NULL,
                    position_amount REAL NOT NULL,
                    mark_price REAL NOT NULL,
                    equity REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bot_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    level TEXT NOT NULL,
                    event TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}'
                );
            """)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def record_trade(self, *, symbol: str, side: str, amount: float, price: float,
                     mode: str, status: str, fee: float = 0, pnl: float | None = None,
                     exchange_order_id: str | None = None,
                     metadata: dict[str, Any] | None = None) -> int:
        if side.lower() not in ("buy", "sell") or amount <= 0 or price <= 0:
            raise ValueError("Trade side, amount, and price must be valid")
        with self._connect() as db:
            cursor = db.execute("""
                INSERT INTO trades(created_at,symbol,side,amount,price,fee,pnl,mode,
                                    exchange_order_id,status,metadata_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (self._now(), symbol, side.lower(), amount, price, fee, pnl, mode,
                  exchange_order_id, status, json.dumps(metadata or {})))
            return int(cursor.lastrowid)

    def record_snapshot(self, *, mode: str, quote_currency: str, cash_balance: float,
                        position_amount: float, mark_price: float, equity: float):
        with self._connect() as db:
            db.execute("""INSERT INTO portfolio_snapshots
                (created_at,mode,quote_currency,cash_balance,position_amount,mark_price,equity)
                VALUES(?,?,?,?,?,?,?)""",
                (self._now(), mode, quote_currency, cash_balance, position_amount,
                 mark_price, equity))

    def record_event(self, event: str, *, level: str = "INFO",
                     details: dict[str, Any] | None = None):
        with self._connect() as db:
            db.execute("INSERT INTO bot_events(created_at,level,event,details_json) VALUES(?,?,?,?)",
                       (self._now(), level.upper(), event, json.dumps(details or {})))

    def recent_trades(self, limit: int = 100):
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def recent_snapshots(self, limit: int = 500):
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be between 1 and 5000")
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM portfolio_snapshots ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
