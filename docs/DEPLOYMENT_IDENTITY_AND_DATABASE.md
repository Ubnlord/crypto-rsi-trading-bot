# Deployment setup: Supabase Auth and restricted PostgreSQL runtime

This is an operator runbook, not proof that the app deployment has been configured. Never paste secrets into GitHub files, pull requests, logs, or chat.

## 1. Supabase Auth configuration

The trading SaaS uses the dedicated Supabase project `mavvurmaucnqtuizcznn`.

In the API deployment environment, configure these non-secret identity values:

- `JWT_JWKS_URL=https://mavvurmaucnqtuizcznn.supabase.co/auth/v1/.well-known/jwks.json`
- `JWT_ISSUER=https://mavvurmaucnqtuizcznn.supabase.co/auth/v1`
- `JWT_AUDIENCE=authenticated`

The URL Configuration Site URL must eventually be the deployed app URL. While there is no deployment yet, keep `http://localhost:3000` for local development and add `http://localhost:3000/**` as a development redirect. Do not treat localhost as a production callback.

Email sign-in is enabled in the project. Email confirmation is enabled. The migration `004_supabase_auth_provisioning.sql` adds an `auth.users` trigger to create the corresponding `app_users` row and a personal starter workspace with owner membership. This trigger has been applied to the dedicated Supabase project. Do not manually create duplicate user rows.

The API accepts RS256 and ES256 JWTs and verifies signature, issuer, audience, expiry, issued-at and UUID subject. The Supabase Auth user UUID is the expected `sub`. The API checks the local `app_users` row and rejects unknown or disabled accounts. Before launch, test valid tokens plus wrong issuer, wrong audience, expired token, bad signature, unknown user and disabled user.

## 2. Restricted PostgreSQL runtime role

Never use the database owner, superuser, or migration role as the API's `DATABASE_URL`. Create a dedicated role in the Supabase SQL editor as an administrator, using a generated password stored only in deployment secrets:

```sql
CREATE ROLE app_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
GRANT CONNECT ON DATABASE postgres TO app_runtime;
GRANT USAGE ON SCHEMA public TO app_runtime;
GRANT SELECT ON app_users, tenants, tenant_memberships, exchange_connections,
  strategy_instances, order_intents, fills, audit_events TO app_runtime;
GRANT EXECUTE ON FUNCTION app_is_tenant_member(uuid) TO app_runtime;
```

Set a strong password through a secure database/admin workflow; never commit it or paste it into chat. Configure the API's `DATABASE_URL` to use this role with TLS required. Verify `current_user = 'app_runtime'`, `rolsuper = false`, `rolcreatedb = false`, and `rolcreaterole = false`. Confirm the role is not a member of the owner/migration role.

The current API only reads these tables. Do not grant write privileges until write endpoints and their authorization/audit behavior have been implemented and reviewed. Never grant the runtime role schema creation, migrations, sequence, or role-management privileges.

## 3. Required verification

Run PostgreSQL 16 CI tests against a fresh disposable database; never run destructive integration-test cleanup against production. Verify that customer A and customer B cannot read or write each other's tenant records, missing identity context returns no tenant data, and database identity does not leak between pooled/reused connections.

Supabase's security advisor is not a substitute for these tests or an independent review. Record the reviewer, commit SHA, evidence, findings and explicit approval in the pull request.

Live execution and order submission must remain disabled until all tests pass and independent security plus trading-risk review explicitly approves the same commit SHA.
