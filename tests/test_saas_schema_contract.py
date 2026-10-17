import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "migrations" / "001_saas_core.sql"

class SaaSSchemaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = SCHEMA.read_text(encoding="utf-8")

    def test_core_records_are_tenant_scoped(self):
        for table in (
            "exchange_connections", "strategy_instances", "order_intents",
            "fills", "audit_events",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", self.sql)
        self.assertGreaterEqual(self.sql.count("tenant_id uuid NOT NULL REFERENCES tenants(id)"), 5)

    def test_cross_tenant_foreign_keys_are_composite(self):
        self.assertIn("FOREIGN KEY (tenant_id, connection_id)", self.sql)
        self.assertIn("FOREIGN KEY (tenant_id, strategy_id)", self.sql)
        self.assertIn("FOREIGN KEY (tenant_id, order_intent_id)", self.sql)

    def test_rls_enabled_and_forced_for_tenant_tables(self):
        self.assertIn("ENABLE ROW LEVEL SECURITY", self.sql)
        self.assertIn("FORCE ROW LEVEL SECURITY", self.sql)
        self.assertIn("app_is_tenant_member(tenant_id)", self.sql)
        self.assertIn("app_is_tenant_member(id)", self.sql)

    def test_secrets_are_external_references_and_live_is_not_default(self):
        self.assertIn("secret_ref text NOT NULL", self.sql)
        self.assertIn("DEFAULT 'paper' CHECK (execution_mode IN ('paper','demo','live'))", self.sql)
        self.assertIn("never store API keys or secrets in this table", self.sql)

    def test_audit_and_fill_rows_have_no_client_write_policies(self):
        self.assertNotIn("CREATE POLICY fills_member_all", self.sql)
        self.assertNotIn("CREATE POLICY audit_member_all", self.sql)

if __name__ == "__main__":
    unittest.main()
