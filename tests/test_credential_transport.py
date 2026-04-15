from __future__ import annotations

import unittest

from core.credential_transport import contains_sensitive_fields, redact_sensitive_fields


class CredentialTransportTests(unittest.TestCase):
    def test_suffix_style_sensitive_fields_are_detected(self):
        payload = {
            "access_token": "token-a",
            "refresh_token": "token-b",
            "api_key": "key-c",
            "nested": {
                "service_token": "token-d",
                "cookie_header": "vpn=ok",
            },
        }

        self.assertTrue(contains_sensitive_fields(payload))

    def test_suffix_style_sensitive_fields_are_redacted(self):
        payload = {
            "access_token": "token-a",
            "refresh_token": "token-b",
            "api_key": "key-c",
            "nested": {
                "service_token": "token-d",
                "cookie_header": "vpn=ok",
                "safe_field": "keep-me",
            },
        }

        redacted = redact_sensitive_fields(payload)

        self.assertEqual(redacted["access_token"], "[REDACTED]")
        self.assertEqual(redacted["refresh_token"], "[REDACTED]")
        self.assertEqual(redacted["api_key"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["service_token"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["cookie_header"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["safe_field"], "keep-me")


if __name__ == "__main__":
    unittest.main()
