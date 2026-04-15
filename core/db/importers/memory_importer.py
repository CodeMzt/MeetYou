from __future__ import annotations

from core.db.importers.helpers import infer_workspace_key
from core.persistence import load_json_with_recovery


def _normalize_workspace_key(value) -> str:
    return str(value or "").strip()


def import_memory_state_payload(
    payload: dict,
    *,
    principal_id,
    workspaces: dict[str, object],
    services,
    imported_from: str,
) -> int:
    imported: list[dict] = []
    for record in payload.get("records", []):
        if not isinstance(record, dict):
            continue
        scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
        scope_user_id = str(scope.get("user_id") or "global")
        scope_session_id = str(scope.get("session_id") or "")
        workspace_keys = []
        for value in record.get("workspace_tags", []) or record.get("workspace_ids", []) or []:
            workspace_key = _normalize_workspace_key(value)
            if workspace_key and workspace_key not in workspace_keys:
                workspace_keys.append(workspace_key)
        origin_workspace_key = _normalize_workspace_key(record.get("origin_workspace_id"))
        if origin_workspace_key and origin_workspace_key not in workspace_keys:
            workspace_keys.append(origin_workspace_key)
        if not workspace_keys:
            inferred_workspace_key = infer_workspace_key(scope_user_id)
            if inferred_workspace_key:
                workspace_keys.append(inferred_workspace_key)
        origin_workspace = workspaces.get(origin_workspace_key) if origin_workspace_key else None
        if origin_workspace is None and workspace_keys:
            origin_workspace = workspaces.get(workspace_keys[0])
        imported.append(
            {
                "memory_id": str(record.get("id") or ""),
                "origin_workspace_id": getattr(origin_workspace, "id", None),
                "record_type": str(record.get("type") or "episode"),
                "status": str(record.get("status") or "active"),
                "content": str(record.get("content") or ""),
                "canonical_text": str(record.get("canonical_text") or ""),
                "scope_user_id": scope_user_id,
                "scope_session_id": scope_session_id,
                "raw_record": record,
                "meta": {"imported_from": imported_from},
                "workspace_ids": [getattr(workspaces.get(key), "id", None) for key in workspace_keys],
            }
        )
    sanitized = []
    for item in imported:
        item["workspace_ids"] = [value for value in item["workspace_ids"] if value is not None]
        if item["memory_id"]:
            sanitized.append(item)
    return services.memory_state.replace_records(principal_id=principal_id, records=sanitized)


def import_memory_state(memory_file_path: str, *, principal_id, workspaces: dict[str, object], services) -> int:
    payload = load_json_with_recovery(
        memory_file_path,
        validator=lambda data: isinstance(data, dict) and isinstance(data.get("records"), list),
        default_factory=lambda: {"records": []},
    )
    return import_memory_state_payload(
        payload,
        principal_id=principal_id,
        workspaces=workspaces,
        services=services,
        imported_from=memory_file_path,
    )
