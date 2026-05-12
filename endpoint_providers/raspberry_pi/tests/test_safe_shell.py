from __future__ import annotations

import sys
import unittest
from tempfile import TemporaryDirectory

from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.capabilities.base import (
    CapabilityContext,
    CapabilityError,
)
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.capabilities.safe_shell import handle_safe_exec
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.config import (
    OperationConfig,
    RpiEndpointConfig,
    SecurityConfig,
)
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.registry import build_default_registry


class SafeShellTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_by_default(self):
        with TemporaryDirectory() as tmp:
            config = RpiEndpointConfig(security=SecurityConfig(sandbox_dir=tmp))
            context = CapabilityContext(config=config)

            with self.assertRaises(CapabilityError) as raised:
                await handle_safe_exec({"command": "python-ok"}, context)

        self.assertEqual(raised.exception.code, "safe_shell_disabled")

    async def test_rejects_arbitrary_commands(self):
        with TemporaryDirectory() as tmp:
            config = RpiEndpointConfig(
                security=SecurityConfig(
                    sandbox_dir=tmp,
                    safe_shell_enabled=True,
                    safe_shell_allowlist=[{"name": "python-ok", "argv": [sys.executable, "--version"]}],
                )
            )
            context = CapabilityContext(config=config)

            with self.assertRaises(CapabilityError) as raised:
                await handle_safe_exec({"command": "python-ok", "argv": ["echo", "bad"]}, context)

        self.assertEqual(raised.exception.code, "safe_shell_arbitrary_command_rejected")

    async def test_allows_only_configured_template(self):
        with TemporaryDirectory() as tmp:
            config = RpiEndpointConfig(
                operation=OperationConfig(default_timeout_seconds=5, max_timeout_seconds=5),
                security=SecurityConfig(
                    sandbox_dir=tmp,
                    safe_shell_enabled=True,
                    safe_shell_allowlist=[
                        {
                            "name": "python-ok",
                            "argv": [sys.executable, "-c", "print('ok')"],
                            "timeout_seconds": 5,
                        }
                    ],
                ),
            )
            context = CapabilityContext(config=config)

            result = await handle_safe_exec({"command": "python-ok"}, context)

        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"].strip(), "ok")

    def test_disabled_safe_shell_not_advertised(self):
        registry = build_default_registry(RpiEndpointConfig(), force_fake_gpio=True)

        self.assertNotIn("rpi.shell.safe_exec", registry.names())


if __name__ == "__main__":
    unittest.main()

