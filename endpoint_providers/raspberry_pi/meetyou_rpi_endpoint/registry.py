from __future__ import annotations

from typing import Any

from .capabilities.base import (
    CapabilityContext,
    CapabilityDefinition,
    CapabilityError,
)
from .capabilities.echo import build_echo_capability
from .capabilities.gpio import (
    build_gpio_backend,
    build_gpio_read_capability,
    build_gpio_write_capability,
)
from .capabilities.safe_shell import (
    build_safe_shell_capability,
)
from .capabilities.system_info import (
    build_system_info_capability,
)
from .security import normalize_safe_shell_allowlist


class CapabilityRegistry:
    def __init__(self, context: CapabilityContext):
        self.context = context
        self._capabilities: dict[str, CapabilityDefinition] = {}

    def register(self, definition: CapabilityDefinition) -> None:
        if not definition.name:
            raise ValueError("Capability name is required")
        self._capabilities[definition.name] = definition

    def get(self, name: str) -> CapabilityDefinition | None:
        return self._capabilities.get(str(name or "").strip())

    def names(self) -> list[str]:
        return sorted(self._capabilities)

    def definitions(self) -> list[CapabilityDefinition]:
        return [self._capabilities[name] for name in self.names()]

    def tool_definitions(self) -> list[dict[str, Any]]:
        return [
            definition.to_tool_definition(
                endpoint_id=self.context.config.executor_endpoint_id,
                workspace_ids=self.context.config.workspace_ids,
                max_concurrency=self.context.config.max_parallel_calls if definition.safe_parallel else 1,
            )
            for definition in self.definitions()
        ]

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        definition = self.get(name)
        if definition is None:
            raise CapabilityError("capability_not_found", f"Capability is not registered: {name}")
        return await definition.handler(dict(arguments or {}), self.context)


def build_default_registry(config, *, gpio_backend=None, force_fake_gpio: bool = False) -> CapabilityRegistry:
    backend = (
        gpio_backend
        if gpio_backend is not None
        else build_gpio_backend(
            force_fake=force_fake_gpio,
            working_dir=getattr(getattr(config, "security", None), "sandbox_dir", ""),
        )
    )
    registry = CapabilityRegistry(CapabilityContext(config=config, gpio_backend=backend))
    registry.register(build_echo_capability())
    registry.register(build_system_info_capability())
    registry.register(build_gpio_read_capability())
    registry.register(build_gpio_write_capability())
    allowlist = normalize_safe_shell_allowlist(config.security.safe_shell_allowlist)
    if config.security.safe_shell_enabled and allowlist:
        registry.register(build_safe_shell_capability())
    return registry
