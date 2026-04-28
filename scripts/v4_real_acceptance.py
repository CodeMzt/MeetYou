from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse, urlunparse
from uuid import uuid4

import httpx
import websockets
from websockets.exceptions import InvalidStatus

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from endpoint_tool_sdk.protocol import (
    ENDPOINT_TOOL_PROTOCOL_SCHEMA,
    build_endpoint_capabilities_snapshot,
    build_endpoint_heartbeat,
    build_endpoint_hello,
    build_endpoint_envelope,
    build_tool_call_accepted_message,
    build_tool_call_progress_message,
    build_tool_call_result_message,
)
from endpoint_tool_sdk.tool_ids import build_endpoint_tool_id


def utcnow_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def load_auth_tokens_from_dotenv() -> None:
    dotenv_path = REPO_ROOT / ".env"
    if not dotenv_path.exists():
        return
    wanted = {"MEETYOU_GATEWAY_ACCESS_TOKEN", "MEETYOU_CLIENT_ACCESS_TOKEN"}
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


def bearer_headers() -> dict[str, str]:
    load_auth_tokens_from_dotenv()
    token = (
        os.environ.get("MEETYOU_GATEWAY_ACCESS_TOKEN")
        or os.environ.get("MEETYOU_CLIENT_ACCESS_TOKEN")
        or ""
    ).strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def ws_url(base_url: str, path: str) -> str:
    load_auth_tokens_from_dotenv()
    parsed = urlparse(base_url.rstrip("/") + path)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    token = (
        os.environ.get("MEETYOU_GATEWAY_ACCESS_TOKEN")
        or os.environ.get("MEETYOU_CLIENT_ACCESS_TOKEN")
        or ""
    ).strip()
    query = parsed.query
    if token:
        query = f"{query}&access_token={quote(token)}" if query else f"access_token={quote(token)}"
    return urlunparse((scheme, parsed.netloc, parsed.path, "", query, ""))


def as_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("value"), list):
        return list(payload["value"])
    if payload is None:
        return []
    return [payload]


def frame(frame_type: str, *, endpoint_id: str, payload: dict[str, Any], correlation_id: str = "") -> dict[str, Any]:
    return build_endpoint_envelope(
        envelope_type=frame_type,
        endpoint_id=endpoint_id,
        payload=payload,
        message_id=f"msg_{uuid4().hex}",
        correlation_id=correlation_id,
    )


@dataclass
class ProbeState:
    provider_id: str
    provider_type: str
    workspace_id: str
    frames: list[dict[str, Any]] = field(default_factory=list)
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    tool_requests: list[dict[str, Any]] = field(default_factory=list)
    stopped: bool = False

    @property
    def ui_endpoint_id(self) -> str:
        return f"{self.provider_type}.{self.provider_id}.ui"

    @property
    def executor_endpoint_id(self) -> str:
        return f"{self.provider_type}.{self.provider_id}.executor"


class AcceptanceError(RuntimeError):
    pass


