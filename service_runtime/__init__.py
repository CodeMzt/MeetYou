from service_runtime.boundaries import RuntimeModuleBoundary, RuntimeModuleSet, build_default_runtime_boundaries
from service_runtime.models import RuntimeCommand, RuntimeError, RuntimeEvent, RuntimeHealth

__all__ = [
    "RuntimeModuleBoundary",
    "RuntimeModuleSet",
    "build_default_runtime_boundaries",
    "RuntimeCommand",
    "RuntimeError",
    "RuntimeEvent",
    "RuntimeHealth",
    "ServiceRuntime",
]


def __getattr__(name: str):
    if name == "ServiceRuntime":
        from service_runtime.service import ServiceRuntime

        return ServiceRuntime
    raise AttributeError(name)
