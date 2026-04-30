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

        def list_skills(skill_type="all", query=""):
            skills = [
                {
                    "id": "mode:general",
                    "skill_type": "mode",
                    "title": "通用模式 SKILL",
                    "summary": "通用日常协作范式。",
                    "storage_path": "",
                    "storage_ref": "core://skills/mode/general",
                    "editable": False,
                    "source": "builtin",
                    "applicable_modes": ["general"],
                    "scenarios": ["日常对话"],
                    "recommended_tools": ["search_memory"],
                },
                {
                    "id": "task_recognition",
                    "skill_type": "reusable",
                    "title": "任务识别 SKILL",
                    "summary": "识别提醒、追踪、阻塞与任务状态请求。",
                    "storage_path": "",
                    "storage_ref": "core://skills/reusable/task_recognition",
                    "editable": False,
                    "source": "builtin",
                    "applicable_modes": ["general", "automation"],
                    "scenarios": ["提醒"],
                    "recommended_tools": ["manage_tasks"],
                },
            ]
            if skill_type != "all":
                skills = [item for item in skills if item["skill_type"] == skill_type]
            normalized_query = str(query or "").lower()
            if normalized_query:
                skills = [
                    item
                    for item in skills
                    if normalized_query in item["id"].lower()
                    or normalized_query in item["title"].lower()
                    or any(normalized_query in tool for tool in item["recommended_tools"])
                ]
            return skills

        def get_skill(skill_id):
            for item in list_skills():
                if item["id"] == skill_id:
                    return {**item, "content": f"# {item['title']}\n\nFollow this skill."}
            return None

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
            skill_list_getter=list_skills,
            skill_getter=get_skill,
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
        trusted_write_roots = next(
            field for field in payload["ui_schema"]["config_fields"] if field["key"] == "trusted_write_roots"
        )
        self.assertEqual(trusted_write_roots["control"], "directory_list")
        self.assertTrue(trusted_write_roots["help_text"])
        self.assertTrue(trusted_write_roots["examples"])
        web_search_quality = next(
            field for field in payload["ui_schema"]["config_fields"] if field["key"] == "web_search_quality"
        )
        self.assertEqual(web_search_quality["input"], "select")
        self.assertIn("deep", [option["value"] for option in web_search_quality["options"]])

    def test_operator_config_surfaces_match_new_architecture(self):
        schema_response = self.client.get("/operator/schema/ui", headers=self._auth_headers())
        config_response = self.client.get("/operator/config", headers=self._auth_headers())

        self.assertEqual(schema_response.status_code, 200)
        self.assertEqual(config_response.status_code, 200)
        self.assertEqual(schema_response.json()["kind"], "schema")
        self.assertIn("api_provider", config_response.json()["items"])

    def test_operator_skills_lists_registered_skills(self):
        response = self.client.get(
            "/operator/skills?skill_type=reusable&query=manage_tasks",
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], "task_recognition")
        self.assertEqual(payload[0]["skill_type"], "reusable")
        self.assertEqual(payload[0]["storage_path"], "")
        self.assertEqual(payload[0]["storage_ref"], "core://skills/reusable/task_recognition")
        self.assertFalse(payload[0]["editable"])

    def test_operator_skill_detail_loads_content(self):
        response = self.client.get(
            "/operator/skills/task_recognition",
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], "task_recognition")
        self.assertEqual(payload["storage_ref"], "core://skills/reusable/task_recognition")
        self.assertIn("Follow this skill", payload["content"])

    def test_operator_skill_detail_returns_404_for_unknown_skill(self):
        response = self.client.get(
            "/operator/skills/missing_skill",
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "skill_not_found")

    def test_operator_skills_rejects_unknown_skill_type(self):
        response = self.client.get(
            "/operator/skills?skill_type=procedure",
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["kind"], "error")
        self.assertEqual(response.json()["error"]["code"], "invalid_skill_type")

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

    def test_endpoint_websocket_rejects_wrong_access_token(self):
        gateway = FastAPIGateway(
            EventBus(),
            SessionManager(),
            access_token="gateway-token",
        )
        client = TestClient(gateway.app)
        self.addCleanup(client.close)

        with client.websocket_connect(
            "/endpoint/ws",
            headers={"Authorization": "Bearer wrong-token"},
        ) as websocket:
            payload = websocket.receive_json()

        self.assertEqual(payload["kind"], "error")
        self.assertEqual(payload["error"]["code"], "unauthorized")
        self.assertEqual(payload["error"]["details"]["auth_type"], "bearer_or_api_key_or_query")


if __name__ == "__main__":
    unittest.main()
