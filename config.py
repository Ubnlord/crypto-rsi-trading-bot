"""
Configuration loader. All sensitive values come from environment variables.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    exchange_id: str = os.getenv("EXCHANGE_ID", "kraken")
    api_key: str = os.getenv("API_KEY", "")
    api_secret: str = os.getenv("API_SECRET", "")
    api_passphrase: str = os.getenv("API_PASSPHRASE", "")

    mode: str = os.getenv("MODE", "paper").lower()  # "paper" or "live"
    symbol: str = os.getenv("SYMBOL", "BTC/USD")
    timeframe: str = os.getenv("TIMEFRAME", "15m")
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
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    @property
    def is_live(self) -> bool:
        return self.mode == "live" and bool(self.api_key) and bool(self.api_secret)

    def validate(self) -> None:
        if self.mode not in ("paper", "live"):
            raise ValueError("MODE must be 'paper' or 'live'")
        if self.is_live:
            print(
                "\n"
                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                "  WARNING: LIVE TRADING MODE ENABLED\n"
                "  Real money will be used. You can lose everything.\n"
                "  Double-check keys, symbol, risk settings, and strategy.\n"
                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
            )


config = Config()
