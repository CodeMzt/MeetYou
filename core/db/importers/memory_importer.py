from __future__ import annotations

from core.db.importers.helpers import infer_workspace_key
from core.persistence import load_json_with_recovery


def import_memory_state(memory_file_path: str, *, principal_id, workspaces: dict[str, object], services) -> int:
    payload = load_json_with_recovery(
        memory_file_path,
        validator=lambda data: isinstance(data, dict) and isinstance(data.get("records"), list),
        default_factory=lambda: {"records": []},
    )
    imported: list[dict] = []
    for record in payload.get("records", []):
        if not isinstance(record, dict):
            continue
        scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
        scope_user_id = str(scope.get("user_id") or "global")
        scope_session_id = str(scope.get("session_id") or "")
        workspace_key = infer_workspace_key(scope_user_id)
        workspace = workspaces.get(workspace_key) if workspace_key else None
        imported.append(
            {
                "memory_id": str(record.get("id") or ""),
                "origin_workspace_id": getattr(workspace, "id", None),
                "record_type": str(record.get("type") or "episode"),
                "status": str(record.get("status") or "active"),
                "content": str(record.get("content") or ""),
                "canonical_text": str(record.get("canonical_text") or ""),
                "scope_user_id": scope_user_id,
                "scope_session_id": scope_session_id,
                "raw_record": record,
                "meta": {"imported_from": memory_file_path},
                "workspace_ids": [getattr(workspace, "id", None)] if workspace is not None else [],
            }
        )
    sanitized = []
    for item in imported:
        item["workspace_ids"] = [value for value in item["workspace_ids"] if value is not None]
        if item["memory_id"]:
            sanitized.append(item)
    return services.memory_state.replace_records(principal_id=principal_id, records=sanitized)
