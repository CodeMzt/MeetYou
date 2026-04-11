from __future__ import annotations

from core.db.models.capability import Capability, CapabilityWorkspaceBinding
from core.db.repositories.base import RepositoryBase


class CapabilityRepository(RepositoryBase):
    def get_by_capability_id(self, capability_id: str) -> Capability | None:
        return self.session.query(Capability).filter_by(capability_id=capability_id).one_or_none()

    def list_all(self) -> list[Capability]:
        return self.session.query(Capability).all()

    def list_for_workspace(self, *, workspace_id) -> list[Capability]:
        return (
            self.session.query(Capability)
            .join(CapabilityWorkspaceBinding, CapabilityWorkspaceBinding.capability_id == Capability.id)
            .filter(CapabilityWorkspaceBinding.workspace_id == workspace_id, CapabilityWorkspaceBinding.enabled.is_(True))
            .all()
        )

    def has_workspace_binding(self, *, capability_id, workspace_id) -> bool:
        return (
            self.session.query(CapabilityWorkspaceBinding)
            .filter_by(capability_id=capability_id, workspace_id=workspace_id, enabled=True)
            .count()
            > 0
        )

    def upsert(
        self,
        *,
        capability_id: str,
        provider_type: str,
        provider_ref: str,
        kind: str,
        title: str,
        risk_level: str,
        requires_confirmation: bool,
        availability: str,
        input_schema: dict | None = None,
        output_schema: dict | None = None,
        meta: dict | None = None,
    ) -> Capability:
        capability = self.get_by_capability_id(capability_id)
        if capability is None:
            capability = Capability(capability_id=capability_id)
            self.session.add(capability)
        capability.provider_type = provider_type
        capability.provider_ref = provider_ref
        capability.kind = kind
        capability.title = title
        capability.risk_level = risk_level
        capability.requires_confirmation = requires_confirmation
        capability.availability = availability
        capability.input_schema = dict(input_schema or {})
        capability.output_schema = dict(output_schema or {})
        capability.meta = dict(meta or {})
        self.session.flush()
        return capability

    def clear_workspace_bindings(self, *, capability_id) -> None:
        self.session.query(CapabilityWorkspaceBinding).filter_by(capability_id=capability_id).delete()
        self.session.flush()

    def add_workspace_binding(self, *, capability_id, workspace_id, enabled: bool = True, priority: int = 100) -> CapabilityWorkspaceBinding:
        binding = CapabilityWorkspaceBinding(
            capability_id=capability_id,
            workspace_id=workspace_id,
            enabled=enabled,
            priority=priority,
        )
        self.session.add(binding)
        self.session.flush()
        return binding
