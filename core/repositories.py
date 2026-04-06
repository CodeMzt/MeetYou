from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RepositoryVersion:
    schema_version: str
    revision: int
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": str(self.schema_version),
            "revision": int(self.revision),
            "updated_at": str(self.updated_at or ""),
        }


@dataclass(slots=True)
class ConfigTransactionSnapshot:
    config: dict[str, Any]
    metadata: dict[str, Any]
    env_text: str
    env_values: dict[str, str | None] = field(default_factory=dict)


class ConfigRepository(ABC):
    @abstractmethod
    def get(self, key: str, default=None):
        raise NotImplementedError

    @abstractmethod
    def get_bool(self, key: str, default: bool = False) -> bool:
        raise NotImplementedError

    @abstractmethod
    def describe_key(self, key: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def snapshot(self) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def reload(self):
        raise NotImplementedError

    @abstractmethod
    def begin_transaction(self) -> ConfigTransactionSnapshot:
        raise NotImplementedError

    @abstractmethod
    def rollback_transaction(self, snapshot: ConfigTransactionSnapshot) -> None:
        raise NotImplementedError

    @abstractmethod
    def apply_updates(self, updates: dict[str, Any]) -> tuple[list[str], list[str]]:
        raise NotImplementedError

    @abstractmethod
    def get_mcp_servers(self) -> dict[str, Any]:
        raise NotImplementedError


class MemoryRepository(ABC):
    @abstractmethod
    async def init_memory(self, config) -> None:
        raise NotImplementedError

    @abstractmethod
    def refresh_config(self, config) -> None:
        raise NotImplementedError

    @abstractmethod
    async def save_memory_graph(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_memory_snapshot(
        self,
        source_id: str = "",
        session_id: str = "",
        include_invalidated: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_memory_graph_view(
        self,
        source_id: str = "",
        session_id: str = "",
        include_invalidated: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError


class TaskRepository(ABC):
    @abstractmethod
    def build_background_status(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_task_by_key(self, task_key: str) -> dict[str, Any] | None:
        raise NotImplementedError
