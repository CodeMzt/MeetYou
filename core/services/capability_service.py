from __future__ import annotations

from typing import Any

from core.db.repositories import CapabilityRepository
from core.services.base import ServiceBase


class CapabilityService(ServiceBase):
    @staticmethod
    def get_abstract_capability_key(capability) -> str:
        if capability is None:
            return ""
        meta = dict(getattr(capability, "meta", {}) or {})
        return str(meta.get("abstract_capability_key") or getattr(capability, "capability_id", "") or "").strip()

    def get_by_capability_id(self, capability_id: str):
        with self.session_scope() as session:
            return CapabilityRepository(session).get_by_capability_id(capability_id)

    def list_for_workspace(self, *, workspace_id) -> list[object]:
        with self.session_scope() as session:
            return CapabilityRepository(session).list_for_workspace(workspace_id=workspace_id)

    def resolve_capability_reference(self, *, capability_ref: str, workspace_id, target_agent_id: str | None = None):
        normalized_ref = str(capability_ref or "").strip()
        if not normalized_ref:
            return None
        with self.session_scope() as session:
            repo = CapabilityRepository(session)
            exact = repo.get_by_capability_id(normalized_ref)
            if exact is not None and repo.has_workspace_binding(capability_id=exact.id, workspace_id=workspace_id):
                if target_agent_id and str(getattr(exact, "provider_ref", "") or "") != str(target_agent_id or ""):
                    pass
                else:
                    return exact
            for capability in repo.list_for_workspace(workspace_id=workspace_id):
                if target_agent_id and str(getattr(capability, "provider_ref", "") or "") != str(target_agent_id or ""):
                    continue
                if self.get_abstract_capability_key(capability) == normalized_ref:
                    return capability
            return None

    def list_agents_for_capability_reference(self, *, capability_ref: str, workspace_id) -> list[str]:
        normalized_ref = str(capability_ref or "").strip()
        if not normalized_ref:
            return []
        result: list[str] = []
        seen: set[str] = set()
        for capability in self.list_for_workspace(workspace_id=workspace_id):
            provider_ref = str(getattr(capability, "provider_ref", "") or "").strip()
            if not provider_ref or provider_ref in seen:
                continue
            if str(getattr(capability, "capability_id", "") or "") == normalized_ref or self.get_abstract_capability_key(capability) == normalized_ref:
                seen.add(provider_ref)
                result.append(provider_ref)
        return result

    def is_available_in_workspace(self, *, capability_id: str, workspace_id) -> bool:
        with self.session_scope() as session:
            repo = CapabilityRepository(session)
            capability = repo.get_by_capability_id(capability_id)
            if capability is None:
                return False
            return repo.has_workspace_binding(capability_id=capability.id, workspace_id=workspace_id)

    def replace_agent_capabilities(self, *, agent, capabilities: list[dict], workspace_rows: list[object], revision: int) -> int:
        with self.session_scope() as session:
            repo = CapabilityRepository(session)
            count = 0
            workspace_ids_by_key = {getattr(workspace, "workspace_id", ""): getattr(workspace, "id", None) for workspace in workspace_rows}
            for item in capabilities:
                capability_key = str(item.get("capability_id") or "").strip()
                if not capability_key:
                    continue
                capability = repo.upsert(
                    capability_id=capability_key,
                    provider_type="agent",
                    provider_ref=agent.agent_id,
                    kind=str(item.get("kind") or "tool"),
                    title=str(item.get("title") or item.get("capability_id") or ""),
                    risk_level=str(item.get("risk_level") or "read"),
                    requires_confirmation=bool(item.get("requires_confirmation", False)),
                    availability="online",
                    input_schema=item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {},
                    output_schema=item.get("output_schema") if isinstance(item.get("output_schema"), dict) else {},
                    meta={
                        "revision": revision,
                        **({"tags": item.get("tags")} if item.get("tags") else {}),
                        **(
                            {"abstract_capability_key": str(item.get("abstract_capability_key") or "").strip()}
                            if str(item.get("abstract_capability_key") or "").strip()
                            else {}
                        ),
                    },
                )
                repo.clear_workspace_bindings(capability_id=capability.id)
                for workspace_key in [str(value) for value in item.get("workspace_ids", []) if str(value).strip()]:
                    workspace_id = workspace_ids_by_key.get(workspace_key)
                    if workspace_id is not None:
                        repo.add_workspace_binding(capability_id=capability.id, workspace_id=workspace_id)
                count += 1
            return count
