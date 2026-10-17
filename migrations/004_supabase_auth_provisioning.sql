-- Provision a local app account and personal workspace for Supabase Auth users.
-- The function is owned by the migration role, uses a fixed search_path, and
-- is invoked only by the auth.users trigger. It is not an API-callable RPC.
BEGIN;

CREATE OR REPLACE FUNCTION public.handle_new_auth_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  workspace_id uuid;
  safe_email text;
BEGIN
  safe_email := NULLIF(trim(NEW.email), '');
  IF safe_email IS NULL THEN
    RAISE EXCEPTION 'An email address is required to provision a trading account';
  END IF;

  INSERT INTO public.app_users (id, email, disabled_at)
  VALUES (NEW.id, safe_email, NULL)
  ON CONFLICT (id) DO UPDATE
    SET email = EXCLUDED.email
    WHERE public.app_users.disabled_at IS NULL;

  IF EXISTS (
    SELECT 1 FROM public.app_users
    WHERE id = NEW.id AND disabled_at IS NOT NULL
  ) THEN
    RETURN NEW;
  END IF;

  SELECT t.id INTO workspace_id
  FROM public.tenant_memberships AS m
  JOIN public.tenants AS t ON t.id = m.tenant_id
  WHERE m.user_id = NEW.id AND m.role = 'owner'
  ORDER BY m.created_at
  LIMIT 1;

  IF workspace_id IS NULL THEN
    INSERT INTO public.tenants (name, plan, status)
    VALUES ('Personal workspace', 'starter', 'active')
    RETURNING id INTO workspace_id;

    INSERT INTO public.tenant_memberships (tenant_id, user_id, role)
    VALUES (workspace_id, NEW.id, 'owner')
    ON CONFLICT (tenant_id, user_id) DO NOTHING;
  END IF;

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.handle_new_auth_user() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.handle_new_auth_user() FROM anon;
REVOKE ALL ON FUNCTION public.handle_new_auth_user() FROM authenticated;

DROP TRIGGER IF EXISTS on_auth_user_created_provision_trading_account ON auth.users;
CREATE TRIGGER on_auth_user_created_provision_trading_account
AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.handle_new_auth_user();

COMMIT;
