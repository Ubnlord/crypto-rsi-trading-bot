import unittest
from uuid import uuid4

try:
    from fastapi.testclient import TestClient
    from service.app import app
    from service.auth import Principal, require_principal
except ImportError:
    TestClient = None
    app = None
    Principal = None
    require_principal = None


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed")
class ServiceAPITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.pop(require_principal, None)

    def test_health_is_available(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_status_never_claims_order_execution_enabled(self):
        response = self.client.get("/api/v1/status")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["live_execution_enabled"])
        self.assertFalse(response.json()["order_submission_enabled"])

    def test_risk_policy_is_capped_at_quarter_percent(self):
        response = self.client.get("/api/v1/risk-policy")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["max_risk_per_trade_pct"], 0.25)
        self.assertTrue(response.json()["fail_closed"])

    def test_order_execution_route_is_locked(self):
        # Exercise the route's locked-state response after authentication.
        # This does not bypass authentication in production; it only supplies
        # a test principal so the endpoint's 409 execution gate is testable.
        app.dependency_overrides[require_principal] = lambda: Principal(
            user_id=str(uuid4()),
            issuer="https://issuer.example.test",
            claims={"sub": str(uuid4())},
        )
        response = self.client.post("/api/v1/trading/enable")
        self.assertEqual(response.status_code, 409)

    def test_security_headers_are_present(self):
        response = self.client.get("/health")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
