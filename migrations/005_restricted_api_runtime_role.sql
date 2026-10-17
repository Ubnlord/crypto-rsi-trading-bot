-- Create the least-privilege API runtime role for the Supabase SaaS database.
-- Set its password separately using a secure admin workflow; never commit secrets.
BEGIN;

CREATE ROLE app_runtime LOGIN NOINHERIT;
GRANT CONNECT ON DATABASE postgres TO app_runtime;
GRANT USAGE ON SCHEMA public TO app_runtime;
GRANT SELECT ON TABLE
  public.app_users,
  public.tenants,
  public.tenant_memberships,
  public.exchange_connections,
  public.strategy_instances,
  public.order_intents,
  public.fills,
  public.audit_events
TO app_runtime;
GRANT EXECUTE ON FUNCTION public.app_is_tenant_member(uuid) TO app_runtime;
GRANT EXECUTE ON FUNCTION public.app_current_user_id() TO app_runtime;

COMMIT;
