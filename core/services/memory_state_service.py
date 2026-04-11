from __future__ import annotations

from core.db.repositories import MemoryRecordRepository, WorkspaceRepository
from core.services.base import ServiceBase


class MemoryStateService(ServiceBase):
    def replace_records(self, *, principal_id, records: list[dict]) -> int:
        with self.session_scope() as session:
            repo = MemoryRecordRepository(session)
            repo.delete_all_for_principal(principal_id)
            count = 0
            for payload in records:
                tags = list(payload.pop("workspace_ids", []))
                row = repo.create(principal_id=principal_id, **payload)
                for workspace_id in tags:
                    repo.add_workspace_tag(memory_row_id=row.id, workspace_id=workspace_id)
                count += 1
            return count

    def build_snapshot_view(
        self,
        *,
        principal_id,
        source_id: str = "",
        session_id: str = "",
        include_invalidated: bool = False,
        embedding_model: str = "",
        embedding_api_url: str = "",
    ) -> dict:
        with self.session_scope() as session:
            repo = MemoryRecordRepository(session)
            workspace_repo = WorkspaceRepository(session)
            rows = repo.list_by_principal(principal_id, include_invalidated=include_invalidated)
            tags = repo.list_workspace_tags([row.id for row in rows])
            workspace_rows = workspace_repo.list_all()
            workspace_keys_by_id = {workspace.id: workspace.workspace_id for workspace in workspace_rows}
            tags_by_memory_id: dict[object, list[object]] = {}
            for tag in tags:
                tags_by_memory_id.setdefault(tag.memory_row_id, []).append(tag)

            records = []
            by_type: dict[str, int] = {}
            for row in rows:
                record_type = str(row.record_type or "episode")
                by_type[record_type] = by_type.get(record_type, 0) + 1
                raw = dict(row.raw_record or {})
                scope = raw.get("scope") if isinstance(raw.get("scope"), dict) else {}
                workspace_ids = [
                    workspace_keys_by_id.get(tag.workspace_id, "")
                    for tag in tags_by_memory_id.get(row.id, [])
                    if workspace_keys_by_id.get(tag.workspace_id, "")
                ]
                origin_workspace_id = workspace_keys_by_id.get(row.origin_workspace_id, "") if row.origin_workspace_id is not None else ""
                source_label = (
                    f"工作区:{', '.join(workspace_ids)}"
                    if workspace_ids
                    else (f"工作区:{origin_workspace_id}" if origin_workspace_id else "全局")
                )
                records.append(
                    {
                        "id": row.memory_id,
                        "type": record_type,
                        "scope": {
                            "user_id": str(scope.get("user_id") or row.scope_user_id or "global"),
                            "session_id": str(scope.get("session_id") or row.scope_session_id or ""),
                        },
                        "content": row.content,
                        "strength": float(raw.get("strength") or 0.0),
                        "importance": float(raw.get("importance") or 0.0),
                        "confidence": float(raw.get("confidence") or 0.0),
                        "created_at": row.created_at.isoformat() if row.created_at is not None else "",
                        "last_accessed_at": str(raw.get("last_accessed_at") or ""),
                        "last_updated_at": row.updated_at.isoformat() if row.updated_at is not None else "",
                        "access_count": int(raw.get("access_count") or 0),
                        "status": row.status,
                        "tags": list(raw.get("tags") or []),
                        "entity_keys": list(raw.get("entity_keys") or []),
                        "source_record_ids": list(raw.get("source_record_ids") or []),
                        "fact_key": raw.get("fact_key"),
                        "fact_value": raw.get("fact_value"),
                        "workspace_tags": workspace_ids,
                        "origin_workspace_id": origin_workspace_id,
                        "source_label": source_label,
                    }
                )

            return {
                "metadata": {
                    "embedding_model": embedding_model,
                    "embedding_api_url": embedding_api_url,
                    "updated_at": rows[-1].updated_at.isoformat() if rows else "",
                },
                "scope": {
                    "source_id": source_id,
                    "session_id": session_id,
                },
                "working_summaries": {
                    "global_summary": "",
                    "session_summary": "",
                    "session_id": session_id,
                },
                "records": records,
                "edges": [],
                "stats": {
                    "record_count": len(records),
                    "edge_count": 0,
                    "by_type": by_type,
                },
            }

    def build_graph_view(
        self,
        *,
        principal_id,
        source_id: str = "",
        session_id: str = "",
        include_invalidated: bool = False,
        embedding_model: str = "",
        embedding_api_url: str = "",
    ) -> dict:
        snapshot = self.build_snapshot_view(
            principal_id=principal_id,
            source_id=source_id,
            session_id=session_id,
            include_invalidated=include_invalidated,
            embedding_model=embedding_model,
            embedding_api_url=embedding_api_url,
        )
        return {
            "metadata": snapshot["metadata"],
            "scope": snapshot["scope"],
            "working_summaries": snapshot["working_summaries"],
            "nodes": [
                {
                    **record,
                    "label": record.get("fact_value") or record.get("content")[:40],
                }
                for record in snapshot["records"]
            ],
            "edges": [],
            "stats": snapshot["stats"],
        }
