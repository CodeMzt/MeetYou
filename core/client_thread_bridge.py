"""
Bridge Core runtime events to client thread surfaces.
"""

from __future__ import annotations

from typing import Any, Callable


class ClientThreadBridge:
    def __init__(
        self,
        *,
        gateway_getter: Callable[[], Any],
        core_services_getter: Callable[[], Any],
    ) -> None:
        self._gateway_getter = gateway_getter
        self._core_services_getter = core_services_getter

    def _resolve_thread_context(self, session_id: str) -> tuple[Any | None, Any | None, Any | None]:
        gateway = self._gateway_getter()
        core_services = self._core_services_getter()
        if gateway is None or core_services is None:
            return None, None, None
        session_row = core_services.session.get_by_session_id(session_id)
        if session_row is None:
            return gateway, None, None
        thread_row = core_services.thread.get_by_id(session_row.thread_id)
        if thread_row is None:
            return gateway, None, None
        return gateway, core_services, thread_row

    async def publish_task_operation_update(
        self,
        operation,
        *,
        thread_id: str,
        phase: str = "",
        detail: str = "",
        error: dict[str, Any] | None = None,
    ) -> None:
        gateway = self._gateway_getter()
        if gateway is None or not thread_id:
            return
        metadata = dict(getattr(operation, "meta", {}) or {})
        await gateway.publish_client_thread_event(
            thread_id,
            event_type="operation.updated",
            payload={
                "thread_id": thread_id,
                "workspace_id": str(metadata.get("workspace_id") or ""),
                "operation_id": operation.operation_id,
                "title": operation.title,
                "operation_type": operation.operation_type,
                "execution_target": operation.execution_target,
                "target_agent_id": str(metadata.get("target_agent_key") or ""),
                "capability_id": str(metadata.get("preferred_capability_ref") or metadata.get("capability_id") or ""),
                "status": operation.status,
                "phase": phase,
                "detail": detail,
                "routing_reason": str(metadata.get("routing_reason") or ""),
                **({"error": dict(error)} if isinstance(error, dict) else {}),
            },
        )

    async def publish_message_delta(self, session_id: str, *, stream_id: str, turn_id: str, delta: str) -> None:
        if not delta:
            return
        gateway, _, thread_row = self._resolve_thread_context(session_id)
        if gateway is None or thread_row is None:
            return
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="message.delta",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": session_id,
                "stream_id": stream_id,
                "turn_id": turn_id,
                "delta": delta,
            },
        )

    async def publish_runtime_state(self, session_id: str, snapshot: dict[str, Any], *, turn_id: str = "") -> None:
        gateway, _, thread_row = self._resolve_thread_context(session_id)
        if gateway is None or thread_row is None:
            return
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="runtime.state",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": session_id,
                "turn_id": turn_id or str(snapshot.get("turn_id") or ""),
                "snapshot": dict(snapshot or {}),
            },
        )

    async def publish_runtime_usage(self, session_id: str, payload: dict[str, Any]) -> None:
        gateway, _, thread_row = self._resolve_thread_context(session_id)
        if gateway is None or thread_row is None:
            return
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="runtime.usage",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": session_id,
                "snapshot": dict(payload or {}),
            },
        )

    async def publish_reasoning_event(
        self,
        session_id: str,
        *,
        stream_id: str,
        turn_id: str,
        phase: str,
        content: str,
    ) -> None:
        gateway, _, thread_row = self._resolve_thread_context(session_id)
        if gateway is None or thread_row is None:
            return
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="reasoning.delta",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": session_id,
                "stream_id": stream_id,
                "turn_id": turn_id,
                "phase": phase,
                "delta": content,
            },
        )

    async def publish_activity_event(self, session_id: str, *, activity: dict[str, Any], turn_id: str = "") -> None:
        gateway, _, thread_row = self._resolve_thread_context(session_id)
        if gateway is None or thread_row is None:
            return
        metadata = dict(activity.get("metadata") or {}) if isinstance(activity.get("metadata"), dict) else {}
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="activity.status",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": session_id,
                "turn_id": turn_id or str(activity.get("turn_id") or ""),
                "stream_id": str(activity.get("stream_id") or ""),
                "phase": str(activity.get("phase") or "status"),
                "content": str(activity.get("content") or ""),
                "activity_kind": str(activity.get("activity_kind") or metadata.get("activity_kind") or "tool_chain"),
                "tool_names": list(activity.get("tool_names") or metadata.get("tool_names") or []),
                "metadata": metadata,
                "event_id": str(activity.get("event_id") or ""),
            },
        )

    async def persist_and_publish_assistant_message(
        self,
        session_id: str,
        *,
        content: str,
        stream_id: str,
        turn_id: str,
    ) -> None:
        if not content:
            return
        gateway, core_services, thread_row = self._resolve_thread_context(session_id)
        if gateway is None or core_services is None or thread_row is None:
            return
        session_row = core_services.session.get_by_session_id(session_id)
        workspace_row = core_services.workspace.get_by_id(thread_row.workspace_id)
        message = core_services.message.create_message(
            thread_id=thread_row.id,
            session_id=session_row.id,
            role="assistant",
            content=content,
            status="completed",
            meta={"turn_id": turn_id, "stream_id": stream_id},
        )
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="message.completed",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": session_id,
                "message": {
                    "message_id": message.message_id,
                    "thread_id": thread_row.thread_id,
                    "session_id": session_id,
                    "workspace_id": getattr(workspace_row, "workspace_id", ""),
                    "client_id": "",
                    "role": message.role,
                    "content": message.content,
                    "status": message.status,
                    "channel": message.channel,
                    "created_at": message.created_at.isoformat() if getattr(message, "created_at", None) is not None else "",
                },
                "stream_id": stream_id,
                "turn_id": turn_id,
            },
        )

    async def publish_confirm_request(self, event, *, approval_context: dict[str, Any] | None = None) -> None:
        gateway, core_services, thread_row = self._resolve_thread_context(event.session_id)
        if gateway is None or core_services is None or thread_row is None:
            return
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="confirm.requested",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": event.session_id,
                "request_id": event.request_id,
                "content": str(event.content or ""),
                "timeout": float(getattr(event, "timeout", 0.0) or 0.0),
                "default_decision": bool(getattr(event, "default_decision", False)),
                "approval_id": str((approval_context or {}).get("approval_id") or ""),
                "approval_status": str((approval_context or {}).get("approval_status") or ""),
                "approval_type": str((approval_context or {}).get("approval_type") or ""),
                "risk_level": str((approval_context or {}).get("risk_level") or ""),
                "operation_id": str((approval_context or {}).get("operation_id") or ""),
            },
        )

    async def publish_confirm_resolution(
        self,
        payload: dict[str, Any],
        *,
        approval_context: dict[str, Any] | None = None,
    ) -> None:
        session_id = str((payload or {}).get("session_id") or "")
        gateway, _, thread_row = self._resolve_thread_context(session_id)
        if gateway is None or thread_row is None or not session_id:
            return
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="confirm.resolved",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": session_id,
                "request_id": str((payload or {}).get("request_id") or ""),
                "accepted": bool((payload or {}).get("accepted")),
                "approval_id": str((approval_context or {}).get("approval_id") or ""),
                "approval_status": str((approval_context or {}).get("approval_status") or ""),
                "operation_id": str((approval_context or {}).get("operation_id") or ""),
            },
        )

    async def publish_human_input_request(self, event) -> None:
        gateway, _, thread_row = self._resolve_thread_context(event.session_id)
        if gateway is None or thread_row is None:
            return
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="human_input.requested",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": event.session_id,
                "request_id": event.request_id,
                "question": str(getattr(event, "question", "") or event.content or ""),
                "options": list(getattr(event, "options", []) or []),
                "placeholder": str(getattr(event, "placeholder", "") or ""),
                "timeout": float(getattr(event, "timeout", 0.0) or 0.0),
            },
        )

    async def publish_human_input_resolution(self, payload: dict[str, Any]) -> None:
        session_id = str((payload or {}).get("session_id") or "")
        gateway, _, thread_row = self._resolve_thread_context(session_id)
        if gateway is None or thread_row is None or not session_id:
            return
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="human_input.resolved",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": session_id,
                "request_id": str((payload or {}).get("request_id") or ""),
                "answer_text": str((payload or {}).get("answer_text") or ""),
                "selected_option": (payload or {}).get("selected_option"),
            },
        )

    async def publish_control_event(self, session_id: str, payload: dict[str, Any], *, turn_id: str = "") -> None:
        gateway, _, thread_row = self._resolve_thread_context(session_id)
        if gateway is None or thread_row is None or not session_id:
            return
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="control.updated",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "control": dict(payload or {}),
            },
        )
