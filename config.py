"""
Configuration loader. Sensitive values are read from environment variables.
Live trading remains opt-in; never use it before completing the documented release gates.
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

    mode: str = os.getenv("MODE", "paper").lower()
    symbol: str = os.getenv("SYMBOL", "BTC/USD")
    timeframe: str = os.getenv("TIMEFRAME", "15m")
    # EMA(200) needs at least 200 closes; use extra history for RSI/warmup.
    candle_limit: int = int(os.getenv("CANDLE_LIMIT", "300"))

    rsi_period: int = int(os.getenv("RSI_PERIOD", "14"))
    rsi_oversold: float = float(os.getenv("RSI_OVERSOLD", "30"))
    rsi_overbought: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
    ema_period: int = int(os.getenv("EMA_PERIOD", "200"))

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
        if self.rsi_period < 2 or self.ema_period < 2:
            raise ValueError("RSI_PERIOD and EMA_PERIOD must be at least 2")
        if not 0 < self.rsi_oversold < self.rsi_overbought < 100:
            raise ValueError("Require 0 < RSI_OVERSOLD < RSI_OVERBOUGHT < 100")
        if self.candle_limit < max(self.rsi_period + 2, self.ema_period):
            raise ValueError("CANDLE_LIMIT must cover RSI and EMA warmup periods")
        if self.is_live:
            print(
                "\n"
                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                "  WARNING: LIVE TRADING MODE ENABLED\n"
                "  Real money will be used. You can lose everything.\n"
                "  Live trading is not verified by this project branch.\n"
                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
            )


config = Config()
