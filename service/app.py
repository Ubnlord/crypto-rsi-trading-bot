"""FastAPI service for the RSI trading SaaS.

Trading remains hard-disabled. Protected customer endpoints require a verified
JWT and a restricted PostgreSQL role; they fail closed if either is missing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from service.auth import Principal, require_principal
from service.db import tenant_db

app = FastAPI(title="RSI Trading Platform API", version="0.3.0")
LIVE_EXECUTION_ENABLED = False
ORDER_SUBMISSION_ENABLED = False
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


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return response


@app.get("/health", response_model=dict[str, str])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "rsi-trading-platform"}


@app.get("/api/v1/status", response_model=ServiceStatus)
def status() -> ServiceStatus:
    return ServiceStatus(service="rsi-trading-platform", status="ready-for-integration",
                         live_execution_enabled=LIVE_EXECUTION_ENABLED,
                         order_submission_enabled=ORDER_SUBMISSION_ENABLED,
                         timestamp=datetime.now(timezone.utc).isoformat())


@app.get("/api/v1/risk-policy", response_model=RiskPolicy)
def risk_policy() -> RiskPolicy:
    return RiskPolicy(max_risk_per_trade_pct=MAX_RISK_PER_TRADE_PCT,
                      max_position_notional_pct=10.0, max_open_positions=1, fail_closed=True)


@app.get("/api/v1/me")
def me(principal: Principal = Depends(require_principal)):
    return {"user_id": principal.user_id, "issuer": principal.issuer}


@app.get("/api/v1/tenants")
def list_tenants(principal: Principal = Depends(require_principal)):
    with tenant_db(principal.user_id) as conn:
        rows = conn.execute(
            "SELECT id, name, plan, status, created_at FROM tenants ORDER BY created_at DESC"
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/v1/tenants/{tenant_id}/strategies")
def list_strategies(tenant_id: UUID, principal: Principal = Depends(require_principal)):
    with tenant_db(principal.user_id) as conn:
        rows = conn.execute(
            """SELECT id, strategy_key, symbol, timeframe, state, execution_mode, created_at
               FROM strategy_instances WHERE tenant_id = %s ORDER BY created_at DESC""",
            (tenant_id,),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/v1/tenants/{tenant_id}/connections")
def list_connections(tenant_id: UUID, principal: Principal = Depends(require_principal)):
    with tenant_db(principal.user_id) as conn:
        rows = conn.execute(
            """SELECT id, provider, label, environment, status, last_verified_at, created_at
               FROM exchange_connections WHERE tenant_id = %s ORDER BY created_at DESC""",
            (tenant_id,),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/v1/trading/enable")
def enable_trading(principal: Principal = Depends(require_principal)) -> Any:
    raise HTTPException(status_code=409, detail="Order execution is locked pending connector integration, reconciliation, and independent review.")
