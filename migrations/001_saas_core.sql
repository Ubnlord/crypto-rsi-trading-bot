-- SaaS tenant isolation baseline. Apply only to an isolated PostgreSQL database first.
-- The API must validate the caller's JWT and set request.jwt.claim.sub transaction-locally.
-- Never grant customers direct database credentials or use a database owner role in the API.
BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS app_users (
  id uuid PRIMARY KEY,
  email text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  disabled_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS app_users_email_lower_uidx ON app_users (lower(email));

CREATE TABLE IF NOT EXISTS tenants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (length(trim(name)) BETWEEN 2 AND 120),
  plan text NOT NULL DEFAULT 'starter' CHECK (plan IN ('starter','pro','enterprise')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','closed')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_memberships (
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('owner','admin','trader','viewer')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS exchange_connections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  provider text NOT NULL CHECK (provider IN ('bybit','mt5')),
  label text NOT NULL CHECK (length(trim(label)) BETWEEN 1 AND 100),
  environment text NOT NULL CHECK (environment IN ('demo','live')),
  secret_ref text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','connected','degraded','revoked')),
  last_verified_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id)
);
COMMENT ON COLUMN exchange_connections.secret_ref IS
  'Opaque reference to external secret manager; never store API keys or secrets in this table.';

CREATE TABLE IF NOT EXISTS strategy_instances (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  connection_id uuid NOT NULL,
  strategy_key text NOT NULL DEFAULT 'rsi_recovery_ema',
  symbol text NOT NULL,
  timeframe text NOT NULL,
  config jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(config) = 'object'),
  state text NOT NULL DEFAULT 'stopped' CHECK (state IN ('stopped','starting','running','paused','error')),
  execution_mode text NOT NULL DEFAULT 'paper' CHECK (execution_mode IN ('paper','demo','live')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, connection_id) REFERENCES exchange_connections(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS order_intents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  strategy_id uuid NOT NULL,
  client_order_id text NOT NULL,
  provider_order_id text,
  symbol text NOT NULL,
  side text NOT NULL CHECK (side IN ('buy','sell')),
  order_type text NOT NULL CHECK (order_type IN ('market','limit','stop_market','take_profit_market')),
  quantity numeric(30,12) NOT NULL CHECK (quantity > 0),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','submitting','unknown','accepted','partially_filled','filled','cancelled','rejected','failed')),
  execution_mode text NOT NULL CHECK (execution_mode IN ('paper','demo','live')),
  requested_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, client_order_id),
  FOREIGN KEY (tenant_id, strategy_id) REFERENCES strategy_instances(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS fills (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  order_intent_id uuid NOT NULL,
  provider_fill_id text NOT NULL,
  quantity numeric(30,12) NOT NULL CHECK (quantity > 0),
  price numeric(30,12) NOT NULL CHECK (price > 0),
  fee numeric(30,12) NOT NULL DEFAULT 0 CHECK (fee >= 0),
  fee_currency text,
  filled_at timestamptz NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, provider_fill_id),
  FOREIGN KEY (tenant_id, order_intent_id) REFERENCES order_intents(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS audit_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  actor_user_id uuid REFERENCES app_users(id) ON DELETE SET NULL,
  event_type text NOT NULL,
  entity_type text NOT NULL,
  entity_id text,
  request_id text,
  details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
  occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS tenant_memberships_user_idx ON tenant_memberships(user_id);
CREATE INDEX IF NOT EXISTS strategies_tenant_state_idx ON strategy_instances(tenant_id, state);
CREATE INDEX IF NOT EXISTS orders_tenant_status_idx ON order_intents(tenant_id, status, requested_at DESC);
CREATE INDEX IF NOT EXISTS fills_tenant_time_idx ON fills(tenant_id, filled_at DESC);
CREATE INDEX IF NOT EXISTS audit_tenant_time_idx ON audit_events(tenant_id, occurred_at DESC);

CREATE OR REPLACE FUNCTION app_current_user_id() RETURNS uuid
LANGUAGE sql STABLE
AS $$
  SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION app_is_tenant_member(target_tenant uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM tenant_memberships m
    WHERE m.tenant_id = target_tenant AND m.user_id = app_current_user_id()
  )
$$;
REVOKE ALL ON FUNCTION app_is_tenant_member(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_is_tenant_member(uuid) TO PUBLIC;

DO $$
DECLARE tbl text;
BEGIN
  FOREACH tbl IN ARRAY ARRAY[
    'tenants','tenant_memberships','exchange_connections','strategy_instances',
    'order_intents','fills','audit_events'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
  END LOOP;
END $$;

DROP POLICY IF EXISTS tenants_member_select ON tenants;
CREATE POLICY tenants_member_select ON tenants FOR SELECT USING (app_is_tenant_member(id));
DROP POLICY IF EXISTS memberships_member_select ON tenant_memberships;
CREATE POLICY memberships_member_select ON tenant_memberships FOR SELECT USING (app_is_tenant_member(tenant_id));
DROP POLICY IF EXISTS connections_member_all ON exchange_connections;
CREATE POLICY connections_member_all ON exchange_connections USING (app_is_tenant_member(tenant_id)) WITH CHECK (app_is_tenant_member(tenant_id));
DROP POLICY IF EXISTS strategies_member_all ON strategy_instances;
CREATE POLICY strategies_member_all ON strategy_instances USING (app_is_tenant_member(tenant_id)) WITH CHECK (app_is_tenant_member(tenant_id));
DROP POLICY IF EXISTS orders_member_all ON order_intents;
CREATE POLICY orders_member_all ON order_intents USING (app_is_tenant_member(tenant_id)) WITH CHECK (app_is_tenant_member(tenant_id));
DROP POLICY IF EXISTS fills_member_select ON fills;
CREATE POLICY fills_member_select ON fills FOR SELECT USING (app_is_tenant_member(tenant_id));
DROP POLICY IF EXISTS audit_member_select ON audit_events;
CREATE POLICY audit_member_select ON audit_events FOR SELECT USING (app_is_tenant_member(tenant_id));

-- Deliberately no client INSERT/UPDATE/DELETE policies for audit rows or fills.
COMMIT;
