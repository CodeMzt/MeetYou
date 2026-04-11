from __future__ import annotations

from core.db.models.memory_record import MemoryRecordModel, MemoryWorkspaceTag
from core.db.repositories.base import RepositoryBase


class MemoryRecordRepository(RepositoryBase):
    def delete_all_for_principal(self, principal_id) -> None:
        rows = self.session.query(MemoryRecordModel).filter_by(principal_id=principal_id).all()
        for row in rows:
            self.session.query(MemoryWorkspaceTag).filter_by(memory_row_id=row.id).delete()
            self.session.delete(row)
        self.session.flush()

    def create(
        self,
        *,
        memory_id: str,
        principal_id,
        record_type: str,
        content: str,
        canonical_text: str,
        scope_user_id: str,
        scope_session_id: str,
        origin_workspace_id=None,
        status: str = "active",
        raw_record: dict | None = None,
        meta: dict | None = None,
    ) -> MemoryRecordModel:
        row = MemoryRecordModel(
            memory_id=memory_id,
            principal_id=principal_id,
            origin_workspace_id=origin_workspace_id,
            record_type=record_type,
            content=content,
            canonical_text=canonical_text,
            scope_user_id=scope_user_id,
            scope_session_id=scope_session_id,
            status=status,
            raw_record=dict(raw_record or {}),
            meta=dict(meta or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def add_workspace_tag(self, *, memory_row_id, workspace_id) -> MemoryWorkspaceTag:
        binding = MemoryWorkspaceTag(memory_row_id=memory_row_id, workspace_id=workspace_id)
        self.session.add(binding)
        self.session.flush()
        return binding

    def list_by_principal(self, principal_id, *, include_invalidated: bool = False) -> list[MemoryRecordModel]:
        query = self.session.query(MemoryRecordModel).filter_by(principal_id=principal_id)
        if not include_invalidated:
            query = query.filter(MemoryRecordModel.status != "invalidated")
        return list(query.order_by(MemoryRecordModel.created_at.asc()).all())

    def list_workspace_tags(self, memory_row_ids: list) -> list[MemoryWorkspaceTag]:
        if not memory_row_ids:
            return []
        return list(self.session.query(MemoryWorkspaceTag).filter(MemoryWorkspaceTag.memory_row_id.in_(memory_row_ids)).all())
