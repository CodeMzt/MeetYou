import asyncio
import json
import unittest
from unittest import mock

from core.exceptions import PlatformError
from platform_layer.detector import detect_platform, normalize_platform_system
from platform_layer.linux import LinuxPlatformAdapter
from platform_layer.macos import MacOSPlatformAdapter
from platform_layer.windows import WindowsPlatformAdapter
from tools import system_tools


class PlatformDetectorTests(unittest.TestCase):
    def test_normalize_platform_system_uses_repo_host_os_values(self):
        self.assertEqual(normalize_platform_system("Windows"), "windows")
        self.assertEqual(normalize_platform_system("Linux"), "linux")
        self.assertEqual(normalize_platform_system("Darwin"), "macos")

    def test_normalize_platform_system_rejects_unknown_platform(self):
        with self.assertRaises(PlatformError):
            normalize_platform_system("FreeBSD")

    def test_detect_platform_returns_expected_adapter(self):
        with mock.patch("platform_layer.detector.platform.system", return_value="Windows"):
            self.assertIsInstance(detect_platform(), WindowsPlatformAdapter)
        with mock.patch("platform_layer.detector.platform.system", return_value="Linux"):
            self.assertIsInstance(detect_platform(), LinuxPlatformAdapter)
        with mock.patch("platform_layer.detector.platform.system", return_value="Darwin"):
            self.assertIsInstance(detect_platform(), MacOSPlatformAdapter)


class PlatformCapabilitySemanticsTests(unittest.TestCase):
    def test_windows_ui_context_is_explicitly_marked_windows_only(self):
        capabilities = WindowsPlatformAdapter().describe_capabilities()
        self.assertEqual(capabilities["ui_context"]["status"], "enabled")
        self.assertEqual(capabilities["ui_context"]["availability"], "full")
        self.assertTrue(capabilities["ui_context"]["windows_only"])
        self.assertEqual(capabilities["ui_context"]["supported_platforms"], ["windows"])

    def test_linux_and_macos_disable_ui_context_instead_of_claiming_support(self):
        linux_capabilities = LinuxPlatformAdapter().describe_capabilities()
        macos_capabilities = MacOSPlatformAdapter().describe_capabilities()

        self.assertEqual(linux_capabilities["ui_context"]["status"], "disabled")
        self.assertEqual(linux_capabilities["ui_context"]["availability"], "disabled")
        self.assertIn("ui_automation_not_implemented_on_linux", linux_capabilities["ui_context"]["notes"])

        self.assertEqual(macos_capabilities["ui_context"]["status"], "disabled")
        self.assertEqual(macos_capabilities["ui_context"]["availability"], "disabled")
        self.assertIn("ui_automation_not_implemented_on_macos", macos_capabilities["ui_context"]["notes"])

    def test_background_status_includes_platform_capability_summary(self):
        class _FakeAdapter:
            def get_system_vitals(self):
                return {"cpu_percent": 1.0, "ram_percent": 2.0}

            def describe_capabilities(self):
                return {
                    "ui_context": {"status": "disabled"},
                    "system_vitals": {"status": "enabled"},
                }

        previous_adapter = system_tools._platform_adapter
        system_tools._platform_adapter = _FakeAdapter()
        try:
            payload = json.loads(asyncio.run(system_tools.get_background_status()))
        finally:
            system_tools._platform_adapter = previous_adapter

        self.assertEqual(payload["platform_adapter"], "_FakeAdapter")
        self.assertEqual(payload["platform_capabilities"]["ui_context"]["status"], "disabled")
        self.assertEqual(payload["system_vitals"]["cpu_percent"], 1.0)


if __name__ == "__main__":
    unittest.main()
