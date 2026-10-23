"""
Configuration loader. Sensitive values are read only from environment variables.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    exchange_id: str = os.getenv("EXCHANGE_ID", "kraken").strip().lower()
    api_key: str = os.getenv("API_KEY", "").strip()
    api_secret: str = os.getenv("API_SECRET", "").strip()
    api_passphrase: str = os.getenv("API_PASSPHRASE", "").strip()

    mode: str = os.getenv("MODE", "paper").strip().lower()
    symbol: str = os.getenv("SYMBOL", "BTC/USD").strip()
    timeframe: str = os.getenv("TIMEFRAME", "15m").strip()
    candle_limit: int = int(os.getenv("CANDLE_LIMIT", "100"))

    rsi_period: int = int(os.getenv("RSI_PERIOD", "14"))
    rsi_oversold: float = float(os.getenv("RSI_OVERSOLD", "30"))
    rsi_overbought: float = float(os.getenv("RSI_OVERBOUGHT", "70"))

    risk_per_trade_pct: float = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))
    max_position_pct: float = float(os.getenv("MAX_POSITION_PCT", "10.0"))
    stop_loss_pct: float = float(os.getenv("STOP_LOSS_PCT", "2.0"))
    take_profit_pct: float = float(os.getenv("TAKE_PROFIT_PCT", "4.0"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "1"))

    poll_interval_seconds: int = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO").strip().upper()

    @property
    def is_live(self) -> bool:
        """True only when live mode is explicitly selected; validation enforces credentials."""
        return self.mode == "live"

    def validate(self) -> None:
        if self.mode not in ("paper", "live"):
            raise ValueError("MODE must be 'paper' or 'live'")
        if self.mode == "live" and (not self.api_key or not self.api_secret):
            raise ValueError(
                "MODE=live requires API_KEY and API_SECRET. "
                "Refusing to silently run in paper mode."
            )
        if not self.exchange_id or not self.symbol or "/" not in self.symbol:
            raise ValueError("EXCHANGE_ID and a ccxt SYMBOL such as BTC/USD are required")
        if self.candle_limit < self.rsi_period + 2:
            raise ValueError("CANDLE_LIMIT must be at least RSI_PERIOD + 2")
        if self.rsi_period < 2:
            raise ValueError("RSI_PERIOD must be >= 2")
        if not (0 < self.rsi_oversold < self.rsi_overbought < 100):
            raise ValueError("RSI thresholds must satisfy 0 < OVERSOLD < OVERBOUGHT < 100")
        if not (0 < self.risk_per_trade_pct <= 100):
            raise ValueError("RISK_PER_TRADE_PCT must be in (0, 100]")
        if not (0 < self.max_position_pct <= 100):
            raise ValueError("MAX_POSITION_PCT must be in (0, 100]")
        if self.stop_loss_pct <= 0 or self.take_profit_pct <= 0:
            raise ValueError("STOP_LOSS_PCT and TAKE_PROFIT_PCT must be positive")
        if self.max_open_positions < 1:
            raise ValueError("MAX_OPEN_POSITIONS must be >= 1")
        if self.poll_interval_seconds < 1:
            raise ValueError("POLL_INTERVAL_SECONDS must be >= 1")

        if self.is_live:
            print(
                "\n"
                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\\n"
                "  WARNING: LIVE TRADING MODE ENABLED\\n"
                "  Real money will be used. You can lose everything.\\n"
                "  Use trade-only API keys; disable withdrawals and restrict IPs.\\n"
                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\\n"
            )


config = Config()
