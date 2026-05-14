from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from .base import (
    CapabilityContext,
    CapabilityDefinition,
)
from .gpio import (
    FakeGPIOBackend,
    GpioZeroBackend,
    UnavailableGPIOBackend,
    _select_gpio_pin_factory_name,
)


async def handle_system_info(arguments: dict[str, Any], context: CapabilityContext) -> dict[str, Any]:
    del arguments
    return collect_system_info(config=context.config, gpio_backend=context.gpio_backend)


def collect_system_info(*, config: Any | None = None, gpio_backend: Any | None = None) -> dict[str, Any]:
    disk = _disk_summary("/")
    return {
        "summary": f"{socket.gethostname()} {platform.system()} {platform.machine()}",
        "hostname": socket.gethostname(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "python": {
            "version": sys.version.split()[0],
            "implementation": platform.python_implementation(),
        },
        "uptime_seconds": _uptime_seconds(),
        "memory": _memory_summary(),
        "disk": disk,
        "cpu_temperature_c": _cpu_temperature_c(),
        "gpio": _gpio_backend_summary(gpio_backend),
        "endpoint": _endpoint_summary(config),
    }


def _uptime_seconds() -> float | None:
    path = Path("/proc/uptime")
    if not path.exists():
        return None
    try:
        return float(path.read_text(encoding="utf-8").split()[0])
    except Exception:
        return None


def _memory_summary() -> dict[str, int] | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values: dict[str, int] = {}
        try:
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if ":" not in line:
                    continue
                key, raw = line.split(":", 1)
                parts = raw.strip().split()
                if not parts:
                    continue
                values[key.lower() + "_kb"] = int(parts[0])
            return {
                "total_kb": values.get("memtotal_kb", 0),
                "available_kb": values.get("memavailable_kb", 0),
                "free_kb": values.get("memfree_kb", 0),
            }
        except Exception:
            return None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
        return {"total_kb": int(page_size * page_count / 1024), "available_kb": 0, "free_kb": 0}
    except Exception:
        return None


def _disk_summary(path: str) -> dict[str, int] | None:
    try:
        usage = shutil.disk_usage(path)
    except Exception:
        return None
    return {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
    }


def _cpu_temperature_c() -> float | None:
    candidates = [
        Path("/sys/class/thermal/thermal_zone0/temp"),
        Path("/sys/class/hwmon/hwmon0/temp1_input"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8").strip()
            value = float(raw)
            return value / 1000.0 if value > 200 else value
        except Exception:
            continue
    return None


def _gpio_backend_summary(gpio_backend: Any | None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "selected_pin_factory": _select_gpio_pin_factory_name(),
        "backend": None,
        "available": None,
    }
    if gpio_backend is None:
        return summary
    if isinstance(gpio_backend, FakeGPIOBackend):
        summary.update({"backend": "fake", "available": True})
        return summary
    if isinstance(gpio_backend, UnavailableGPIOBackend):
        summary.update(
            {
                "backend": "unavailable",
                "available": False,
                "code": gpio_backend.code,
                "message": gpio_backend.message,
            }
        )
        return summary
    if isinstance(gpio_backend, GpioZeroBackend):
        summary.update(
            {
                "backend": f"gpiozero:{getattr(gpio_backend, '_pin_factory_name', 'unknown')}",
                "available": True,
            }
        )
        return summary
    summary.update({"backend": gpio_backend.__class__.__name__, "available": True})
    return summary


def _endpoint_summary(config: Any | None) -> dict[str, Any]:
    return {
        "version": _package_version(),
        "git_commit": _git_commit(),
        "endpoint_id": getattr(config, "endpoint_id", None),
        "provider_type": getattr(config, "provider_type", None),
        "executor_endpoint_id": getattr(config, "executor_endpoint_id", None),
    }


def _package_version() -> str | None:
    try:
        return metadata.version("meetyou-rpi-endpoint")
    except metadata.PackageNotFoundError:
        return None


def _git_commit() -> str | None:
    repo_root = _repo_root()
    if repo_root is None:
        return None
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    commit = completed.stdout.strip()
    return commit or None


def _repo_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    return None


def build_system_info_capability() -> CapabilityDefinition:
    return CapabilityDefinition(
        name="rpi.system.info",
        description="Raspberry Pi System Info",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "hostname": {"type": "string"},
                "platform": {"type": "object"},
                "python": {"type": "object"},
                "uptime_seconds": {"type": ["number", "null"]},
                "memory": {"type": ["object", "null"]},
                "disk": {"type": ["object", "null"]},
                "cpu_temperature_c": {"type": ["number", "null"]},
                "gpio": {"type": "object"},
                "endpoint": {"type": "object"},
            },
            "required": ["summary", "hostname", "platform", "python"],
        },
        risk_level="read",
        requires_confirmation=False,
        handler=handle_system_info,
        safe_parallel=True,
        tags=("rpi", "system", "read"),
    )
