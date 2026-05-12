from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def utcnow_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def load_auth_tokens_from_dotenv() -> None:
    dotenv_path = REPO_ROOT / ".env"
    if not dotenv_path.exists():
        return
    wanted = {"MEETYOU_GATEWAY_ACCESS_TOKEN", "MEETYOU_CLIENT_ACCESS_TOKEN", "MEETYOU_API_KEY"}
    try:
        lines = dotenv_path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError:
        lines = dotenv_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in wanted or os.environ.get(key):
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        os.environ[key] = value


def auth_headers() -> dict[str, str]:
    load_auth_tokens_from_dotenv()
    bearer = (
        os.environ.get("MEETYOU_GATEWAY_ACCESS_TOKEN")
        or os.environ.get("MEETYOU_CLIENT_ACCESS_TOKEN")
        or ""
    ).strip()
    if bearer:
        return {"Authorization": f"Bearer {bearer}"}
    api_key = os.environ.get("MEETYOU_API_KEY", "").strip()
    return {"X-API-Key": api_key} if api_key else {}


def as_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("value"), list):
        return list(payload["value"])
    if payload is None:
        return []
    return [payload]


def is_acceptance_project(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    title = str(item.get("title") or "")
    return metadata.get("acceptance") == "v5_real_acceptance" or "V5 real acceptance" in title


def is_acceptance_thread(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    title = str(item.get("title") or "")
    return "V5 acceptance thread" in title


class AcceptanceError(RuntimeError):
    pass


@dataclass
class V5Acceptance:
    base_url: str
    expected_branch: str = ""
    workspace_id: str = ""
    wait_timeout: float = 120.0
    keep_resources: bool = False
    marker: str = field(default_factory=lambda: f"V5OK_{utcnow_compact()}_{uuid4().hex[:6]}")

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=auth_headers(),
            timeout=httpx.Timeout(90.0),
            follow_redirects=True,
        )
        self.results: dict[str, Any] = {"marker": self.marker, "checks": []}
        self.project_ids: list[str] = []
        self.thread_ids: list[str] = []

    async def close(self) -> None:
        await self.client.aclose()

    def ok(self, name: str, details: dict[str, Any] | None = None) -> None:
        clean_details = dict(details or {})
        self.results["checks"].append({"name": name, "ok": True, "details": clean_details})
        suffix = f" {clean_details}" if clean_details else ""
        print(f"[OK] {name}{suffix}")

    def fail(self, name: str, message: str) -> None:
        self.results["checks"].append({"name": name, "ok": False, "message": message})
        raise AcceptanceError(f"{name}: {message}")

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        raw: bool = False,
    ) -> Any:
        response = await self.client.request(method, path, json=json_body, params=params)
        if response.status_code >= 400:
            raise AcceptanceError(f"{method} {path} failed: {response.status_code} {response.text[:800]}")
        if raw:
            return response
        if not response.content:
            return None
        return response.json()

    async def cleanup(self) -> None:
        if self.keep_resources:
            self.ok("cleanup skipped", {"keep_resources": True})
            return
        for thread_id in reversed(self.thread_ids):
            try:
                await self.request("DELETE", f"/runtime/threads/{thread_id}", params={"force": "true"})
                self.ok("thread cleaned", {"thread_id": thread_id})
            except Exception as exc:  # noqa: BLE001 - cleanup should not mask the real result.
                print(f"[WARN] thread cleanup failed for {thread_id}: {exc}")
        for project_id in reversed(self.project_ids):
            try:
                archived = await self.request("PATCH", f"/runtime/projects/{project_id}", json_body={"status": "archived"})
                self.ok("project archived", {"project_id": project_id, "status": archived.get("status")})
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] project archive failed for {project_id}: {exc}")
        await self.assert_no_acceptance_resources()

    async def cleanup_leaked_resources(self) -> None:
        removed_threads: set[str] = set()
        archived_projects: set[str] = set()
        projects = as_list(await self.request("GET", "/runtime/projects", params={"include_archived": "true", "limit": "500"}))
        for project in projects:
            if not is_acceptance_project(project):
                continue
            project_id = str(project.get("project_id") or "").strip()
            if not project_id:
                continue
            try:
                project_threads = as_list(await self.request("GET", f"/runtime/projects/{project_id}/threads"))
                for thread in project_threads:
                    thread_id = str(thread.get("thread_id") or "").strip() if isinstance(thread, dict) else ""
                    if thread_id and thread_id not in removed_threads:
                        await self.request("DELETE", f"/runtime/threads/{thread_id}", params={"force": "true"})
                        removed_threads.add(thread_id)
                await self.request("PATCH", f"/runtime/projects/{project_id}", json_body={"status": "archived"})
                archived_projects.add(project_id)
            except Exception as exc:  # noqa: BLE001 - cleanup-only should continue across stale rows.
                print(f"[WARN] leaked project cleanup failed for {project_id}: {exc}")
        threads = as_list(await self.request("GET", "/runtime/threads", params={"limit": "500"}))
        for thread in threads:
            if not is_acceptance_thread(thread):
                continue
            thread_id = str(thread.get("thread_id") or "").strip()
            if not thread_id or thread_id in removed_threads:
                continue
            try:
                await self.request("DELETE", f"/runtime/threads/{thread_id}", params={"force": "true"})
                removed_threads.add(thread_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] leaked thread cleanup failed for {thread_id}: {exc}")
        self.ok("acceptance leaked resources cleaned", {"threads": len(removed_threads), "projects": len(archived_projects)})
        await self.assert_no_acceptance_resources()

    async def assert_no_acceptance_resources(self) -> None:
        active_projects = as_list(await self.request("GET", "/runtime/projects", params={"include_archived": "false", "limit": "500"}))
        leaked_projects = [str(item.get("project_id") or "") for item in active_projects if is_acceptance_project(item)]
        active_threads = as_list(await self.request("GET", "/runtime/threads", params={"limit": "500"}))
        leaked_threads = [str(item.get("thread_id") or "") for item in active_threads if is_acceptance_thread(item)]
        if leaked_projects or leaked_threads:
            self.fail("acceptance cleanup assertion", f"leaked_projects={leaked_projects} leaked_threads={leaked_threads}")
        self.ok("acceptance cleanup assertion", {"active_projects": 0, "active_threads": 0})

    async def check_health(self) -> None:
        health = await self.request("GET", "/health")
        payload = health.get("health", health) if isinstance(health, dict) else {}
        build_info = payload.get("build_info", {}) if isinstance(payload, dict) else {}
        branch = str(build_info.get("branch") or "")
        commit = str(build_info.get("git_commit") or "")
        status = str(payload.get("status") or "")
        if self.expected_branch and branch != self.expected_branch:
            self.fail("core branch", f"expected {self.expected_branch}, got {branch or '<missing>'}")
        self.ok("core health", {"status": status, "branch": branch, "commit": commit[:12]})

    async def discover_workspace(self) -> str:
        if self.workspace_id:
            self.ok("workspace selected", {"workspace_id": self.workspace_id})
            return self.workspace_id
        workspaces = as_list(await self.request("GET", "/runtime/workspaces"))
        for item in workspaces:
            workspace_id = str(item.get("workspace_id") or "").strip() if isinstance(item, dict) else ""
            if workspace_id:
                self.workspace_id = workspace_id
                self.ok("workspace discovered", {"workspace_id": workspace_id})
                return workspace_id
        self.fail("workspace discovered", "no runtime workspace is available")
        return ""

    async def create_project_and_thread(self) -> tuple[dict[str, Any], dict[str, Any]]:
        workspace_id = await self.discover_workspace()
        project = await self.request(
            "POST",
            "/runtime/projects",
            json_body={
                "workspace_id": workspace_id,
                "title": f"V5 real acceptance {self.marker}",
                "description": "Temporary project for V5 acceptance.",
                "instructions": "Use project sources first during this acceptance run.",
                "metadata": {"acceptance": "v5_real_acceptance", "marker": self.marker},
            },
        )
        project_id = str(project.get("project_id") or "")
        if not project_id:
            self.fail("project create", "missing project_id")
        self.project_ids.append(project_id)
        patched = await self.request(
            "PATCH",
            f"/runtime/projects/{project_id}",
            json_body={"description": "Patched by V5 real acceptance.", "instructions": "Patched project instructions."},
        )
        if patched.get("description") != "Patched by V5 real acceptance.":
            self.fail("project patch", "description did not persist")
        self.ok("project create and patch", {"project_id": project_id})

        note = await self.request(
            "POST",
            f"/runtime/projects/{project_id}/sources",
            json_body={
                "source_type": "note",
                "title": "V5 acceptance evidence note",
                "content": "V5 acceptance evidence note content for research synthesis.",
                "content_type": "text",
                "metadata": {"marker": self.marker, "created_from": "v5_real_acceptance"},
            },
        )
        sources = as_list(await self.request("GET", f"/runtime/projects/{project_id}/sources"))
        if not any(item.get("source_id") == note.get("source_id") for item in sources if isinstance(item, dict)):
            self.fail("project source note", "created source was not listed")
        self.ok("project source note", {"source_id": note.get("source_id"), "source_count": len(sources)})

        delete_note = await self.request(
            "POST",
            f"/runtime/projects/{project_id}/sources",
            json_body={
                "source_type": "note",
                "title": "V5 acceptance delete source",
                "content": "Temporary source that must be archived during acceptance.",
                "content_type": "text",
                "metadata": {"marker": self.marker, "created_from": "v5_real_acceptance"},
            },
        )
        archived_source = await self.request(
            "DELETE",
            f"/runtime/projects/{project_id}/sources/{delete_note['source_id']}",
        )
        active_sources = as_list(await self.request("GET", f"/runtime/projects/{project_id}/sources"))
        archived_sources = as_list(await self.request("GET", f"/runtime/projects/{project_id}/sources", params={"include_archived": "true"}))
        if archived_source.get("status") != "archived":
            self.fail("project source delete", f"unexpected archived status={archived_source.get('status')}")
        if any(item.get("source_id") == delete_note.get("source_id") for item in active_sources if isinstance(item, dict)):
            self.fail("project source delete", "archived source remained in active source list")
        if not any(item.get("source_id") == delete_note.get("source_id") and item.get("status") == "archived" for item in archived_sources if isinstance(item, dict)):
            self.fail("project source delete", "archived source was not visible in include_archived list")
        self.ok("project source delete", {"source_id": delete_note.get("source_id")})

        thread = await self.request(
            "POST",
            "/runtime/threads",
            json_body={
                "workspace_id": workspace_id,
                "project_id": project_id,
                "title": f"V5 acceptance thread {self.marker}",
            },
        )
        thread_id = str(thread.get("thread_id") or "")
        if not thread_id or thread.get("project_id") != project_id:
            self.fail("project thread create", "thread did not bind to project")
        self.thread_ids.append(thread_id)
        project_threads = as_list(await self.request("GET", f"/runtime/projects/{project_id}/threads"))
        if not any(item.get("thread_id") == thread_id for item in project_threads if isinstance(item, dict)):
            self.fail("project thread listing", "created thread was not listed under project")
        self.ok("project thread create", {"thread_id": thread_id})
        return project, thread

    async def check_versioning_and_sources(self, project: dict[str, Any], thread: dict[str, Any]) -> None:
        project_id = str(project["project_id"])
        thread_id = str(thread["thread_id"])
        workspace_id = str(thread.get("workspace_id") or self.workspace_id)

        user_message = await self.request(
            "POST",
            "/runtime/messages",
            json_body={
                "thread_id": thread_id,
                "workspace_id": workspace_id,
                "endpoint_id": "v5.acceptance",
                "endpoint_type": "acceptance",
                "role": "user",
                "content": "V5 acceptance original prompt",
                "metadata": {"marker": self.marker},
            },
        )
        assistant_message = await self.request(
            "POST",
            "/runtime/messages",
            json_body={
                "thread_id": thread_id,
                "workspace_id": workspace_id,
                "endpoint_id": "v5.acceptance",
                "endpoint_type": "acceptance",
                "role": "assistant",
                "content": "V5 acceptance original answer",
                "metadata": {"marker": self.marker},
            },
        )

        message_source = await self.request(
            "POST",
            f"/runtime/projects/{project_id}/sources/from-message",
            json_body={
                "message_id": assistant_message["message_id"],
                "title": "V5 acceptance answer snapshot",
                "metadata": {"marker": self.marker, "created_from": "v5_real_acceptance"},
            },
        )
        if message_source.get("source_type") != "message_snapshot":
            self.fail("message snapshot source", f"unexpected source_type={message_source.get('source_type')}")
        self.ok("message snapshot source", {"source_id": message_source.get("source_id")})

        branches = as_list(await self.request("GET", f"/runtime/threads/{thread_id}/branches"))
        if len(branches) != 1:
            self.fail("default branch", f"expected one branch, got {len(branches)}")
        default_branch = branches[0]
        default_branch_id = str(default_branch.get("branch_id") or "")
        if not default_branch.get("metadata", {}).get("is_active"):
            self.fail("default branch", "default branch is not active")

        checkpoints = as_list(await self.request("GET", f"/runtime/threads/{thread_id}/checkpoints"))
        checkpoint_by_message = {
            str(item.get("message_id") or ""): item
            for item in checkpoints
            if isinstance(item, dict) and item.get("message_id")
        }
        user_checkpoint = checkpoint_by_message.get(str(user_message["message_id"]))
        assistant_checkpoint = checkpoint_by_message.get(str(assistant_message["message_id"]))
        if not user_checkpoint or not assistant_checkpoint:
            self.fail(
                "automatic checkpoints",
                f"missing message checkpoints; checkpoint_count={len(checkpoints)}",
            )
        self.ok("automatic checkpoints", {"checkpoint_count": len(checkpoints)})

        await self.request("POST", f"/runtime/threads/{thread_id}/checkpoints/{user_checkpoint['checkpoint_id']}/restore")
        restored_messages = as_list(await self.request("GET", f"/runtime/threads/{thread_id}/messages"))
        if [item.get("content") for item in restored_messages] != ["V5 acceptance original prompt"]:
            self.fail("checkpoint restore", f"unexpected restored messages={restored_messages}")
        self.ok("checkpoint restore", {"message_count": len(restored_messages)})

        checkout_branch = await self.request(
            "POST",
            f"/runtime/threads/{thread_id}/checkpoints/{assistant_checkpoint['checkpoint_id']}/checkout",
            json_body={"title": "V5 acceptance checkout branch"},
        )
        if checkout_branch.get("parent_branch_id") != default_branch_id:
            self.fail("checkpoint checkout", "checkout branch parent mismatch")
        self.ok("checkpoint checkout", {"branch_id": checkout_branch.get("branch_id")})

        retry = await self.request(
            "POST",
            f"/runtime/messages/{user_message['message_id']}/edit-retry",
            json_body={"content": "V5 acceptance edited prompt", "title": "V5 acceptance edit retry branch"},
        )
        if retry.get("message", {}).get("content") != "V5 acceptance edited prompt":
            self.fail("edit retry", "edited message content mismatch")
        if retry.get("branch", {}).get("parent_branch_id") != default_branch_id:
            self.fail("edit retry", "retry branch parent mismatch")
        self.ok("edit retry", {"branch_id": retry.get("branch", {}).get("branch_id"), "replay_status": retry.get("replay_status")})

        branches_after_retry = as_list(await self.request("GET", f"/runtime/threads/{thread_id}/branches"))
        active = [item for item in branches_after_retry if item.get("metadata", {}).get("is_active")]
        if [item.get("branch_id") for item in active] != [retry.get("branch", {}).get("branch_id")]:
            self.fail("branch activation after edit retry", "retry branch is not the sole active branch")
        siblings = [item for item in branches_after_retry if item.get("parent_branch_id") == default_branch_id]
        if len(siblings) < 2:
            self.fail("branch sibling variants", "checkout and retry branches were not both exposed")
        self.ok("branch sibling variants", {"branch_count": len(branches_after_retry), "sibling_count": len(siblings)})

        activated = await self.request("POST", f"/runtime/threads/{thread_id}/branches/{checkout_branch['branch_id']}/activate")
        if not activated.get("metadata", {}).get("is_active"):
            self.fail("branch activate", "checkout branch did not become active")
        activated_messages = as_list(await self.request("GET", f"/runtime/threads/{thread_id}/messages"))
        if [item.get("content") for item in activated_messages] != [
            "V5 acceptance original prompt",
            "V5 acceptance original answer",
        ]:
            self.fail("branch projected messages", "active branch did not project the original message path")
        self.ok("branch activate and projection", {"branch_id": activated.get("branch_id")})

    async def check_research_and_artifacts(self, project: dict[str, Any], thread: dict[str, Any]) -> None:
        project_id = str(project["project_id"])
        thread_id = str(thread["thread_id"])
        task = await self.request(
            "POST",
            "/runtime/research-tasks",
            json_body={
                "project_id": project_id,
                "thread_id": thread_id,
                "topic": f"V5 project source research acceptance {self.marker}",
                "source_policy": {
                    "source_adapters": [],
                    "include_project_sources": True,
                    "derived_formats": ["pdf", "docx"],
                    "limit": 5,
                },
            },
        )
        task_id = str(task.get("research_task_id") or "")
        if not task_id or task.get("status") != "planned":
            self.fail("research task create", f"unexpected create response={task}")
        plan = task.get("plan", {})
        if plan.get("language") != "zh-CN" or not plan.get("approval", {}).get("editable_before_start"):
            self.fail("research plan contract", "plan is not Chinese-first/editable-before-start")
        if "citation_guard" not in [gate.get("id") for gate in plan.get("quality_gates", [])]:
            self.fail("research plan contract", "citation_guard quality gate missing")
        self.ok("research task create", {"research_task_id": task_id})

        task = await self.request("PATCH", f"/runtime/research-tasks/{task_id}", json_body={"action": "start"})
        if task.get("status") != "running" or not task.get("run_id"):
            self.fail("research task start", f"unexpected start response={task}")
        self.ok("research task start", {"run_id": task.get("run_id")})

        deadline = asyncio.get_running_loop().time() + self.wait_timeout
        completed: dict[str, Any] = {}
        while asyncio.get_running_loop().time() < deadline:
            completed = await self.request("GET", f"/runtime/research-tasks/{task_id}")
            status = str(completed.get("status") or "")
            if status in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(1.5)
        if completed.get("status") != "completed":
            self.fail("research task completion", f"status={completed.get('status')} metadata={completed.get('metadata')}")
        evidence = as_list(completed.get("evidence_ledger"))
        if not evidence:
            self.fail("research evidence", "completed task has no evidence")
        if not all(item.get("source_trust") == "untrusted" for item in evidence if isinstance(item, dict)):
            self.fail("research evidence trust", "evidence rows are not marked untrusted")
        if not completed.get("artifact_id") or not completed.get("artifact", {}).get("download_url"):
            self.fail("research artifact", "completed task is missing artifact metadata")
        derived = as_list(completed.get("derived_artifacts"))
        formats = [item.get("metadata", {}).get("derived_format") for item in derived if isinstance(item, dict)]
        if formats != ["pdf", "docx"]:
            self.fail("research derived artifacts", f"unexpected formats={formats}")
        self.ok("research task completed", {"artifact_id": completed.get("artifact_id"), "evidence_count": len(evidence)})

        events = as_list(await self.request("GET", f"/runtime/research-tasks/{task_id}/events", params={"durable_only": "true"}))
        event_types = [str(item.get("type") or "") for item in events if isinstance(item, dict)]
        if "research.started" not in event_types or "research.completed" not in event_types:
            self.fail("research run events", f"missing durable events: {event_types}")
        self.ok("research run events", {"event_count": len(events), "last": event_types[-1] if event_types else ""})

        report_response = await self.request("GET", str(completed["artifact"]["download_url"]), raw=True)
        report_text = report_response.text
        if "V5 acceptance evidence note" not in report_text:
            self.fail("research report download", "report does not contain the project source evidence title")
        self.ok("research report download", {"bytes": len(report_response.content)})

        pdf = next((item for item in derived if item.get("metadata", {}).get("derived_format") == "pdf"), None)
        docx = next((item for item in derived if item.get("metadata", {}).get("derived_format") == "docx"), None)
        pdf_response = await self.request("GET", str(pdf["download_url"]), raw=True)
        docx_response = await self.request("GET", str(docx["download_url"]), raw=True)
        if not pdf_response.content.startswith(b"%PDF-"):
            self.fail("research pdf download", "PDF derivative missing PDF header")
        if not docx_response.content.startswith(b"PK"):
            self.fail("research docx download", "DOCX derivative missing ZIP header")
        self.ok("research derived downloads", {"pdf_bytes": len(pdf_response.content), "docx_bytes": len(docx_response.content)})

        artifacts = as_list(await self.request("GET", f"/runtime/projects/{project_id}/artifacts"))
        artifact_ids = {str(item.get("artifact_id") or "") for item in artifacts if isinstance(item, dict)}
        expected_ids = {str(completed.get("artifact_id") or ""), str(pdf.get("artifact_id") or ""), str(docx.get("artifact_id") or "")}
        if not expected_ids.issubset(artifact_ids):
            self.fail("project artifact listing", f"missing expected artifacts={expected_ids - artifact_ids}")
        self.ok("project artifact listing", {"artifact_count": len(artifacts)})

        messages = as_list(await self.request("GET", f"/runtime/threads/{thread_id}/messages"))
        if not any("/runtime/artifacts/" in str(item.get("content") or "") for item in messages if isinstance(item, dict)):
            self.fail("research delivery message", "thread does not include an artifact link message")
        self.ok("research delivery message", {"message_count": len(messages)})

    async def check_research_cancel(self, project: dict[str, Any]) -> None:
        task = await self.request(
            "POST",
            "/runtime/research-tasks",
            json_body={
                "project_id": project["project_id"],
                "topic": f"V5 cancellation acceptance {self.marker}",
                "source_policy": {"source_adapters": [], "auto_execute": False},
            },
        )
        cancelled = await self.request("PATCH", f"/runtime/research-tasks/{task['research_task_id']}", json_body={"action": "cancel"})
        if cancelled.get("status") != "cancelled" or cancelled.get("artifact_id"):
            self.fail("research cancel", f"unexpected cancel response={cancelled}")
        self.ok("research cancel", {"research_task_id": cancelled.get("research_task_id")})

    async def run(self) -> dict[str, Any]:
        await self.check_health()
        await self.cleanup_leaked_resources()
        project, thread = await self.create_project_and_thread()
        await self.check_versioning_and_sources(project, thread)
        await self.check_research_cancel(project)
        await self.check_research_and_artifacts(project, thread)
        return self.results


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Run MeetYou V5 local/remote real acceptance checks.")
    parser.add_argument("--base-url", default=os.environ.get("MEETYOU_CORE_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--expected-branch", default=os.environ.get("MEETYOU_EXPECTED_BRANCH", ""))
    parser.add_argument("--workspace-id", default=os.environ.get("MEETYOU_ACCEPTANCE_WORKSPACE_ID", ""))
    parser.add_argument("--wait-timeout", type=float, default=float(os.environ.get("MEETYOU_V5_ACCEPTANCE_TIMEOUT", "120")))
    parser.add_argument("--keep-resources", action="store_true")
    parser.add_argument("--cleanup-only", action="store_true", help="Only remove leaked V5 acceptance projects/threads and assert they are gone.")
    args = parser.parse_args()

    acceptance = V5Acceptance(
        base_url=args.base_url,
        expected_branch=args.expected_branch,
        workspace_id=args.workspace_id,
        wait_timeout=args.wait_timeout,
        keep_resources=args.keep_resources,
    )
    try:
        if args.cleanup_only:
            await acceptance.check_health()
            await acceptance.cleanup_leaked_resources()
            results = acceptance.results
        else:
            results = await acceptance.run()
        print(json_dumps(results))
        return 0
    except AcceptanceError as exc:
        print(f"[FAIL] {exc}")
        return 1
    finally:
        await acceptance.cleanup()
        await acceptance.close()


def json_dumps(payload: Any) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
