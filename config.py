"""
Configuration loader. Sensitive values are read from environment variables.
Live trading is hard-disabled in this build.
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

# Hard release gate: never change this as part of the demo integration stage.
LIVE_EXECUTION_ENABLED = False
MAX_RISK_PER_TRADE_PCT = 0.25

@dataclass
class Config:
    exchange_id: str = os.getenv("EXCHANGE_ID", "bybit").lower()
    api_key: str = os.getenv("API_KEY", "")
    api_secret: str = os.getenv("API_SECRET", "")
    api_passphrase: str = os.getenv("API_PASSPHRASE", "")
    mode: str = os.getenv("MODE", "demo").lower()
    symbol: str = os.getenv("SYMBOL", "BTC/USDT")
    timeframe: str = os.getenv("TIMEFRAME", "15m")
    candle_limit: int = int(os.getenv("CANDLE_LIMIT", "300"))
    rsi_period: int = int(os.getenv("RSI_PERIOD", "14"))
    rsi_oversold: float = float(os.getenv("RSI_OVERSOLD", "30"))
    rsi_overbought: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
    ema_period: int = int(os.getenv("EMA_PERIOD", "200"))
    risk_per_trade_pct: float = float(os.getenv("RISK_PER_TRADE_PCT", "0.25"))
    max_position_pct: float = float(os.getenv("MAX_POSITION_PCT", "10.0"))
    stop_loss_pct: float = float(os.getenv("STOP_LOSS_PCT", "2.0"))
    take_profit_pct: float = float(os.getenv("TAKE_PROFIT_PCT", "4.0"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "1"))
    poll_interval_seconds: int = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    @property
    def is_live(self) -> bool:
        # Intentionally impossible while the module-level release gate is False.
        return LIVE_EXECUTION_ENABLED and self.mode == "live" and bool(self.api_key) and bool(self.api_secret)

    def validate(self) -> None:
        if self.mode not in ("paper", "demo", "live"):
            raise ValueError("MODE must be 'paper', 'demo', or 'live'")
        if self.mode == "live" and not LIVE_EXECUTION_ENABLED:
            raise ValueError(
                "Live execution is disabled in this build. Use MODE=demo or paper; "
                "do not enable live until exchange protection, reconciliation, "
                "restart recovery, sandbox tests and independent review are complete."
            )
        if self.mode == "demo" and self.exchange_id != "bybit":
            raise ValueError("MODE=demo currently supports Bybit demo market-data routing only")
        if not 0 < self.risk_per_trade_pct <= MAX_RISK_PER_TRADE_PCT:
            raise ValueError("RISK_PER_TRADE_PCT must be greater than 0 and at most 0.25")
        if self.rsi_period < 2 or self.ema_period < 2:
            raise ValueError("RSI_PERIOD and EMA_PERIOD must be at least 2")
        if not 0 < self.rsi_oversold < self.rsi_overbought < 100:
            raise ValueError("Require 0 < RSI_OVERSOLD < RSI_OVERBOUGHT < 100")
        if self.candle_limit < max(self.rsi_period + 2, self.ema_period):
            raise ValueError("CANDLE_LIMIT must cover RSI and EMA warmup periods")
        if self.max_position_pct <= 0 or self.stop_loss_pct <= 0 or self.take_profit_pct <= 0:
            raise ValueError("Position, stop-loss and take-profit limits must be positive")
        if self.max_open_positions < 1 or self.poll_interval_seconds < 1:
            raise ValueError("MAX_OPEN_POSITIONS and POLL_INTERVAL_SECONDS must be positive")

config = Config()
