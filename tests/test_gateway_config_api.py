import unittest

from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway


class GatewayConfigApiTests(unittest.TestCase):
    def setUp(self):
        async def updater(updates):
            return {
                "applied_keys": sorted(updates.keys()),
                "reloaded_components": ["brain"],
                "restart_required_keys": [],
                "warnings": [],
            }

        self.gateway = FastAPIGateway(
            EventBus(),
            SessionManager(),
            config_snapshot_getter=lambda: {
                "api_provider": {
                    "key": "api_provider",
                    "value": "openai",
                    "is_secret": False,
                    "has_value": True,
                    "source": "config",
                    "env_key": None,
                },
                "api_key": {
                    "key": "api_key",
                    "value": "te*****et",
                    "is_secret": True,
                    "has_value": True,
                    "source": "env",
                    "env_key": "MEETYOU_API_KEY",
                },
            },
            config_item_getter=lambda key: {
                "key": key,
                "value": "openai" if key == "api_provider" else "te*****et",
                "is_secret": key == "api_key",
                "has_value": True,
                "source": "config" if key == "api_provider" else "env",
                "env_key": None if key == "api_provider" else "MEETYOU_API_KEY",
            },
            config_updater=updater,
        )
        self.client = TestClient(self.gateway.app)
        self.addCleanup(self.client.close)

    def test_get_config_snapshot(self):
        response = self.client.get("/config")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("api_provider", payload["items"])
        self.assertTrue(payload["items"]["api_key"]["is_secret"])

    def test_get_single_config_item(self):
        response = self.client.get("/config/api_provider")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["key"], "api_provider")
        self.assertEqual(payload["value"], "openai")

    def test_patch_config(self):
        response = self.client.patch(
            "/config",
            json={"updates": {"api_provider": "anthropic"}},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["applied_keys"], ["api_provider"])
        self.assertEqual(payload["reloaded_components"], ["brain"])


if __name__ == "__main__":
    unittest.main()
