from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.config import (
    RpiConfigError,
    load_rpi_endpoint_config,
)


class RpiConfigTests(unittest.TestCase):
    def _write_config(self, root: Path, payload: dict) -> Path:
        path = root / "rpi.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_loads_example_config(self):
        config = load_rpi_endpoint_config("user/rpi_endpoint.example.json")

        self.assertEqual(config.core_base_url, "https://core.example.com")
        self.assertEqual(config.endpoint_id, "raspberry-pi-dev")
        self.assertEqual(config.connect_path, "/endpoint/ws")
        self.assertEqual(config.security.gpio_allowed_pins, [17, 27, 22])
        self.assertFalse(config.security.safe_shell_enabled)
        self.assertEqual([device.device_id for device in config.devices], ["desk_led", "relay_1", "button_1"])
        self.assertTrue(config.devices[1].effective_requires_confirmation)

    def test_env_overrides_work(self):
        with TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {
                "MEETYOU_RPI_CORE_BASE_URL": "http://127.0.0.1:9000",
                "MEETYOU_RPI_ENDPOINT_ID": "pi-lab",
                "MEETYOU_RPI_ENDPOINT_TOKEN": "test-token",
            },
            clear=True,
        ):
            path = self._write_config(Path(tmp), {"core_base_url": "https://config.example", "endpoint_id": "config-pi"})

            config = load_rpi_endpoint_config(str(path))

        self.assertEqual(config.core_base_url, "http://127.0.0.1:9000")
        self.assertEqual(config.endpoint_id, "pi-lab")
        self.assertTrue(config.token_status()["configured"])

    def test_missing_token_is_reported_safely(self):
        with TemporaryDirectory() as tmp, patch.dict("os.environ", {}, clear=True):
            path = self._write_config(Path(tmp), {"endpoint_token_env": "MEETYOU_RPI_ENDPOINT_TOKEN"})
            config = load_rpi_endpoint_config(str(path))

        with self.assertRaises(RpiConfigError) as raised:
            config.require_token()

        self.assertEqual(raised.exception.code, "missing_endpoint_token")
        self.assertNotIn("secret", raised.exception.message.lower())


if __name__ == "__main__":
    unittest.main()
