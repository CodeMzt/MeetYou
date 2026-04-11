from __future__ import annotations

from core.db.models.workspace import Workspace
from core.db.repositories.base import RepositoryBase


class WorkspaceRepository(RepositoryBase):
    def create(
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
    ) -> Workspace:
        workspace = Workspace(
            workspace_id=workspace_id,
            principal_id=principal_id,
            title=title,
            description=description,
            base_mode=base_mode,
            prompt_overlay=prompt_overlay,
            default_execution_target=default_execution_target,
            meta=dict(metadata or {}),
        )
        self.session.add(workspace)
        self.session.flush()
        return workspace

    def update_profile(
        self,
        *,
        workspace_id: str,
        title: str | None = None,
        description: str | None = None,
        base_mode: str | None = None,
        prompt_overlay: str | None = None,
        default_execution_target: str | None = None,
        metadata: dict | None = None,
    ) -> Workspace | None:
        workspace = self.get_by_workspace_id(workspace_id)
        if workspace is None:
            return None
        if title is not None:
            workspace.title = title
        if description is not None:
            workspace.description = description
        if base_mode is not None:
            workspace.base_mode = base_mode
        if prompt_overlay is not None:
            workspace.prompt_overlay = prompt_overlay
        if default_execution_target is not None:
            workspace.default_execution_target = default_execution_target
        if metadata is not None:
            merged = dict(workspace.meta or {})
            merged.update(dict(metadata))
            workspace.meta = merged
        self.session.flush()
        return workspace

    def get_by_workspace_id(self, workspace_id: str) -> Workspace | None:
        return self.session.query(Workspace).filter_by(workspace_id=workspace_id).one_or_none()

    def get_by_id(self, row_id) -> Workspace | None:
        return self.session.query(Workspace).filter_by(id=row_id).one_or_none()

    def list_all(self) -> list[Workspace]:
        return list(self.session.query(Workspace).order_by(Workspace.workspace_id).all())