class V4Acceptance:
    def __init__(self, *, base_url: str, ui_url: str, skip_ui: bool = False):
        self.base_url = base_url.rstrip("/")
        self.ui_url = ui_url.rstrip("/")
        self.skip_ui = skip_ui
        self.marker = f"V4OK_{utcnow_compact()}_{uuid4().hex[:6]}"
        self.headers = bearer_headers()
        self.client = httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=90)
        self.results: dict[str, Any] = {"marker": self.marker, "checks": []}

    async def close(self) -> None:
        await self.client.aclose()

    def ok(self, name: str, details: dict[str, Any] | None = None) -> None:
        self.results["checks"].append({"name": name, "ok": True, "details": dict(details or {})})
        print(f"[OK] {name}")

    def fail(self, name: str, message: str) -> None:
        self.results["checks"].append({"name": name, "ok": False, "message": message})
        raise AcceptanceError(f"{name}: {message}")

    async def request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> Any:
        response = await self.client.request(method, path, json=json_body)
        if response.status_code >= 400:
            raise AcceptanceError(f"{method} {path} failed: {response.status_code} {response.text[:800]}")
        if not response.content:
            return None
        return response.json()

    async def check_health_and_ui(self) -> None:
        health = await self.request("GET", "/health")
        self.ok("core health", {"status": health.get("status") if isinstance(health, dict) else ""})
        if self.skip_ui:
            self.ok("ui skipped")
            return
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(self.ui_url)
        if response.status_code >= 400:
            self.fail("ui dev server", f"status={response.status_code}")
        if "等待后端服务启动后即可使用" in response.text:
            self.fail("ui dev server", "stale backend-waiting placeholder is still rendered in index HTML")
        self.ok("ui dev server", {"url": self.ui_url, "status": response.status_code})

    async def check_legacy_ws_removed(self) -> None:
        try:
            async with websockets.connect(ws_url(self.base_url, "/client/ws"), open_timeout=5):
                self.fail("/client/ws removed", "legacy websocket unexpectedly accepted a connection")
        except InvalidStatus as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None) or getattr(exc, "status_code", None)
            if status in {400, 403, 404, 410, 426}:
                self.ok("/client/ws removed", {"status": status})
                return
            self.fail("/client/ws removed", f"unexpected websocket status: {status}")
        except OSError:
            self.ok("/client/ws removed", {"status": "connection rejected"})

    async def first_workspace_id(self) -> str:
        workspaces = as_list(await self.request("GET", "/client/workspaces"))
        for item in workspaces:
            if isinstance(item, dict) and str(item.get("workspace_id") or "").strip():
                workspace_id = str(item["workspace_id"]).strip()
                self.ok("workspace discovered", {"workspace_id": workspace_id})
                return workspace_id
        self.fail("workspace discovered", "no workspace_id returned by /client/workspaces")
        return ""

    async def receiver(self, ws, state: ProbeState) -> None:
        try:
            async for raw in ws:
                payload = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    continue
                state.frames.append(payload)
                await state.queue.put(payload)
                if payload.get("type") == "tool.call.request":
                    await self.handle_tool_call(ws, state, payload)
        finally:
            state.stopped = True

    async def handle_tool_call(self, ws, state: ProbeState, payload: dict[str, Any]) -> None:
        state.tool_requests.append(payload)
        body = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        call_id = str(body.get("call_id") or "")
        correlation_id = str(payload.get("message_id") or payload.get("correlation_id") or "")
        arguments = body.get("arguments") if isinstance(body.get("arguments"), dict) else {}
        text = str(arguments.get("text") or arguments.get("message") or "")
        await ws.send(
            json.dumps(
                build_tool_call_accepted_message(
                    provider_id=state.provider_id,
                    provider_type=state.provider_type,
                    call_id=call_id,
                    correlation_id=correlation_id,
                )
            )
        )
        await ws.send(
            json.dumps(
                build_tool_call_progress_message(
                    provider_id=state.provider_id,
                    provider_type=state.provider_type,
                    call_id=call_id,
                    correlation_id=correlation_id,
                    phase="running",
                    detail="v4 acceptance endpoint tool is running",
                )
            )
        )
        await ws.send(
            json.dumps(
                build_tool_call_result_message(
                    provider_id=state.provider_id,
                    provider_type=state.provider_type,
                    call_id=call_id,
                    correlation_id=correlation_id,
                    result={"echo": text, "summary": "v4 endpoint tool completed"},
                )
            )
        )

    async def wait_for(
        self,
        state: ProbeState,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        timeout: float = 30,
        name: str = "frame",
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout
        for existing in state.frames:
            if predicate(existing):
                return existing
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                seen = [str(item.get("type") or "") for item in state.frames[-20:]]
                raise AcceptanceError(f"timed out waiting for {name}; recent frames={seen}")
            try:
                item = await asyncio.wait_for(state.queue.get(), timeout=remaining)
            except asyncio.TimeoutError as exc:
                seen = [str(item.get("type") or "") for item in state.frames[-20:]]
                raise AcceptanceError(f"timed out waiting for {name}; recent frames={seen}") from exc
            if predicate(item):
                return item

    async def register_endpoint(self, ws, state: ProbeState) -> None:
        await ws.send(
            json.dumps(
                build_endpoint_hello(
                    provider_id=state.provider_id,
                    provider_type=state.provider_type,
                    display_name="V4 Acceptance Endpoint",
                    transport_profile="acceptance_ws",
                    workspace_ids=[state.workspace_id],
                )
            )
        )
        ack = await self.wait_for(state, lambda item: item.get("type") == "endpoint.hello.ack", name="endpoint.hello.ack")
        registered = ack.get("payload", {}).get("registered_endpoints", [])
        if state.executor_endpoint_id not in registered or state.ui_endpoint_id not in registered:
            self.fail("endpoint hello", f"registered endpoints missing expected ids: {registered}")
        tool_id = build_endpoint_tool_id(state.executor_endpoint_id, "utility.echo")
        await ws.send(
            json.dumps(
                build_endpoint_capabilities_snapshot(
                    provider_id=state.provider_id,
                    provider_type=state.provider_type,
                    revision=1,
                    capabilities=[
                        {
                            "tool_id": tool_id,
                            "tool_key": "utility.echo",
                            "kind": "tool",
                            "title": "V4 Echo",
                            "risk_level": "read",
                            "requires_confirmation": False,
                            "workspace_ids": [state.workspace_id],
                        }
                    ],
                )
            )
        )
        await self.wait_for(state, lambda item: item.get("type") == "endpoint.ready", name="endpoint.ready")
        await ws.send(
            json.dumps(
                frame(
                    "endpoint.ready",
                    endpoint_id=state.executor_endpoint_id,
                    payload={"endpoint_id": state.executor_endpoint_id},
                )
            )
        )
        await ws.send(json.dumps(build_endpoint_heartbeat(provider_id=state.provider_id, provider_type=state.provider_type, status="ready")))
        self.ok("endpoint protocol", {"executor_endpoint_id": state.executor_endpoint_id})

    async def create_thread_and_session(self, state: ProbeState) -> tuple[str, str]:
        thread = await self.request(
            "POST",
            "/client/threads",
            json_body={
                "workspace_id": state.workspace_id,
                "title": f"V4 acceptance {self.marker}",
                "mode": "study",
            },
        )
        thread_id = str(thread.get("thread_id") or "")
        session = await self.request(
            "POST",
            "/client/sessions",
            json_body={
                "thread_id": thread_id,
                "workspace_id": state.workspace_id,
                "client_id": state.ui_endpoint_id,
                "client_type": "acceptance",
                "display_name": "V4 Acceptance",
            },
        )
        session_id = str(session.get("session_id") or "")
        if not thread_id or not session_id:
            self.fail("thread/session", f"invalid response thread={thread} session={session}")
        self.ok("thread/session", {"thread_id": thread_id, "session_id": session_id})
        return thread_id, session_id

    async def subscribe_thread(self, ws, state: ProbeState, thread_id: str, *, last_seen_event_seq: int = 0) -> None:
        await ws.send(
            json.dumps(
                frame(
                    "subscription.start",
                    endpoint_id=state.executor_endpoint_id,
                    payload={
                        "subscription_id": f"sub_{uuid4().hex}",
                        "target_type": "thread",
                        "target_id": thread_id,
                        "replay": True,
                        "last_seen_event_seq": last_seen_event_seq,
                    },
                )
            )
        )
        await self.wait_for(
            state,
            lambda item: item.get("type") == "subscription.ack"
            and item.get("payload", {}).get("target_type") == "thread"
            and item.get("payload", {}).get("target_id") == thread_id,
            name="subscription.ack",
        )
        self.ok("thread subscription", {"thread_id": thread_id, "last_seen_event_seq": last_seen_event_seq})

    async def post_message_and_wait(self, state: ProbeState, thread_id: str, session_id: str) -> dict[str, Any]:
        prompt = f"测试，请只回复这个唯一标识，不要重复，不要添加其他内容：{self.marker}"
        await self.request(
            "POST",
            "/client/messages",
            json_body={
                "thread_id": thread_id,
                "workspace_id": state.workspace_id,
                "client_id": state.ui_endpoint_id,
                "session_id": session_id,
                "role": "user",
                "content": prompt,
                "metadata": {
                    "supports_streaming_reply": False,
                    "response_transport": "non_streaming_external_client",
                    "progress_notice_autostart": True,
                    "progress_notice_content": f"正在验证 V4 链路 {self.marker}",
                    "acceptance_marker": self.marker,
                },
            },
        )
        await self.wait_for(
            state,
            lambda item: item.get("type") == "delivery.run_event"
            and item.get("payload", {}).get("type") == "assistant.progress_notice",
            timeout=45,
            name="assistant.progress_notice",
        )
        final_frame = await self.wait_for(
            state,
            lambda item: item.get("type") == "delivery.message"
            and item.get("payload", {}).get("role") == "assistant"
            and item.get("payload", {}).get("thread_id") == thread_id,
            timeout=120,
            name="assistant final message delivery",
        )
        messages = as_list(await self.request("GET", f"/client/threads/{thread_id}/messages"))
        assistant_messages = [
            item
            for item in messages
            if isinstance(item, dict) and item.get("role") == "assistant" and self.marker in str(item.get("content") or "")
        ]
        delivered_messages = [
            item
            for item in state.frames
            if item.get("type") == "delivery.message"
            and item.get("payload", {}).get("role") == "assistant"
            and self.marker in str(item.get("payload", {}).get("content") or "")
        ]
        if len(assistant_messages) != 1:
            self.fail("final assistant persistence", f"expected one persisted assistant message with marker, got {len(assistant_messages)}")
        content = str(assistant_messages[0].get("content") or "")
        if content.count(self.marker) != 1:
            self.fail("non-streaming duplicate guard", f"marker occurrence count={content.count(self.marker)} content={content!r}")
        if len(delivered_messages) != 1:
            self.fail("non-streaming delivery once", f"expected one delivered assistant message with marker, got {len(delivered_messages)}")
        self.ok(
            "conversation delivery",
            {
                "message_id": assistant_messages[0].get("message_id"),
                "content": content,
                "delivery_message_id": final_frame.get("payload", {}).get("message_id"),
            },
        )
        return {"messages": messages, "assistant": assistant_messages[0]}

    async def check_tool_router(self, state: ProbeState, thread_id: str, session_id: str) -> None:
        operation = await self.request(
            "POST",
            "/client/operations",
            json_body={
                "thread_id": thread_id,
                "workspace_id": state.workspace_id,
                "client_id": state.ui_endpoint_id,
                "session_id": session_id,
                "title": "V4 acceptance endpoint echo",
                "operation_type": "tool_call",
                "tool_key": "utility.echo",
                "target_endpoint_id": state.executor_endpoint_id,
                "arguments": {"text": self.marker},
            },
        )
        operation_id = str(operation.get("operation_id") or "")
        await self.wait_for(
            state,
            lambda item: item.get("type") == "delivery.operation_update"
            and item.get("payload", {}).get("operation_id") == operation_id
            and item.get("payload", {}).get("phase") == "completed",
            timeout=30,
            name="operation_update completed",
        )
        if not state.tool_requests:
            self.fail("tool router", "no tool.call.request was observed by endpoint provider")
        request_payload = state.tool_requests[-1].get("payload", {})
        if request_payload.get("tool_key") != "utility.echo":
            self.fail("tool router", f"unexpected tool_key: {request_payload.get('tool_key')}")
        self.ok("tool router", {"operation_id": operation_id, "target": state.executor_endpoint_id})

    async def check_scheduler(self) -> None:
        jobs = as_list(await self.request("GET", "/operator/scheduled-jobs"))
        heartbeat = next((item for item in jobs if isinstance(item, dict) and item.get("job_id") == "system.heartbeat"), None)
        if heartbeat is None:
            self.fail("scheduler system heartbeat", "system.heartbeat not found")
        trigger_config = dict(heartbeat.get("trigger_config") or {})
        interval = int(trigger_config.get("interval_seconds") or 600)
        if heartbeat.get("deletable") is not False:
            self.fail("scheduler system heartbeat", "system.heartbeat is deletable")
        updated = await self.request(
            "PATCH",
            "/operator/scheduled-jobs/system.heartbeat",
            json_body={"interval_seconds": interval, "enabled": bool(heartbeat.get("enabled", True))},
        )
        if int(dict(updated.get("trigger_config") or {}).get("interval_seconds") or 0) != interval:
            self.fail("scheduler system heartbeat", "interval update did not round-trip")
        delete_response = await self.client.delete("/operator/scheduled-jobs/system.heartbeat")
        if delete_response.status_code not in {400, 409}:
            self.fail("scheduler system heartbeat delete guard", f"unexpected status {delete_response.status_code}")
        job_id = f"acceptance.{self.marker.lower()}"
        created = await self.request(
            "POST",
            "/operator/scheduled-jobs",
            json_body={
                "job_id": job_id,
                "kind": "workflow",
                "name": "V4 acceptance disposable job",
                "workspace_id": "",
                "enabled": False,
                "interval_seconds": 3600,
                "action_ref": "core.workflow.assistant_turn",
                "run_template": {"acceptance_marker": self.marker},
            },
        )
        if created.get("job_id") != job_id:
            self.fail("scheduler user job", f"created wrong job: {created}")
        deleted = await self.request("DELETE", f"/operator/scheduled-jobs/{job_id}")
        if not deleted.get("deleted"):
            self.fail("scheduler user job", f"delete failed: {deleted}")
        self.ok("scheduler", {"system_heartbeat_interval": interval, "user_job": job_id})

    async def check_reconnect_replay(self, state: ProbeState, thread_id: str) -> None:
        durable_events = [
            item.get("payload", {})
            for item in state.frames
            if item.get("type") == "delivery.run_event" and item.get("payload", {}).get("durable") is True
        ]
        if not durable_events:
            self.fail("run event replay", "no durable run events were observed before reconnect")
        last_seq = max(int(item.get("seq") or 0) for item in durable_events)
        replay_state = ProbeState(
            provider_id=f"{state.provider_id}-replay",
            provider_type=state.provider_type,
            workspace_id=state.workspace_id,
        )
        async with websockets.connect(ws_url(self.base_url, "/endpoint/ws"), open_timeout=10, ping_interval=None) as ws:
            task = asyncio.create_task(self.receiver(ws, replay_state))
            await self.register_endpoint(ws, replay_state)
            await self.subscribe_thread(ws, replay_state, thread_id, last_seen_event_seq=0)
            replayed = await self.wait_for(
                replay_state,
                lambda item: item.get("type") == "delivery.run_event"
                and item.get("payload", {}).get("durable") is True
                and int(item.get("payload", {}).get("seq") or 0) > 0,
                timeout=20,
                name="replayed durable run event",
            )
            await ws.send(
                json.dumps(
                    frame(
                        "endpoint.goodbye",
                        endpoint_id=replay_state.executor_endpoint_id,
                        payload={"endpoint_id": replay_state.executor_endpoint_id},
                    )
                )
            )
            task.cancel()
            with contextlib_suppress(asyncio.CancelledError):
                await task
        self.ok("disconnect reconnect replay", {"last_seq_before_reconnect": last_seq, "replayed_seq": replayed.get("payload", {}).get("seq")})

    async def run(self) -> dict[str, Any]:
        await self.check_health_and_ui()
        await self.check_legacy_ws_removed()
        workspace_id = await self.first_workspace_id()
        state = ProbeState(provider_id=f"v4check-{uuid4().hex[:8]}", provider_type="desktop", workspace_id=workspace_id)
        async with websockets.connect(ws_url(self.base_url, "/endpoint/ws"), open_timeout=10, ping_interval=None) as ws:
            receiver_task = asyncio.create_task(self.receiver(ws, state))
            try:
                await self.register_endpoint(ws, state)
                thread_id, session_id = await self.create_thread_and_session(state)
                await self.subscribe_thread(ws, state, thread_id)
                await self.post_message_and_wait(state, thread_id, session_id)
                await self.check_tool_router(state, thread_id, session_id)
                await self.check_scheduler()
                await self.check_reconnect_replay(state, thread_id)
                await ws.send(
                    json.dumps(
                        frame(
                            "endpoint.goodbye",
                            endpoint_id=state.executor_endpoint_id,
                            payload={"endpoint_id": state.executor_endpoint_id},
                        )
                    )
                )
            finally:
                receiver_task.cancel()
                with contextlib_suppress(asyncio.CancelledError):
                    await receiver_task
        return self.results


class contextlib_suppress:
    def __init__(self, *exceptions):
        self.exceptions = exceptions

    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return exc_type is not None and issubclass(exc_type, self.exceptions)


async def amain() -> int:
    parser = argparse.ArgumentParser(description="Run MeetYou V4 local/remote real acceptance checks.")
    parser.add_argument("--base-url", default=os.environ.get("MEETYOU_CORE_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--ui-url", default=os.environ.get("MEETYOU_UI_BASE_URL", "http://127.0.0.1:5173"))
    parser.add_argument("--skip-ui", action="store_true")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    acceptance = V4Acceptance(base_url=args.base_url, ui_url=args.ui_url, skip_ui=args.skip_ui)
    try:
        results = await acceptance.run()
    finally:
        await acceptance.close()
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=2)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(amain()))
    except AcceptanceError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
