from __future__ import annotations

from core.db.importers.helpers import infer_workspace_key
from core.persistence import load_json_with_recovery


def import_task_state(task_file_path: str, *, principal_id, workspaces: dict[str, object], services) -> int:
    payload = load_json_with_recovery(
        task_file_path,
        validator=lambda data: isinstance(data, dict) and isinstance(data.get("tasks"), list),
        default_factory=lambda: {"tasks": []},
    )
    imported: list[dict] = []
    seen_task_ids: dict[str, int] = {}
    for task in payload.get("tasks", []):
        if not isinstance(task, dict):
            continue
        scope = task.get("scope") if isinstance(task.get("scope"), dict) else {}
        scope_user_id = str(scope.get("user_id") or "global")
        scope_session_id = str(scope.get("session_id") or "")
        workspace_key = infer_workspace_key(scope_user_id)
        workspace = workspaces.get(workspace_key) if workspace_key else None
        base_task_id = str(task.get("id") or task.get("task_key") or task.get("canonical_text") or "").strip()
        if not base_task_id:
            base_task_id = f"imported_task_{len(imported) + 1}"
        sequence = seen_task_ids.get(base_task_id, 0)
        seen_task_ids[base_task_id] = sequence + 1
        task_id = base_task_id if sequence == 0 else f"{base_task_id}__{sequence + 1}"
        imported.append(
            {
                "task_id": task_id,
                "workspace_id": getattr(workspace, "id", None),
                "scope_user_id": scope_user_id,
                "scope_session_id": scope_session_id,
                "task_type": str(task.get("type") or "task"),
                "status": str(task.get("status") or "active"),
                "title": str(task.get("content") or task.get("summary") or task.get("task_key") or ""),
                "execution_target": str(task.get("execution_target") or "core.local"),
                "due_at": str(task.get("due_at") or ""),
                "next_run_at": str(task.get("next_run_at") or ""),
                "raw_record": task,
                "meta": {"imported_from": task_file_path},
            }
        )
    sanitized = [item for item in imported if item["task_id"]]
    return services.task_state.replace_tasks(principal_id=principal_id, tasks=sanitized)
