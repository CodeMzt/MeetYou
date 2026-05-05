from __future__ import annotations

from typing import Any

from core.public_contract import normalize_execution_target, to_public_assistant_mode

from core.db.repositories import WorkspaceRepository
from core.services.base import ServiceBase


class WorkspaceService(ServiceBase):
    @staticmethod
    def _normalize_memory_ranking_policy(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"workspace_first"}:
            return "workspace_first"
        return normalized

    @staticmethod
    def _normalize_routing_policy(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"balanced", "prefer_origin_endpoint", "strict_preferred_endpoint"}:
            return "balanced"
        return normalized

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized = str(item or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    @classmethod
    def normalize_governance_metadata(cls, metadata: dict | None = None) -> dict:
        raw = dict(metadata or {})
        allowed_tool_ids = cls._normalize_string_list(raw.get("allowed_tool_ids"))
        preferred_target_endpoint_ids = cls._normalize_string_list(raw.get("preferred_target_endpoint_ids"))
        preferred_endpoint_provider_types = cls._normalize_string_list(raw.get("preferred_endpoint_provider_types"))
        preferred_source_profiles = cls._normalize_string_list(raw.get("preferred_source_profiles"))
        tool_routing_overrides = cls._normalize_tool_routing_overrides(raw.get("tool_routing_overrides"))
        tool_policy = str(raw.get("tool_policy") or "").strip().lower()
        if tool_policy not in {"allow_all", "allowlist"}:
            tool_policy = "allowlist" if allowed_tool_ids else "allow_all"
        tool_target_routing_policy = cls._normalize_routing_policy(raw.get("tool_target_routing_policy"))
        memory_ranking_policy = cls._normalize_memory_ranking_policy(raw.get("memory_ranking_policy"))
        return {
            **{
                key: value
                for key, value in raw.items()
                if key not in {
                    "tool_policy",
                    "allowed_tool_ids",
                    "preferred_target_endpoint_ids",
                    "preferred_endpoint_provider_types",
                    "preferred_source_profiles",
                    "tool_target_routing_policy",
                    "memory_ranking_policy",
                    "tool_routing_overrides",
                }
            },
            "tool_policy": tool_policy,
            "allowed_tool_ids": allowed_tool_ids,
            "preferred_target_endpoint_ids": preferred_target_endpoint_ids,
            "preferred_endpoint_provider_types": preferred_endpoint_provider_types,
            "preferred_source_profiles": preferred_source_profiles,
            "tool_target_routing_policy": tool_target_routing_policy,
            "memory_ranking_policy": memory_ranking_policy,
            "tool_routing_overrides": tool_routing_overrides,
        }

    @classmethod
    def _normalize_tool_routing_overrides(cls, value: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for raw_key, raw_override in value.items():
            tool_key = str(raw_key or "").strip()
            if not tool_key or not isinstance(raw_override, dict):
                continue
            result[tool_key] = {
                "preferred_target_endpoint_ids": cls._normalize_string_list(raw_override.get("preferred_target_endpoint_ids")),
                "preferred_endpoint_provider_types": cls._normalize_string_list(raw_override.get("preferred_endpoint_provider_types")),
                "tool_target_routing_policy": cls._normalize_routing_policy(raw_override.get("tool_target_routing_policy")),
            }
        return result

    @classmethod
    def get_governance_view(cls, workspace) -> dict[str, Any]:
        normalized_meta = cls.normalize_governance_metadata(getattr(workspace, "meta", {}) or {})
        return {
            "description": str(getattr(workspace, "description", "") or ""),
            "prompt_overlay": str(getattr(workspace, "prompt_overlay", "") or ""),
            "default_execution_target": normalize_execution_target(
                getattr(workspace, "default_execution_target", "core.local"),
            ),
            "tool_policy": str(normalized_meta.get("tool_policy") or "allow_all"),
            "allowed_tool_ids": list(normalized_meta.get("allowed_tool_ids") or []),
            "preferred_target_endpoint_ids": list(normalized_meta.get("preferred_target_endpoint_ids") or []),
            "preferred_endpoint_provider_types": list(normalized_meta.get("preferred_endpoint_provider_types") or []),
            "preferred_source_profiles": list(normalized_meta.get("preferred_source_profiles") or []),
            "tool_target_routing_policy": str(normalized_meta.get("tool_target_routing_policy") or "balanced"),
            "memory_ranking_policy": str(normalized_meta.get("memory_ranking_policy") or "workspace_first"),
            "tool_routing_overrides": dict(normalized_meta.get("tool_routing_overrides") or {}),
        }

    @classmethod
    def get_effective_tool_target_preferences(
        cls,
        workspace,
        *,
        tool_key: str = "",
        abstract_tool_key: str = "",
        concrete_tool_id: str = "",
    ) -> dict[str, Any]:
        governance = cls.get_governance_view(workspace)
        overrides = dict(governance.get("tool_routing_overrides") or {})
        for key in [
            str(tool_key or "").strip(),
            str(abstract_tool_key or "").strip(),
            str(concrete_tool_id or "").strip(),
        ]:
            if not key:
                continue
            override = overrides.get(key)
            if not isinstance(override, dict):
                continue
            return {
                "preferred_target_endpoint_ids": list(override.get("preferred_target_endpoint_ids") or governance.get("preferred_target_endpoint_ids") or []),
                "preferred_endpoint_provider_types": list(override.get("preferred_endpoint_provider_types") or governance.get("preferred_endpoint_provider_types") or []),
                "tool_target_routing_policy": str(override.get("tool_target_routing_policy") or governance.get("tool_target_routing_policy") or "balanced"),
                "source": key,
            }
        return {
            "preferred_target_endpoint_ids": list(governance.get("preferred_target_endpoint_ids") or []),
            "preferred_endpoint_provider_types": list(governance.get("preferred_endpoint_provider_types") or []),
            "tool_target_routing_policy": str(governance.get("tool_target_routing_policy") or "balanced"),
            "source": "workspace_default",
        }

    @classmethod
    def tool_allowed(cls, workspace, tool_id: str) -> bool:
        normalized_tool_id = str(tool_id or "").strip()
        if not normalized_tool_id:
            return True
        governance = cls.get_governance_view(workspace)
        if governance["tool_policy"] != "allowlist":
            return True
        return normalized_tool_id in set(governance["allowed_tool_ids"])

    def ensure_workspace(
        self,
        *,
        workspace_id: str,
        principal_id,
        title: str,
        description: str = "",
        base_mode: str = "general",
        prompt_overlay: str = "",
        default_execution_target: str = "core.local",
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            repo = WorkspaceRepository(session)
            existing = repo.get_by_workspace_id(workspace_id)
            if existing is not None:
                updated = False
                normalized_mode = to_public_assistant_mode(base_mode)
                normalized_prompt = str(prompt_overlay or "").strip()
                normalized_execution_target = normalize_execution_target(default_execution_target)
                normalized_description = str(description or "").strip()
                if normalized_description and str(existing.description or "") != normalized_description:
                    existing.description = normalized_description
                    updated = True
                if normalized_mode and str(existing.base_mode or "") != normalized_mode:
                    existing.base_mode = normalized_mode
                    updated = True
                if normalized_prompt and str(existing.prompt_overlay or "") != normalized_prompt:
                    existing.prompt_overlay = normalized_prompt
                    updated = True
                if normalized_execution_target and str(existing.default_execution_target or "") != normalized_execution_target:
                    existing.default_execution_target = normalized_execution_target
                    updated = True
                if metadata:
                    merged = dict(existing.meta or {})
                    merged.update(dict(metadata))
                    existing.meta = self.normalize_governance_metadata(merged)
                    updated = True
                if updated:
                    session.flush()
                return existing
            return repo.create(
                workspace_id=workspace_id,
                principal_id=principal_id,
                title=title,
                description=str(description or "").strip(),
                base_mode=to_public_assistant_mode(base_mode),
                prompt_overlay=str(prompt_overlay or "").strip(),
                default_execution_target=normalize_execution_target(default_execution_target),
                metadata=self.normalize_governance_metadata(metadata),
            )

    def update_workspace(
        self,
        *,
        workspace_id: str,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        base_mode: str | None = None,
        prompt_overlay: str | None = None,
        default_execution_target: str | None = None,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return WorkspaceRepository(session).update_profile(
                workspace_id=workspace_id,
                title=str(title or "").strip() if title is not None else None,
                description=str(description or "").strip() if description is not None else None,
                status=str(status or "").strip() if status is not None else None,
                base_mode=to_public_assistant_mode(base_mode) if base_mode is not None else None,
                prompt_overlay=str(prompt_overlay or "").strip() if prompt_overlay is not None else None,
                default_execution_target=normalize_execution_target(default_execution_target)
                if default_execution_target is not None
                else None,
                metadata=self.normalize_governance_metadata(metadata) if metadata is not None else None,
            )

    def archive_workspace(self, *, workspace_id: str):
        normalized = str(workspace_id or "").strip()
        if normalized == "personal":
            raise ValueError("personal workspace cannot be archived.")
        with self.session_scope() as session:
            repo = WorkspaceRepository(session)
            workspace = repo.get_by_workspace_id(normalized)
            if workspace is None:
                return None
            workspace.status = "archived"
            session.flush()
            return workspace

    def restore_workspace(self, *, workspace_id: str):
        with self.session_scope() as session:
            repo = WorkspaceRepository(session)
            workspace = repo.get_by_workspace_id(str(workspace_id or "").strip())
            if workspace is None:
                return None
            workspace.status = "active"
            session.flush()
            return workspace

    def get_by_workspace_id(self, workspace_id: str):
        with self.session_scope() as session:
            return WorkspaceRepository(session).get_by_workspace_id(workspace_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return WorkspaceRepository(session).get_by_id(row_id)

    def list_workspaces(self, *, include_archived: bool = False):
        with self.session_scope() as session:
            return WorkspaceRepository(session).list_all(include_archived=include_archived)
