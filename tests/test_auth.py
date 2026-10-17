import unittest
from unittest.mock import patch
from fastapi import HTTPException

from service.auth import verified_claims


class AuthenticationConfigTests(unittest.TestCase):
    def test_missing_provider_configuration_fails_closed(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(HTTPException) as caught:
                verified_claims("not-a-real-token")
        self.assertEqual(caught.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
