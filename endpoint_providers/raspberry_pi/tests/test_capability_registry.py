from __future__ import annotations

import unittest

from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.config import (
    RpiEndpointConfig,
    SecurityConfig,
)
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.registry import build_default_registry


class CapabilityRegistryTests(unittest.TestCase):
    def test_default_capabilities_registered_without_safe_shell(self):
        registry = build_default_registry(RpiEndpointConfig(), force_fake_gpio=True)

        names = registry.names()

        self.assertIn("rpi.echo", names)
        self.assertIn("rpi.system.info", names)
        self.assertIn("rpi.gpio.read", names)
        self.assertIn("rpi.gpio.write", names)
        self.assertNotIn("rpi.shell.safe_exec", names)

    def test_safe_shell_advertised_only_when_enabled_with_allowlist(self):
        disabled_registry = build_default_registry(
            RpiEndpointConfig(security=SecurityConfig(safe_shell_enabled=True, safe_shell_allowlist=[])),
            force_fake_gpio=True,
        )
        enabled_registry = build_default_registry(
            RpiEndpointConfig(
                security=SecurityConfig(
                    safe_shell_enabled=True,
                    safe_shell_allowlist=[{"name": "python-version", "argv": ["python", "--version"]}],
                )
            ),
            force_fake_gpio=True,
        )

        self.assertNotIn("rpi.shell.safe_exec", disabled_registry.names())
        self.assertIn("rpi.shell.safe_exec", enabled_registry.names())

    def test_tool_definitions_use_rpi_endpoint_prefix(self):
        config = RpiEndpointConfig(endpoint_id="pi-one", workspace_ids=["lab"])
        registry = build_default_registry(config, force_fake_gpio=True)

        tool_ids = {item["tool_key"]: item["tool_id"] for item in registry.tool_definitions()}

        self.assertEqual(tool_ids["rpi.echo"], "endpoint.rpi.pi-one.executor.rpi.echo")


if __name__ == "__main__":
    unittest.main()

