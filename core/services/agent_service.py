from __future__ import annotations

from datetime import datetime, timezone

from core.db.repositories import AgentCapabilitySnapshotRepository, AgentRepository, WorkspaceRepository
from core.services.base import ServiceBase


class AgentService(ServiceBase):
    def ensure_agent(self, *, agent_id: str, principal_id, agent_type: str, display_name: str, transport_profile: str, owner_client_id=None):
        with self.session_scope() as session:
            repo = AgentRepository(session)
            existing = repo.get_by_agent_id(agent_id)
            if existing is not None:
                return existing
            return repo.create(
                agent_id=agent_id,
                principal_id=principal_id,
                agent_type=agent_type,
                display_name=display_name,
                transport_profile=transport_profile,
                owner_client_id=owner_client_id,
            )

    def bind_workspace(self, *, workspace_id, agent_id, membership_role: str = "member"):
        with self.session_scope() as session:
            return AgentRepository(session).bind_workspace(
                workspace_id=workspace_id,
                agent_id=agent_id,
                membership_role=membership_role,
            )

    def get_by_agent_id(self, agent_id: str):
        with self.session_scope() as session:
            return AgentRepository(session).get_by_agent_id(agent_id)

    def list_agents(self):
        with self.session_scope() as session:
            return AgentRepository(session).list_all()

    def list_workspaces(self, agent_id: str):
        with self.session_scope() as session:
            repo = AgentRepository(session)
            agent = repo.get_by_agent_id(agent_id)
            if agent is None:
                return []
            bindings = repo.get_bindings_for_agent(agent.id)
            rows = []
            workspace_store = WorkspaceRepository(session)
            for binding in bindings:
                workspace = workspace_store.get_by_id(binding.workspace_id)
                if workspace is not None:
                    rows.append(workspace)
            return rows

    def is_bound_to_workspace(self, *, agent_id: str, workspace_id: str) -> bool:
        workspace_ids = {item.workspace_id for item in self.list_workspaces(agent_id)}
        return workspace_id in workspace_ids

    def register_agent(
        self,
        *,
        principal_id,
        agent_id: str,
        agent_type: str,
        display_name: str,
        transport_profile: str,
        workspace_rows: list[object],
        host_name: str = "",
        host_os: str = "",
        host_arch: str = "",
        supports_offline_cache: bool = False,
        meta: dict | None = None,
        owner_client_id=None,
    ):
        with self.session_scope() as session:
            repo = AgentRepository(session)
            agent = repo.get_by_agent_id(agent_id)
            if agent is None:
                agent = repo.create(
                    agent_id=agent_id,
                    principal_id=principal_id,
                    agent_type=agent_type,
                    display_name=display_name,
                    transport_profile=transport_profile,
                    owner_client_id=owner_client_id,
                )
            agent = repo.update_registration(
                agent_id=agent.id,
                agent_type=agent_type,
                display_name=display_name,
                transport_profile=transport_profile,
                owner_client_id=owner_client_id,
                host_name=host_name,
                host_os=host_os,
                host_arch=host_arch,
                supports_offline_cache=supports_offline_cache,
                status="online",
                meta=meta,
            )
            repo.replace_workspace_bindings(
                agent_id=agent.id,
                workspace_ids=[workspace.id for workspace in workspace_rows],
            )
            return agent

    def list_workspace_bindings(self, agent_id: str):
        with self.session_scope() as session:
            repo = AgentRepository(session)
            agent = repo.get_by_agent_id(agent_id)
            if agent is None:
                return []
            return repo.get_bindings_for_agent(agent.id)

    def list_agents_for_workspace(self, workspace_id) -> list[object]:
        with self.session_scope() as session:
            repo = AgentRepository(session)
            agents = repo.list_all()
            result = []
            for agent in agents:
                bindings = repo.get_bindings_for_agent(agent.id)
                if any(binding.enabled and binding.workspace_id == workspace_id for binding in bindings):
                    result.append(agent)
            return result

    def select_workspace_agent(
        self,
        *,
        workspace_id,
        requesting_client_id=None,
        preferred_agent_ids: list[str] | None = None,
        preferred_agent_types: list[str] | None = None,
        routing_policy: str = "balanced",
        allowed_agent_ids: list[str] | None = None,
    ):
        preferred_order = {
            str(agent_id).strip(): index
            for index, agent_id in enumerate(preferred_agent_ids or [])
            if str(agent_id).strip()
        }
        preferred_type_order = {
            str(agent_type).strip(): index
            for index, agent_type in enumerate(preferred_agent_types or [])
            if str(agent_type).strip()
        }
        allowed_set = {
            str(agent_id).strip()
            for agent_id in (allowed_agent_ids or [])
            if str(agent_id).strip()
        }
        candidates = []
        for agent in self.list_agents_for_workspace(workspace_id):
            if getattr(agent, "status", "") != "online":
                continue
            if allowed_set and agent.agent_id not in allowed_set:
                continue
            candidates.append(agent)
        normalized_policy = str(routing_policy or "balanced").strip().lower()
        if normalized_policy not in {"balanced", "prefer_owner_client", "strict_preferred"}:
            normalized_policy = "balanced"
        if normalized_policy == "strict_preferred" and preferred_order:
            candidates = [agent for agent in candidates if agent.agent_id in preferred_order]

        def _balanced_key(agent):
            return (
                0 if agent.agent_id in preferred_order else 1,
                preferred_order.get(agent.agent_id, 10_000),
                0 if getattr(agent, "agent_type", "") in preferred_type_order else 1,
                preferred_type_order.get(getattr(agent, "agent_type", ""), 10_000),
                0 if getattr(agent, "owner_client_id", None) == requesting_client_id else 1,
                agent.agent_id,
            )

        def _owner_first_key(agent):
            return (
                0 if getattr(agent, "owner_client_id", None) == requesting_client_id else 1,
                0 if agent.agent_id in preferred_order else 1,
                preferred_order.get(agent.agent_id, 10_000),
                0 if getattr(agent, "agent_type", "") in preferred_type_order else 1,
                preferred_type_order.get(getattr(agent, "agent_type", ""), 10_000),
                agent.agent_id,
            )

        candidates.sort(key=_owner_first_key if normalized_policy == "prefer_owner_client" else _balanced_key)
        return candidates[0] if candidates else None

    def record_heartbeat(self, *, agent_id: str, status: str, metrics: dict | None = None):
        with self.session_scope() as session:
            return AgentRepository(session).record_heartbeat(agent_id=agent_id, status=status, metrics=metrics)

    def store_capability_snapshot(self, *, agent, revision: int, status: str, snapshot: dict):
        with self.session_scope() as session:
            return AgentCapabilitySnapshotRepository(session).create(
                agent_id=agent.id,
                revision=revision,
                status=status,
                snapshot=snapshot,
                received_at=datetime.now(timezone.utc),
            )
