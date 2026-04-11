from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

import aiohttp

from core.assistant_modes import AssistantModeManager
from core.config import ConfigManager
from core.db.bootstrap import bootstrap_core_domain
from core.state_backends import RuntimeStateBlobBackend
from tools.document_tools import DocumentTools
from tools.memory import Memory
from tools.office_tools import OfficeTools
from tools.study_tools import StudyTools
from tools.task_manager import TaskManager


def _ok(name: str, detail: str = "") -> None:
    print(f"[PASS] {name}{(': ' + detail) if detail else ''}")


def _fail(name: str, detail: str = "") -> None:
    print(f"[FAIL] {name}{(': ' + detail) if detail else ''}")


class SmokeError(RuntimeError):
    pass


async def _request_json(session: aiohttp.ClientSession, method: str, url: str, *, json_body: dict[str, Any] | None = None) -> Any:
    async with session.request(method, url, json=json_body) as response:
        payload = await response.json()
        if response.status >= 400:
            raise SmokeError(f"{method} {url} -> {response.status}: {payload}")
        return payload


async def run(base_url: str, access_token: str) -> int:
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            health = await _request_json(session, "GET", f"{base_url}/operator/health")
            _ok("Operator health", health.get("health", {}).get("status", ""))

            agents = await _request_json(session, "GET", f"{base_url}/operator/agents")
            _ok("Operator agents", f"count={len(agents)}")

            config = await _request_json(session, "GET", f"{base_url}/operator/config")
            _ok("Operator config", f"items={len(config.get('items', {}))}")

            memory = await _request_json(session, "GET", f"{base_url}/operator/memory")
            _ok("Operator memory", f"records={len(memory.get('records', []))}")

            workspaces = await _request_json(session, "GET", f"{base_url}/client/workspaces")
            if not isinstance(workspaces, list) or not workspaces:
                raise SmokeError("No workspaces returned")
            _ok("Client workspaces", f"count={len(workspaces)}")
            workspace_id = workspaces[0]["workspace_id"]

            thread = await _request_json(
                session,
                "POST",
                f"{base_url}/client/threads",
                json_body={"workspace_id": workspace_id, "title": "Smoke Thread", "mode": "general"},
            )
            _ok("Client thread create", thread.get("thread_id", ""))

            cil_session = await _request_json(
                session,
                "POST",
                f"{base_url}/client/sessions",
                json_body={
                    "thread_id": thread["thread_id"],
                    "workspace_id": workspace_id,
                    "client_id": "smoke-client",
                    "client_type": "smoke",
                    "display_name": "Smoke Client",
                },
            )
            _ok("Client session create", cil_session.get("session_id", ""))

            message = await _request_json(
                session,
                "POST",
                f"{base_url}/client/messages",
                json_body={
                    "thread_id": thread["thread_id"],
                    "workspace_id": workspace_id,
                    "client_id": "smoke-client",
                    "session_id": cil_session["session_id"],
                    "content": "smoke check",
                },
            )
            _ok("Client message create", message.get("message_id", ""))

            messages = await _request_json(session, "GET", f"{base_url}/client/threads/{thread['thread_id']}/messages")
            _ok("Thread messages list", f"count={len(messages)}")
            return 0
        except Exception as exc:
            _fail("Smoke suite", str(exc))
            return 1


async def run_local_tool_smoke() -> int:
    try:
        config = ConfigManager()
        domain = bootstrap_core_domain(config, run_migrations=False)
        mode_manager = AssistantModeManager(config)
        document_tools = DocumentTools(mode_manager, agent_dispatcher=domain.agent_dispatch)
        office_tools = OfficeTools(
            mode_manager,
            document_tools,
            state_backend=RuntimeStateBlobBackend(
                domain.services.state_blob,
                principal_id=domain.principal.id,
                state_key="office_state",
                default_factory=dict,
            ),
        )
        study_tools = StudyTools(
            document_tools,
            state_backend=RuntimeStateBlobBackend(
                domain.services.state_blob,
                principal_id=domain.principal.id,
                state_key="study_progress",
                default_factory=dict,
            ),
        )
        memory = Memory()
        await memory.init_memory(config)
        try:
            task_manager = TaskManager(
                memory,
                task_file_path=config.get("task_file_path") or "user/memory_tasks.json",
                store_backend=RuntimeStateBlobBackend(
                    domain.services.state_blob,
                    principal_id=domain.principal.id,
                    state_key="task_store",
                    default_factory=lambda: {"metadata": {"schema_version": "2", "revision": 0, "updated_at": ""}, "tasks": []},
                ),
            )
            task_payload = json.loads(
                await task_manager.manage_tasks(
                    action="create",
                    summary="smoke task item",
                    source={"id": "smoke-check"},
                )
            )
            if task_payload.get("status") != "success":
                raise SmokeError(f"task smoke failed: {task_payload}")
            _ok("Task smoke", task_payload["tasks"][0]["task_key"])

            office_payload = json.loads(
                await office_tools.manage_schedule(
                    action="draft",
                    title="Smoke schedule",
                    when="tomorrow 09:00",
                    source_system="local",
                )
            )
            if office_payload.get("status") not in {"draft", "requires_confirmation", "created"}:
                raise SmokeError(f"office smoke failed: {office_payload}")
            _ok("Office smoke", office_payload.get("status", ""))

            study_payload = json.loads(
                await study_tools.track_mastery(
                    action="update",
                    topic="smoke topic",
                    score=0.7,
                    notes="smoke note",
                )
            )
            if study_payload.get("status") != "updated":
                raise SmokeError(f"study smoke failed: {study_payload}")
            _ok("Study smoke", study_payload["topic"]["topic"])
        finally:
            await memory.close_memory()
            domain.engine.dispose()
        return 0
    except Exception as exc:
        _fail("Local tool smoke", str(exc))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run basic smoke checks against the new architecture")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--access-token", default="")
    parser.add_argument("--include-local-tools", action="store_true")
    args = parser.parse_args()

    async def _main() -> int:
        code = await run(args.base_url.rstrip("/"), args.access_token)
        if code != 0:
            return code
        if args.include_local_tools:
            return await run_local_tool_smoke()
        return 0

    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
