# Production Trading Platform — Product Blueprint

## Product objective

Turn the RSI trading bot into a maintainable trading application for a single owner first, with a clear path to multi-user operation later. Support crypto exchange accounts and MetaTrader 5 forex accounts through separate adapters. Do not mix broker/exchange credentials, positions, risk calculations, or order lifecycles.

## Production principles

- Real product, not a demo-only code path: real market data, account connectivity, durable state, real order lifecycle interfaces, operational monitoring, and deployment documentation.
- Live order execution remains fail-closed until each connector passes its integration tests and independent review. Never use production credentials in tests.
- Default to no new orders after uncertain state, stale data, missing protection, risk calculation failure, reconciliation mismatch, or loss of broker connectivity.
- Never promise profit. Backtests and paper simulations do not establish future performance.
- Secrets are stored outside the repository. API keys must have withdrawals disabled and only the minimum trading/read permissions needed.

## Target architecture

1. Web UI — account connection status, equity, positions, orders, fills, strategy state, risk limits, alerts, and audit history.
2. API/service layer — authenticated commands, request validation, account ownership, idempotency keys, and operator actions.
3. Strategy engine — RSI recovery + EMA trend filter, candle completeness checks, signal timestamps, and explicit strategy version.
4. Risk engine — maximum planned risk 0.25% per trade by default; total open risk, daily loss, position count, leverage/notional, spread, stale-data and cooldown checks. Risk is recalculated against actual contract specs and fees.
5. Connector interfaces — separate CCXT crypto and MT5 forex implementations with normalized order/position models but broker-specific execution behavior.
6. Order coordinator — durable intent before submission, unique client order IDs, idempotent retries, explicit unknown state on timeouts, fill aggregation, and protective-order verification.
7. Persistence — PostgreSQL in hosted production; schema migrations; immutable order/fill/audit records; no secrets in application tables or logs.
8. Operations — health checks, structured logs, alerts, backup/restore, startup reconciliation, kill switch, and graceful shutdown.

## Required connector behavior

### Crypto (CCXT / Bybit first)

- Confirm supported market type, symbol metadata, amount/price precision, minimum quantity and notional before sizing.
- Use real exchange endpoints only when explicitly configured for the production environment; no silent fallback to demo or paper.
- Validate order acceptance and query state by exchange order ID/client order ID.
- Reconcile partial fills, fees, cancellations, timeouts, and balances.
- Verify exchange-native stop-loss/take-profit orders for the exact spot or derivatives product. Do not assume generic OCO support.
- If protective orders cannot be verified after a fill, block new entries, alert, and run a documented recovery procedure.

### Forex (MetaTrader 5)

- Use a dedicated Windows service/host with MT5 terminal installed; a typical Linux Codespace is not a suitable MT5 terminal runtime.
- Confirm account identity and account mode explicitly; never infer demo/live from a server name alone.
- Use broker symbol metadata, order_calc_profit, order_check, volume min/max/step, margin checks, and attached SL/TP.
- Persist tickets/deals and reconcile them after reconnect/restart.
- Do not submit orders until the MT5 connector has passed broker-specific integration tests.

## Risk controls

Initial defaults: 0.25% maximum planned equity risk per trade, one open position per strategy until portfolio risk accounting is complete, 10% maximum notional allocation per position, and trading disabled after any failed safety invariant. These are starting limits, not a guarantee of maximum realized loss. Gaps, slippage, fees and outages can exceed planned risk.

Before enabling live order submission, add and test: daily loss stop, total open risk cap across both markets, equity drawdown stop, stale candle and spread rejection, duplicate-signal suppression, cooldown, kill switch, and restart recovery.

## Release gates

1. Unit and property tests for sizing, precision, idempotency and state transitions.
2. Connector contract tests using mocked responses.
3. Integration tests against exchange/broker test accounts with sanitized evidence.
4. Fault injection: timeouts, partial fills, duplicate events, API outage, stale prices, missing stops, and process restart.
5. Accounting reconciliation of orders, fills, fees, cash, positions and realized/unrealized PnL.
6. Independent security and trading-risk review.
7. Staged rollout with tiny limits, operator monitoring and documented rollback.
8. Live execution can only be enabled through a separate, reviewed release change; this branch must not enable it automatically.

## Immediate implementation order

1. Keep existing strategy and hard live-execution gate.
2. Add a production service/API and health checks without order submission.
3. Introduce durable trade/order schema and reconciliation state machine.
4. Implement and test Bybit spot connector, including native protective orders.
5. Implement MT5 connector on a supported Windows host.
6. Add the dashboard, alerts, deployment, backup and operational runbooks.
7. Complete review and staged release gates.

## Explicit current limitations

The existing branch is not production-ready yet. The Bybit branch currently routes market-data requests to Bybit demo when configured and still simulates fills locally. The MT5 connector is read-only. Exchange-native protection, real order execution, full reconciliation, persistent service/API, dashboard, and broker-specific integration evidence remain to be implemented. Do not represent this blueprint as proof that live trading is safe.