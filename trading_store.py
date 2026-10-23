"""SQLite persistence for trades, snapshots, events and paper portfolio state."""
from __future__ import annotations
import json, os, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

class TradingStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("DATABASE_PATH", "data/trading_bot.sqlite3")
        if self.path != ":memory:": Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self):
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS trades(
              id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
              symbol TEXT NOT NULL, side TEXT NOT NULL, amount REAL NOT NULL,
              price REAL NOT NULL, fee REAL NOT NULL DEFAULT 0, pnl REAL,
              mode TEXT NOT NULL, exchange_order_id TEXT, status TEXT NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}');
            CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_order_side
              ON trades(exchange_order_id,side) WHERE exchange_order_id IS NOT NULL;
            CREATE TABLE IF NOT EXISTS portfolio_snapshots(
              id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
              mode TEXT NOT NULL, quote_currency TEXT NOT NULL, cash_balance REAL NOT NULL,
              position_amount REAL NOT NULL, mark_price REAL NOT NULL, equity REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS bot_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
              level TEXT NOT NULL, event TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS paper_state(
              symbol TEXT PRIMARY KEY, cash_balance REAL NOT NULL, position_amount REAL NOT NULL,
              entry_price REAL NOT NULL, updated_at TEXT NOT NULL);
            """)

    @staticmethod
    def _now(): return datetime.now(timezone.utc).isoformat()

    def save_paper_state(self, symbol, cash_balance, position_amount, entry_price):
        with self._connect() as db:
            db.execute("""INSERT INTO paper_state VALUES(?,?,?,?,?)
              ON CONFLICT(symbol) DO UPDATE SET cash_balance=excluded.cash_balance,
              position_amount=excluded.position_amount,entry_price=excluded.entry_price,
              updated_at=excluded.updated_at""",
              (symbol, cash_balance, position_amount, entry_price, self._now()))

    def load_paper_state(self, symbol):
        with self._connect() as db:
            row = db.execute("SELECT * FROM paper_state WHERE symbol=?", (symbol,)).fetchone()
            return dict(row) if row else None

    def record_trade(self, *, symbol: str, side: str, amount: float, price: float,
                     mode: str, status: str, fee: float = 0, pnl: float | None = None,
                     exchange_order_id: str | None = None, metadata: dict[str, Any] | None = None):
        if side.lower() not in ("buy","sell") or amount <= 0 or price <= 0:
            raise ValueError("Trade side, amount, and price must be valid")
        with self._connect() as db:
            try:
                cur = db.execute("""INSERT INTO trades(created_at,symbol,side,amount,price,fee,pnl,
                  mode,exchange_order_id,status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                  (self._now(),symbol,side.lower(),amount,price,fee,pnl,mode,exchange_order_id,status,
                   json.dumps(metadata or {})))
                return int(cur.lastrowid)
            except sqlite3.IntegrityError:
                return None

    def record_snapshot(self, *, mode, quote_currency, cash_balance, position_amount, mark_price, equity):
        with self._connect() as db:
            db.execute("""INSERT INTO portfolio_snapshots(created_at,mode,quote_currency,cash_balance,
              position_amount,mark_price,equity) VALUES(?,?,?,?,?,?,?)""",
              (self._now(),mode,quote_currency,cash_balance,position_amount,mark_price,equity))

    def record_event(self, event, *, level="INFO", details=None):
        with self._connect() as db:
            db.execute("INSERT INTO bot_events(created_at,level,event,details_json) VALUES(?,?,?,?)",
              (self._now(),level.upper(),event,json.dumps(details or {})))

    def recent_trades(self, limit=100):
        with self._connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?",(max(1,min(1000,int(limit))),))]
    def recent_snapshots(self, limit=500):
        with self._connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM portfolio_snapshots ORDER BY id DESC LIMIT ?",(max(1,min(5000,int(limit))),))]
    def recent_events(self, limit=100):
        with self._connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM bot_events ORDER BY id DESC LIMIT ?",(max(1,min(1000,int(limit))),))]
