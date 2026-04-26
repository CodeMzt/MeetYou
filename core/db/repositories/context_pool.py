from __future__ import annotations

from datetime import datetime, timezone

from core.db.models.context_pool import ContextPoolItem
from core.db.repositories.base import RepositoryBase


class ContextPoolRepository(RepositoryBase):
    @staticmethod
    def _sort_timestamp(value: datetime | None) -> datetime:
        if value is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def create(
        self,
        *,
        context_id: str,
        principal_id,
        content: str,
        canonical_text: str,
        thread_id=None,
        session_id=None,
        message_id=None,
        source_client_id=None,
        home_workspace_id=None,
        active_workspace_id=None,
        item_type: str = "turn",
        role: str = "",
        importance: float = 0.5,
        status: str = "active",
        workspace_tags: list[str] | None = None,
        embedding: list | None = None,
        embedding_model: str = "",
        meta: dict | None = None,
    ) -> ContextPoolItem:
        row = ContextPoolItem(
            context_id=context_id,
            principal_id=principal_id,
            thread_id=thread_id,
            session_id=session_id,
            message_id=message_id,
            source_client_id=source_client_id,
            home_workspace_id=home_workspace_id,
            active_workspace_id=active_workspace_id,
            item_type=item_type,
            role=role,
            content=content,
            canonical_text=canonical_text,
            importance=importance,
            status=status,
            workspace_tags=list(workspace_tags or []),
            embedding=list(embedding or []),
            embedding_model=embedding_model,
            meta=dict(meta or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_context_id(self, context_id: str) -> ContextPoolItem | None:
        return self.session.query(ContextPoolItem).filter_by(context_id=context_id).one_or_none()

    def list_active_for_principal(self, *, principal_id, limit: int | None = None) -> list[ContextPoolItem]:
        query = (
            self.session.query(ContextPoolItem)
            .filter(ContextPoolItem.principal_id == principal_id, ContextPoolItem.status == "active")
            .order_by(ContextPoolItem.created_at.desc())
        )
        if limit is not None:
            query = query.limit(max(1, int(limit or 1)))
        return list(query.all())

    def prune_for_principal(self, *, principal_id, max_items: int) -> int:
        max_active = max(1, int(max_items or 1))
        rows = self.list_active_for_principal(principal_id=principal_id)
        if len(rows) <= max_active:
            return 0
        ranked = sorted(
            rows,
            key=lambda item: (
                float(item.importance or 0.0),
                self._sort_timestamp(item.created_at),
            ),
            reverse=True,
        )
        keep_ids = {item.id for item in ranked[:max_active]}
        pruned_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        count = 0
        for row in rows:
            if row.id in keep_ids:
                continue
            row.status = "pruned"
            merged_meta = dict(row.meta or {})
            merged_meta.update({"pruned_reason": "context_pool_window", "pruned_at": pruned_at})
            row.meta = merged_meta
            count += 1
        self.session.flush()
        return count

    def list_candidates(
        self,
        *,
        principal_id,
        thread_id=None,
        session_id=None,
        active_workspace_id=None,
        limit: int = 200,
    ) -> list[ContextPoolItem]:
        filters = [ContextPoolItem.principal_id == principal_id, ContextPoolItem.status == "active"]
        # Workspace/thread/session are ranking signals, not visibility boundaries.
        del thread_id, session_id, active_workspace_id
        return list(
            self.session.query(ContextPoolItem)
            .filter(*filters)
            .order_by(ContextPoolItem.created_at.desc())
            .limit(max(1, int(limit or 200)))
            .all()
        )
