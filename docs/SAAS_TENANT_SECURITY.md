# Commercial multi-customer SaaS implementation notes

## Tenant model
- A customer workspace is a `tenants` row; users belong through `tenant_memberships`.
- Roles are owner, admin, trader, and viewer. Role-specific authorization must be enforced by the API before write operations; row-level security (RLS) is a second boundary, not a substitute for authorization.
- Every strategy, exchange connection, order intent, fill, and audit event carries a tenant ID. Composite foreign keys prevent cross-tenant references between strategies, connections, orders, and fills.
- `exchange_connections.secret_ref` is an opaque secret-manager reference. Never store API keys, passwords, access tokens, or MT5 credentials in the database, client app, logs, or Git.
- Customer API keys must be encrypted by a managed secret store, never returned to the web/Android client, and preferably have withdrawals disabled.

## Authentication and database boundary
The schema migration expects a trusted API to validate the JWT and set `request.jwt.claim.sub` for each database transaction. The API must use transaction-local context (for example, `SET LOCAL` or the provider's verified JWT context), clear it at transaction end, and never accept the user ID or tenant ID as proof of identity from request JSON. Do not expose PostgreSQL directly to customers.

The migration does not grant application database privileges or create a public registration flow. Those must be added deliberately after choosing the identity provider and deployment topology. Do not connect as the database owner from the API. Test RLS with a non-owner, non-superuser runtime role; PostgreSQL owners/superusers can bypass policies.

## Automated trading lifecycle
1. Receive a completed candle and validate timestamp, market, spread, and freshness.
2. Evaluate the versioned RSI-recovery/EMA strategy; store a unique signal identity.
3. Validate tenant plan, role, connection status, account environment, kill switch, daily loss, drawdown, total open risk, position count, notional, fees, and exchange constraints.
4. Persist a durable order intent and idempotency key before any connector submission.
5. Submit through a connector-specific adapter; treat timeouts as unknown, not as permission to retry blindly.
6. Reconcile exchange order state, partial fills, fees, balances, positions, and protective orders.
7. Append an immutable audit event and alert on any mismatch. Stop new entries on uncertain state.

## Mobile and web
The intended first client is a responsive web dashboard that also works in Android Chrome. A native Android app can follow using the same authenticated API. Never embed exchange credentials or trading secrets in either client. All customer views must be scoped to the authenticated tenant on the server.

## Release gates
- Schema migration replayed against a clean PostgreSQL instance.
- RLS isolation tested with at least two tenants and a restricted runtime role.
- API authentication, MFA/step-up for sensitive actions, rate limits, CSRF protection where cookie sessions are used, and tenant/role authorization reviewed.
- Connector contract and sandbox integration tests; partial-fill, timeout, duplicate-event, reconnect, missing-protection and restart fault injection.
- Per-tenant quotas and abuse controls, audit retention, backups and restore drills.
- Independent security and trading-risk review.
- PR remains draft and live execution stays disabled until the evidence is reviewed. This schema is a starting point, not a certification of production safety.
