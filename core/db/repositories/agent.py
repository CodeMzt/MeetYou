from __future__ import annotations

from datetime import datetime, timezone

from core.db.models.agent import Agent, WorkspaceAgentMembership
from core.db.repositories.base import RepositoryBase


class AgentRepository(RepositoryBase):
    def create(self, *, agent_id: str, principal_id, agent_type: str, display_name: str, transport_profile: str, owner_client_id=None) -> Agent:
        agent = Agent(
            agent_id=agent_id,
            principal_id=principal_id,
            owner_client_id=owner_client_id,
            agent_type=agent_type,
            display_name=display_name,
            transport_profile=transport_profile,
        )
        self.session.add(agent)
        self.session.flush()
        return agent

    def bind_workspace(self, *, workspace_id, agent_id, membership_role: str = "member") -> WorkspaceAgentMembership:
        membership = WorkspaceAgentMembership(
            workspace_id=workspace_id,
            agent_id=agent_id,
            membership_role=membership_role,
        )
        self.session.add(membership)
        self.session.flush()
        return membership

    def get_by_agent_id(self, agent_id: str) -> Agent | None:
        return self.session.query(Agent).filter_by(agent_id=agent_id).one_or_none()

    def list_all(self) -> list[Agent]:
        return list(self.session.query(Agent).order_by(Agent.agent_id).all())

    def get_bindings_for_agent(self, agent_id) -> list[WorkspaceAgentMembership]:
        return list(self.session.query(WorkspaceAgentMembership).filter_by(agent_id=agent_id).all())

    def replace_workspace_bindings(self, *, agent_id, workspace_ids: list, membership_role: str = "member") -> list[WorkspaceAgentMembership]:
        self.session.query(WorkspaceAgentMembership).filter_by(agent_id=agent_id).delete()
        self.session.flush()
        created: list[WorkspaceAgentMembership] = []
        for workspace_id in workspace_ids:
            created.append(
                self.bind_workspace(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    membership_role=membership_role,
                )
            )
        return created

    def update_registration(
        self,
        *,
        agent_id,
        agent_type: str,
        display_name: str,
        transport_profile: str,
        host_name: str = "",
        host_os: str = "",
        host_arch: str = "",
        supports_offline_cache: bool = False,
        status: str = "online",
        meta: dict | None = None,
        owner_client_id=None,
    ) -> Agent:
        agent = self.session.query(Agent).filter_by(id=agent_id).one()
        agent.agent_type = agent_type
        agent.display_name = display_name
        agent.transport_profile = transport_profile
        agent.owner_client_id = owner_client_id
        agent.host_name = host_name
        agent.host_os = host_os
        agent.host_arch = host_arch
        agent.supports_offline_cache = supports_offline_cache
        agent.status = status
        agent.last_seen_at = datetime.now(timezone.utc)
        merged_meta = dict(agent.meta or {})
        merged_meta.update(dict(meta or {}))
        agent.meta = merged_meta
        self.session.flush()
        return agent

    def record_heartbeat(self, *, agent_id, status: str, metrics: dict | None = None) -> Agent | None:
        agent = self.get_by_agent_id(agent_id)
        if agent is None:
            return None
        agent.status = status
        agent.last_seen_at = datetime.now(timezone.utc)
        merged_meta = dict(agent.meta or {})
        merged_meta["last_metrics"] = dict(metrics or {})
        agent.meta = merged_meta
        self.session.flush()
        return agent
