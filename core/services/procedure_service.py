from __future__ import annotations

from typing import Any

from core.db.repositories import ProcedureRepository
from core.services.base import ServiceBase


class ProcedureService(ServiceBase):
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

    @staticmethod
    def _normalize_routing_policy(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"balanced", "prefer_owner_client", "strict_preferred"}:
            return "balanced"
        return normalized

    @classmethod
    def normalize_meta(cls, meta: dict | None = None) -> dict:
        raw = dict(meta or {})
        preferred_capability_ref = str(raw.get("preferred_capability_ref") or "").strip()
        preferred_agent_ids = cls._normalize_string_list(raw.get("preferred_agent_ids"))
        preferred_agent_types = cls._normalize_string_list(raw.get("preferred_agent_types"))
        agent_routing_policy = cls._normalize_routing_policy(raw.get("agent_routing_policy"))
        return {
            **{
                key: value
                for key, value in raw.items()
                if key not in {"preferred_capability_ref", "preferred_agent_ids", "preferred_agent_types", "agent_routing_policy"}
            },
            "preferred_capability_ref": preferred_capability_ref,
            "preferred_agent_ids": preferred_agent_ids,
            "preferred_agent_types": preferred_agent_types,
            "agent_routing_policy": agent_routing_policy,
        }

    @classmethod
    def get_routing_view(cls, procedure) -> dict[str, Any]:
        meta = cls.normalize_meta(getattr(procedure, "meta", {}) or {})
        recommended_capabilities = cls._normalize_string_list(getattr(procedure, "recommended_capabilities", []) or [])
        preferred_capability_ref = str(meta.get("preferred_capability_ref") or "").strip() or (recommended_capabilities[0] if recommended_capabilities else "")
        return {
            "recommended_capabilities": recommended_capabilities,
            "preferred_capability_ref": preferred_capability_ref,
            "preferred_agent_ids": list(meta.get("preferred_agent_ids") or []),
            "preferred_agent_types": list(meta.get("preferred_agent_types") or []),
            "agent_routing_policy": str(meta.get("agent_routing_policy") or "balanced"),
        }

    def ensure_procedure(
        self,
        *,
        procedure_id: str,
        principal_id,
        title: str = "",
        description: str = "",
        prompt_overlay: str = "",
        default_execution_target: str = "",
        risk_profile: str = "standard",
        status: str = "active",
        applicable_modes: list[str] | None = None,
        recommended_capabilities: list[str] | None = None,
        recommended_source_profiles: list[str] | None = None,
        meta: dict | None = None,
    ):
        with self.session_scope() as session:
            repo = ProcedureRepository(session)
            existing = repo.get_by_procedure_id(procedure_id)
            if existing is not None:
                updated = False
                normalized_meta = self.normalize_meta(meta)
                if title and existing.title != title:
                    existing.title = title
                    updated = True
                if description and existing.description != description:
                    existing.description = description
                    updated = True
                if prompt_overlay and existing.prompt_overlay != prompt_overlay:
                    existing.prompt_overlay = prompt_overlay
                    updated = True
                if default_execution_target and existing.default_execution_target != default_execution_target:
                    existing.default_execution_target = default_execution_target
                    updated = True
                if risk_profile and existing.risk_profile != risk_profile:
                    existing.risk_profile = risk_profile
                    updated = True
                if status and existing.status != status:
                    existing.status = status
                    updated = True
                if applicable_modes and list(existing.applicable_modes or []) != list(applicable_modes):
                    existing.applicable_modes = list(applicable_modes)
                    updated = True
                if recommended_capabilities and list(existing.recommended_capabilities or []) != list(recommended_capabilities):
                    existing.recommended_capabilities = list(recommended_capabilities)
                    updated = True
                if recommended_source_profiles and list(existing.recommended_source_profiles or []) != list(recommended_source_profiles):
                    existing.recommended_source_profiles = list(recommended_source_profiles)
                    updated = True
                if normalized_meta and dict(existing.meta or {}) != normalized_meta:
                    existing.meta = normalized_meta
                    updated = True
                if updated:
                    session.flush()
                return existing
            return repo.create(
                procedure_id=procedure_id,
                principal_id=principal_id,
                title=title,
                description=description,
                prompt_overlay=prompt_overlay,
                default_execution_target=default_execution_target,
                risk_profile=risk_profile,
                status=status,
                applicable_modes=applicable_modes,
                recommended_capabilities=recommended_capabilities,
                recommended_source_profiles=recommended_source_profiles,
                meta=self.normalize_meta(meta),
            )

    def get_by_procedure_id(self, procedure_id: str):
        with self.session_scope() as session:
            return ProcedureRepository(session).get_by_procedure_id(procedure_id)

    def list_active(self, *, principal_id):
        with self.session_scope() as session:
            return ProcedureRepository(session).list_active(principal_id)
