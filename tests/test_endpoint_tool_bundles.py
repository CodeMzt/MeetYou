import unittest

from core.assistant_modes import get_default_assistant_capability_tools
from core.endpoint_tool_bundles import EXTERNAL_ENDPOINT_BASIC_TOOL_BUNDLE


class EndpointToolBundleTests(unittest.TestCase):
    def test_external_endpoint_bundle_allows_default_mode_and_skill_tools(self):
        bundle = EXTERNAL_ENDPOINT_BASIC_TOOL_BUNDLE

        self.assertIn("danxi_list_posts", bundle)
        self.assertIn("danxi_set_webvpn_cookie", bundle)
        self.assertIn("manage_schedule", bundle)
        self.assertIn("read_local_documents", bundle)
        self.assertIn("manage_tasks", bundle)
        self.assertIn("track_source_updates", bundle)
        self.assertIn("summarize_text", bundle)

        self.assertNotIn("send_endpoint_message", bundle)
        self.assertNotIn("exec_core_cmd", bundle)
        self.assertNotIn("exec_sys_cmd", bundle)
        self.assertEqual(len(bundle), len(set(bundle)))

    def test_external_endpoint_bundle_tracks_default_capability_catalog(self):
        excluded = {"send_endpoint_message", "exec_core_cmd", "exec_sys_cmd"}
        expected_tools = set(get_default_assistant_capability_tools(include_basic=True)) - excluded

        self.assertTrue(expected_tools.issubset(set(EXTERNAL_ENDPOINT_BASIC_TOOL_BUNDLE)))


if __name__ == "__main__":
    unittest.main()
