import unittest

from fastapi.testclient import TestClient

from core.exceptions import ConfigError
from core.event_bus import EventBus
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway


class GatewayConfigApiTests(unittest.TestCase):
    def setUp(self):
        self.access_token = "config-token"

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
            access_token=self.access_token,
        )
        self.client = TestClient(self.gateway.app)
        self.addCleanup(self.client.close)

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    def test_get_config_snapshot(self):
        response = self.client.get("/config", headers=self._auth_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("api_provider", payload["items"])
        self.assertTrue(payload["items"]["api_key"]["is_secret"])

    def test_get_ui_schema(self):
        response = self.client.get("/schema/ui", headers=self._auth_headers())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["kind"], "schema")
        self.assertEqual(payload["ui_schema"]["http_schema"], "meetyou.http.v1")
        self.assertEqual(payload["ui_schema"]["ws_schema"], "meetyou.ws.v1")
        self.assertIn("connection", payload["ui_schema"]["ws_frame_kinds"])
        self.assertIn("debug", payload["ui_schema"]["ws_runtime_resources"])
        self.assertIn("thinking", payload["ui_schema"]["runtime_statuses"])
        self.assertTrue(
            any(item["value"] == "openai" for item in payload["ui_schema"]["providers"])
        )
        self.assertTrue(
            any(field["key"] == "api_provider" for field in payload["ui_schema"]["config_fields"])
        )

    def test_operator_config_surfaces_match_new_architecture(self):
        schema_response = self.client.get("/operator/schema/ui", headers=self._auth_headers())
        config_response = self.client.get("/operator/config", headers=self._auth_headers())

        self.assertEqual(schema_response.status_code, 200)
        self.assertEqual(config_response.status_code, 200)
        self.assertEqual(schema_response.json()["kind"], "schema")
        self.assertIn("api_provider", config_response.json()["items"])

    def test_get_single_config_item(self):
        response = self.client.get("/config/api_provider", headers=self._auth_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["key"], "api_provider")
        self.assertEqual(payload["value"], "openai")

    def test_patch_config(self):
        response = self.client.patch(
            "/config",
            json={"updates": {"api_provider": "anthropic"}},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["applied_keys"], ["api_provider"])
        self.assertEqual(payload["reloaded_components"], ["brain"])

    def test_patch_operator_config(self):
        response = self.client.patch(
            "/operator/config",
            json={"updates": {"api_provider": "anthropic"}},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["applied_keys"], ["api_provider"])

    def test_get_config_rejects_unauthorized_request(self):
        response = self.client.get("/config")

        self.assertEqual(response.status_code, 401)
        payload = response.json()
        self.assertEqual(payload["kind"], "error")
        self.assertEqual(payload["error"]["code"], "unauthorized")

    def test_patch_config_returns_bad_request_for_invalid_updates(self):
        async def failing_updater(updates):
            del updates
            raise ConfigError("gateway_port 需在 0 到 65535 之间")

        gateway = FastAPIGateway(
            EventBus(),
            SessionManager(),
            config_snapshot_getter=lambda: {},
            config_item_getter=lambda key: {"key": key},
            config_updater=failing_updater,
            access_token=self.access_token,
        )
        client = TestClient(gateway.app)
        self.addCleanup(client.close)

        response = client.patch(
            "/config",
            json={"updates": {"gateway_port": 70000}},
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["kind"], "error")
        self.assertIn("gateway_port", response.json()["error"]["message"])


if __name__ == "__main__":
    unittest.main()
