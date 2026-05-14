from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.health import (
    HealthCheckResult,
    _check_gpio_backend,
    load_env_file,
    render_health_results,
    run_health_checks,
)
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.config import RpiEndpointConfig, SecurityConfig


class HealthCheckTests(unittest.TestCase):
    def _write_config(self, root: Path) -> Path:
        path = root / "rpi.json"
        path.write_text(
            json.dumps(
                {
                    "endpoint_token_env": "MEETYOU_RPI_ENDPOINT_TOKEN",
                    "security": {
                        "sandbox_dir": str(root / "sandbox"),
                        "gpio_allowed_pins": [17],
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_env_file_loader_does_not_render_token_value(self):
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "rpi.env"
            env_file.write_text("MEETYOU_RPI_ENDPOINT_TOKEN=super-secret-token\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                result = load_env_file(env_file)
                rendered = render_health_results([result])

                self.assertEqual(os.environ["MEETYOU_RPI_ENDPOINT_TOKEN"], "super-secret-token")

        self.assertIn("env_file", rendered)
        self.assertNotIn("super-secret-token", rendered)

    def test_health_output_never_prints_token_value(self):
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"MEETYOU_RPI_ENDPOINT_TOKEN": "super-secret-token"},
            clear=True,
        ):
            config_path = self._write_config(Path(tmp))
            patched = [
                patch(
                    "endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.health._check_gpio_backend",
                    return_value=HealthCheckResult("gpio_backend", "PASS", "mock gpio ok"),
                ),
                patch(
                    "endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.health._check_gpio_group",
                    return_value=HealthCheckResult("gpio_group", "PASS", "mock group ok"),
                ),
                patch(
                    "endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.health._check_gpiochip_permissions",
                    return_value=HealthCheckResult("gpiochip_permissions", "PASS", "mock gpiochip ok"),
                ),
                patch(
                    "endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.health._check_systemd_service",
                    return_value=HealthCheckResult("systemd_service", "PASS", "mock service ok"),
                ),
            ]
            with patched[0], patched[1], patched[2], patched[3]:
                rendered = render_health_results(run_health_checks(config_path=config_path))

        self.assertIn("[PASS] token_env", rendered)
        self.assertIn("MEETYOU_RPI_ENDPOINT_TOKEN", rendered)
        self.assertIn("value redacted", rendered)
        self.assertNotIn("super-secret-token", rendered)

    def test_raspberry_pi_health_requires_explicit_lgpio_env(self):
        config = RpiEndpointConfig(security=SecurityConfig(gpio_allowed_pins=[17]))

        with patch.dict(os.environ, {}, clear=True), patch(
            "endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.health._looks_like_raspberry_pi",
            return_value=True,
        ):
            result = _check_gpio_backend(config)

        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.name, "gpio_backend")
        self.assertIn("MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio", result.message)


if __name__ == "__main__":
    unittest.main()
