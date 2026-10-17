# Deployment setup: identity and restricted PostgreSQL runtime

This is an operator runbook, not proof that production has been configured. Do not paste secrets into GitHub files, pull requests, logs, or chat.

## 1. Trusted identity provider

Choose and configure the production identity provider first (for example, Auth0, Clerk, or another OIDC provider that publishes compatible JWKS). Create a dedicated API audience for this service and require access tokens issued for that audience.

Set these environment variables in the deployment platform's secret/environment settings:
- `JWT_JWKS_URL`: HTTPS JWKS endpoint from the chosen provider's official discovery metadata.
- `JWT_ISSUER`: exact issuer URL expected in the token.
- `JWT_AUDIENCE`: exact API audience configured at the provider.
- `DATABASE_URL`: connection string for the restricted runtime role below.

The API currently accepts RS256 and ES256 JWTs, checks signature/issuer/audience/expiration/issued-at/subject, and requires the subject to be a UUID. Configure the provider's immutable user ID to be a UUID or implement an explicit, verified identity-to-`app_users.id` mapping before launch. Do not trust a client-provided user or tenant ID. Do not put provider client secrets or exchange credentials in the repository.

Before launch, run issuer-backed integration tests for a valid token, wrong issuer, wrong audience, expired token, bad signature, unknown user, and disabled user. Current code does not yet reject a disabled `app_users` record, and this must be fixed before customer launch.

## 2. Create a least-privilege PostgreSQL runtime role

Run as a database administrator in the target database after reviewing `migrations/001_saas_core.sql`. Never use the database owner, superuser, or migration role as `DATABASE_URL`.

In `psql`, run the following commands, substituting the actual database name. Use the interactive password prompt; do not put the password in shell history.

```sql
CREATE ROLE app_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
\password app_runtime
GRANT CONNECT ON DATABASE YOUR_DATABASE_NAME TO app_runtime;
GRANT USAGE ON SCHEMA public TO app_runtime;
GRANT SELECT ON tenants, tenant_memberships, exchange_connections,
  strategy_instances, order_intents, fills, audit_events TO app_runtime;
GRANT EXECUTE ON FUNCTION app_is_tenant_member(uuid) TO app_runtime;
```

The current API only reads these tables. Do not grant write privileges until write endpoints and their authorization/audit behavior have been implemented and reviewed. Do not grant access to `app_users`, schema creation, migrations, sequences, or role management to the runtime role.

Set `DATABASE_URL` to use `app_runtime`, with TLS required by the database provider. Confirm with SQL that `current_user = 'app_runtime'`, `rolsuper = false`, `rolcreatedb = false`, and `rolcreaterole = false`. Verify RLS is enabled and forced on each tenant table and the runtime role is not a member of the owner/migration role.

## 3. Database isolation acceptance checks

Run the PostgreSQL 16 CI integration tests against a fresh disposable database. Additionally, against a staging database:
- customer A sees only A's tenant and tenant-owned records;
- customer B sees only B's records;
- cross-tenant SELECT returns no rows and cross-tenant writes fail;
- no identity leaks between pooled/reused connections;
- membership changes take effect immediately;
- missing identity context returns no tenant data;
- direct access as runtime role cannot bypass RLS.

Never run destructive integration-test cleanup against production.

## 4. Independent review gate

Obtain a separate reviewer who did not implement this code. Request review of JWT validation and identity mapping, RLS policy/function ownership and grants, runtime-role privileges, tenant cross-reference constraints, audit integrity, connection pooling, and fail-closed behavior. Record the reviewer, reviewed commit SHA, findings, evidence, and explicit approval in the pull request.

Live execution and order submission must remain disabled until all tests pass and independent security plus trading-risk review explicitly approves the same commit SHA.
