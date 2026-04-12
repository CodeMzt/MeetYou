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
        if normalized not in {"balanced", "prefer_owner_client", "strict_preferred"}:
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
        allowed_capability_ids = cls._normalize_string_list(raw.get("allowed_capability_ids"))
        preferred_agent_ids = cls._normalize_string_list(raw.get("preferred_agent_ids"))
        preferred_agent_types = cls._normalize_string_list(raw.get("preferred_agent_types"))
        preferred_source_profiles = cls._normalize_string_list(raw.get("preferred_source_profiles"))
        capability_routing_overrides = cls._normalize_capability_routing_overrides(raw.get("capability_routing_overrides"))
        capability_policy = str(raw.get("capability_policy") or "").strip().lower()
        if capability_policy not in {"allow_all", "allowlist"}:
            capability_policy = "allowlist" if allowed_capability_ids else "allow_all"
        agent_routing_policy = cls._normalize_routing_policy(raw.get("agent_routing_policy"))
        memory_ranking_policy = cls._normalize_memory_ranking_policy(raw.get("memory_ranking_policy"))
        return {
            **{
                key: value
                for key, value in raw.items()
                if key not in {
                    "capability_policy",
                    "allowed_capability_ids",
                    "preferred_agent_ids",
                    "preferred_agent_types",
                    "preferred_source_profiles",
                    "agent_routing_policy",
                    "memory_ranking_policy",
                    "capability_routing_overrides",
                }
            },
            "capability_policy": capability_policy,
            "allowed_capability_ids": allowed_capability_ids,
            "preferred_agent_ids": preferred_agent_ids,
            "preferred_agent_types": preferred_agent_types,
            "preferred_source_profiles": preferred_source_profiles,
            "agent_routing_policy": agent_routing_policy,
            "memory_ranking_policy": memory_ranking_policy,
            "capability_routing_overrides": capability_routing_overrides,
        }

    @classmethod
    def _normalize_capability_routing_overrides(cls, value: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for raw_key, raw_override in value.items():
            capability_key = str(raw_key or "").strip()
            if not capability_key or not isinstance(raw_override, dict):
                continue
            result[capability_key] = {
                "preferred_agent_ids": cls._normalize_string_list(raw_override.get("preferred_agent_ids")),
                "preferred_agent_types": cls._normalize_string_list(raw_override.get("preferred_agent_types")),
                "agent_routing_policy": cls._normalize_routing_policy(raw_override.get("agent_routing_policy")),
            }
        return result

    @classmethod
    def get_governance_view(cls, workspace) -> dict[str, Any]:
        normalized_meta = cls.normalize_governance_metadata(getattr(workspace, "meta", {}) or {})
        return {
            "description": str(getattr(workspace, "description", "") or ""),
            "prompt_overlay": str(getattr(workspace, "prompt_overlay", "") or ""),
            "default_execution_target": normalize_execution_target(
                getattr(workspace, "default_execution_target", "core_only"),
            ),
            "capability_policy": str(normalized_meta.get("capability_policy") or "allow_all"),
            "allowed_capability_ids": list(normalized_meta.get("allowed_capability_ids") or []),
            "preferred_agent_ids": list(normalized_meta.get("preferred_agent_ids") or []),
            "preferred_agent_types": list(normalized_meta.get("preferred_agent_types") or []),
            "preferred_source_profiles": list(normalized_meta.get("preferred_source_profiles") or []),
            "agent_routing_policy": str(normalized_meta.get("agent_routing_policy") or "balanced"),
            "memory_ranking_policy": str(normalized_meta.get("memory_ranking_policy") or "workspace_first"),
            "capability_routing_overrides": dict(normalized_meta.get("capability_routing_overrides") or {}),
        }

    @classmethod
    def get_effective_agent_routing_preferences(
        cls,
        workspace,
        *,
        capability_ref: str = "",
        abstract_capability_key: str = "",
        concrete_capability_id: str = "",
    ) -> dict[str, Any]:
        governance = cls.get_governance_view(workspace)
        overrides = dict(governance.get("capability_routing_overrides") or {})
        for key in [str(capability_ref or "").strip(), str(abstract_capability_key or "").strip(), str(concrete_capability_id or "").strip()]:
            if not key:
                continue
            override = overrides.get(key)
            if not isinstance(override, dict):
                continue
            return {
                "preferred_agent_ids": list(override.get("preferred_agent_ids") or governance.get("preferred_agent_ids") or []),
                "preferred_agent_types": list(override.get("preferred_agent_types") or governance.get("preferred_agent_types") or []),
                "agent_routing_policy": str(override.get("agent_routing_policy") or governance.get("agent_routing_policy") or "balanced"),
                "source": key,
            }
        return {
            "preferred_agent_ids": list(governance.get("preferred_agent_ids") or []),
            "preferred_agent_types": list(governance.get("preferred_agent_types") or []),
            "agent_routing_policy": str(governance.get("agent_routing_policy") or "balanced"),
            "source": "workspace_default",
        }

    @classmethod
    def capability_allowed(cls, workspace, capability_id: str) -> bool:
        normalized_capability_id = str(capability_id or "").strip()
        if not normalized_capability_id:
            return True
        governance = cls.get_governance_view(workspace)
        if governance["capability_policy"] != "allowlist":
            return True
        return normalized_capability_id in set(governance["allowed_capability_ids"])

    def ensure_workspace(
        self,
        *,
        workspace_id: str,
        principal_id,
        title: str,
        description: str = "",
        base_mode: str = "general",
        prompt_overlay: str = "",
        default_execution_target: str = "core_only",
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
                base_mode=to_public_assistant_mode(base_mode) if base_mode is not None else None,
                prompt_overlay=str(prompt_overlay or "").strip() if prompt_overlay is not None else None,
                default_execution_target=normalize_execution_target(default_execution_target)
                if default_execution_target is not None
                else None,
                metadata=self.normalize_governance_metadata(metadata) if metadata is not None else None,
            )

    def get_by_workspace_id(self, workspace_id: str):
        with self.session_scope() as session:
            return WorkspaceRepository(session).get_by_workspace_id(workspace_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return WorkspaceRepository(session).get_by_id(row_id)

    def list_workspaces(self):
        with self.session_scope() as session:
            return WorkspaceRepository(session).list_all()
