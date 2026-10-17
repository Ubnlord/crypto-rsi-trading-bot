"""Initial service API for the trading product.

This service intentionally exposes status and risk policy only. It does not
submit orders. Do not expose it to the public internet until authentication,
authorization, TLS, rate limits, and secret management are implemented.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="RSI Trading Platform API", version="0.1.0")
LIVE_EXECUTION_ENABLED = False
MAX_RISK_PER_TRADE_PCT = 0.25

class ServiceStatus(BaseModel):
    service: str
    status: str
    live_execution_enabled: bool
    order_submission_enabled: bool
    timestamp: str

class RiskPolicy(BaseModel):
    max_risk_per_trade_pct: float
    max_position_notional_pct: float
    max_open_positions: int
    fail_closed: bool

@app.get("/health", response_model=dict[str, str])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "rsi-trading-platform"}

@app.get("/api/v1/status", response_model=ServiceStatus)
def status() -> ServiceStatus:
    return ServiceStatus(
        service="rsi-trading-platform",
        status="ready-for-integration",
        live_execution_enabled=LIVE_EXECUTION_ENABLED,
        order_submission_enabled=False,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

@app.get("/api/v1/risk-policy", response_model=RiskPolicy)
def risk_policy() -> RiskPolicy:
    return RiskPolicy(
        max_risk_per_trade_pct=MAX_RISK_PER_TRADE_PCT,
        max_position_notional_pct=10.0,
        max_open_positions=1,
        fail_closed=True,
    )

@app.post("/api/v1/trading/enable")
def enable_trading() -> Any:
    raise HTTPException(status_code=409, detail="Order execution is locked until connector integration, reconciliation, authentication, and independent review are complete.")
