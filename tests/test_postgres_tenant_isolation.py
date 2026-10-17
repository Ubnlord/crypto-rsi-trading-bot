"""Real PostgreSQL RLS tests. Run only against a disposable database."""
from __future__ import annotations

import os
import unittest
import uuid

try:
    import psycopg
except ImportError:
    psycopg = None

DSN = os.getenv("TEST_DATABASE_URL", "")


@unittest.skipUnless(psycopg is not None and DSN, "requires TEST_DATABASE_URL and psycopg")
class PostgresTenantIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # CI uses a fresh disposable PostgreSQL service; these setup statements
        # intentionally create a restricted role and fixture data in that DB.
        cls.owner = psycopg.connect(DSN, autocommit=True)
        with cls.owner.cursor() as c:
            c.execute("CREATE ROLE app_runtime NOLOGIN")
            c.execute("GRANT CONNECT ON DATABASE " + cls.owner.info.dbname + " TO app_runtime")
            c.execute("GRANT USAGE ON SCHEMA public TO app_runtime")
            with open("migrations/001_saas_core.sql", encoding="utf-8") as migration:
                c.execute(migration.read())
            c.execute("GRANT SELECT ON tenants, tenant_memberships, exchange_connections, strategy_instances, order_intents, fills, audit_events TO app_runtime")
            c.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_runtime")
            c.execute("GRANT EXECUTE ON FUNCTION app_is_tenant_member(uuid) TO app_runtime")
            c.execute("GRANT INSERT, UPDATE, DELETE ON exchange_connections, strategy_instances, order_intents TO app_runtime")
        cls.user_a, cls.user_b = uuid.uuid4(), uuid.uuid4()
        cls.tenant_a, cls.tenant_b = uuid.uuid4(), uuid.uuid4()
        cls.conn_a, cls.conn_b = uuid.uuid4(), uuid.uuid4()
        cls.strategy_a, cls.strategy_b = uuid.uuid4(), uuid.uuid4()
        with cls.owner.cursor() as c:
            c.execute("INSERT INTO app_users(id,email) VALUES (%s,%s),(%s,%s)",
                      (cls.user_a, "a@example.test", cls.user_b, "b@example.test"))
            c.execute("INSERT INTO tenants(id,name) VALUES (%s,'Tenant A'),(%s,'Tenant B')",
                      (cls.tenant_a, cls.tenant_b))
            c.execute("INSERT INTO tenant_memberships(tenant_id,user_id,role) VALUES (%s,%s,'owner'),(%s,%s,'owner')",
                      (cls.tenant_a, cls.user_a, cls.tenant_b, cls.user_b))
            c.execute("INSERT INTO exchange_connections(id,tenant_id,provider,label,environment,secret_ref) VALUES (%s,%s,'bybit','A demo','demo','secret://a'),(%s,%s,'bybit','B demo','demo','secret://b')",
                      (cls.conn_a, cls.tenant_a, cls.conn_b, cls.tenant_b))
            c.execute("INSERT INTO strategy_instances(id,tenant_id,connection_id,symbol,timeframe) VALUES (%s,%s,%s,'BTC/USDT','15m'),(%s,%s,%s,'ETH/USDT','15m')",
                      (cls.strategy_a, cls.tenant_a, cls.conn_a, cls.strategy_b, cls.tenant_b, cls.conn_b))
        cls.owner.execute("GRANT app_runtime TO CURRENT_USER")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "owner", None):
            with cls.owner.cursor() as c:
                c.execute("DROP SCHEMA public CASCADE")
                c.execute("CREATE SCHEMA public")
                c.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER")
                c.execute("REVOKE app_runtime FROM CURRENT_USER")
                c.execute("DROP ROLE IF EXISTS app_runtime")
            cls.owner.close()

    def as_runtime(self, user_id, sql, params=()):
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute("SET ROLE app_runtime")
            conn.execute("BEGIN")
            conn.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (str(user_id),))
            result = conn.execute(sql, params).fetchall()
            conn.execute("ROLLBACK")
            return result

    def test_customer_a_cannot_read_customer_b_tenant_or_strategy(self):
        tenants = self.as_runtime(self.user_a, "SELECT id FROM tenants ORDER BY id")
        strategies = self.as_runtime(self.user_a, "SELECT id FROM strategy_instances ORDER BY id")
        self.assertEqual({r[0] for r in tenants}, {self.tenant_a})
        self.assertEqual({r[0] for r in strategies}, {self.strategy_a})

    def test_customer_b_cannot_read_customer_a_tenant_or_strategy(self):
        tenants = self.as_runtime(self.user_b, "SELECT id FROM tenants ORDER BY id")
        strategies = self.as_runtime(self.user_b, "SELECT id FROM strategy_instances ORDER BY id")
        self.assertEqual({r[0] for r in tenants}, {self.tenant_b})
        self.assertEqual({r[0] for r in strategies}, {self.strategy_b})

    def test_cross_tenant_write_is_rejected(self):
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute("SET ROLE app_runtime")
            conn.execute("BEGIN")
            conn.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (str(self.user_a),))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("INSERT INTO exchange_connections(tenant_id,provider,label,environment,secret_ref) VALUES (%s,'bybit','cross-tenant','demo','secret://bad')", (self.tenant_b,))
            conn.execute("ROLLBACK")


if __name__ == "__main__":
    unittest.main()
