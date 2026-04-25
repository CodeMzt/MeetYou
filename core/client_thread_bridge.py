"""
Bridge Core runtime events to client thread surfaces.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4


class ClientThreadBridge:
    def __init__(
        self,
        *,
        gateway_getter: Callable[[], Any],
        core_services_getter: Callable[[], Any],
    ) -> None:
        self._gateway_getter = gateway_getter
        self._core_services_getter = core_services_getter

    def _resolve_thread_context(
        self,
        session_id: str,
    ) -> tuple[Any | None, Any | None, Any | None, Any | None, dict[str, Any], str]:
        gateway = self._gateway_getter()
        core_services = self._core_services_getter()
        if gateway is None or core_services is None:
            return None, None, None, None, {}, ""
        session_row = core_services.session.get_by_session_id(session_id)
        if session_row is not None:
            thread_row = core_services.thread.get_by_id(session_row.thread_id)
            if thread_row is not None:
                return gateway, core_services, thread_row, session_row, {}, str(getattr(session_row, "session_id", "") or session_id)
        session_manager = getattr(gateway, "_session_manager", None)
        if session_manager is None:
            return gateway, core_services, None, session_row, {}, session_id
        binding = session_manager.get_binding(session_id)
        binding_metadata = dict(getattr(binding, "metadata", {}) or {}) if binding is not None else {}
        bridged_session_id = str(binding_metadata.get("bridged_session_id") or "").strip()
        bridged_session_row = (
            core_services.session.get_by_session_id(bridged_session_id)
            if bridged_session_id
            else None
        )
        resolved_session_row = bridged_session_row or session_row
        if bridged_session_row is not None:
            thread_row = core_services.thread.get_by_id(bridged_session_row.thread_id)
            if thread_row is not None:
                return gateway, core_services, thread_row, bridged_session_row, binding_metadata, bridged_session_id
        bridged_thread_id = str(binding_metadata.get("thread_id") or "").strip()
        if not bridged_thread_id:
            return gateway, core_services, None, resolved_session_row, binding_metadata, bridged_session_id or session_id
        thread_row = core_services.thread.get_by_thread_id(bridged_thread_id)
        if thread_row is None:
            return gateway, core_services, None, resolved_session_row, binding_metadata, bridged_session_id or session_id
        return gateway, core_services, thread_row, resolved_session_row, binding_metadata, bridged_session_id or session_id

    def _resolve_workspace_rows(self, core_services, *, thread_row, session_row=None, binding_metadata: dict | None = None):
        binding_metadata = dict(binding_metadata or {})
        home_workspace_row = core_services.workspace.get_by_id(
            getattr(thread_row, "home_workspace_id", None) or getattr(thread_row, "workspace_id", None)
        )
        active_workspace_row = None
        if session_row is not None:
            active_workspace_row = core_services.workspace.get_by_id(
                getattr(session_row, "active_workspace_id", None) or getattr(session_row, "workspace_id", None)
            )
        if active_workspace_row is None:
            active_workspace_key = str(
                binding_metadata.get("active_workspace_id") or binding_metadata.get("workspace_id") or ""
            ).strip()
            resolver = getattr(core_services.workspace, "get_by_workspace_id", None)
            if active_workspace_key and callable(resolver):
                active_workspace_row = core_services.workspace.get_by_workspace_id(active_workspace_key)
        return home_workspace_row, active_workspace_row or home_workspace_row

    def _record_context_pool_message(self, core_services, *, message, thread_row, session_row, active_workspace_row, home_workspace_row) -> None:
        context_pool = getattr(core_services, "context_pool", None)
        if context_pool is None:
            return
        try:
            context_pool.record_message(
                principal_id=thread_row.principal_id,
                message=message,
                thread=thread_row,
                session=session_row,
                active_workspace=active_workspace_row,
                home_workspace=home_workspace_row,
                metadata={"source": "assistant.message"},
            )
        except Exception:
            return

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
        gateway, _, thread_row, _, _, publish_session_id = self._resolve_thread_context(session_id)
        if gateway is None or thread_row is None:
            return
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="message.delta",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": publish_session_id or session_id,
                "stream_id": stream_id,
                "turn_id": turn_id,
                "delta": delta,
            },
        )

    async def publish_runtime_state(self, session_id: str, snapshot: dict[str, Any], *, turn_id: str = "") -> None:
        gateway, _, thread_row, _, _, _ = self._resolve_thread_context(session_id)
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
        gateway, _, thread_row, _, _, _ = self._resolve_thread_context(session_id)
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
        gateway, _, thread_row, _, _, _ = self._resolve_thread_context(session_id)
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
        gateway, _, thread_row, _, _, _ = self._resolve_thread_context(session_id)
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
        gateway, core_services, thread_row, session_row, binding_metadata, publish_session_id = self._resolve_thread_context(
            session_id
        )
        if gateway is None or core_services is None or thread_row is None:
            return
        home_workspace_row, workspace_row = self._resolve_workspace_rows(
            core_services,
            thread_row=thread_row,
            session_row=session_row,
            binding_metadata=binding_metadata,
        )
        workspace_id = getattr(workspace_row, "workspace_id", "")
        if session_row is not None:
            message = core_services.message.create_message(
                thread_id=thread_row.id,
                session_id=session_row.id,
                role="assistant",
                content=content,
                status="completed",
                active_workspace_id=getattr(workspace_row, "id", None),
                meta={
                    "turn_id": turn_id,
                    "stream_id": stream_id,
                    "home_workspace_id": getattr(home_workspace_row, "workspace_id", ""),
                    "active_workspace_id": workspace_id,
                    "workspace_id": workspace_id,
                },
            )
            self._record_context_pool_message(
                core_services,
                message=message,
                thread_row=thread_row,
                session_row=session_row,
                active_workspace_row=workspace_row,
                home_workspace_row=home_workspace_row,
            )
            message_payload = {
                "message_id": message.message_id,
                "thread_id": thread_row.thread_id,
                "session_id": publish_session_id or session_id,
                "active_workspace_id": workspace_id,
                "workspace_id": workspace_id,
                "client_id": "",
                "role": message.role,
                "content": message.content,
                "status": message.status,
                "channel": message.channel,
                "created_at": message.created_at.isoformat() if getattr(message, "created_at", None) is not None else "",
            }
        else:
            message_payload = {
                "message_id": f"msg_transient_{uuid4().hex}",
                "thread_id": thread_row.thread_id,
                "session_id": publish_session_id or session_id,
                "active_workspace_id": workspace_id,
                "workspace_id": workspace_id,
                "client_id": str(binding_metadata.get("client_id") or ""),
                "role": "assistant",
                "content": content,
                "status": "completed",
                "channel": "message",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="message.completed",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": publish_session_id or session_id,
                "message": message_payload,
                "stream_id": stream_id,
                "turn_id": turn_id,
            },
        )

    async def publish_temporary_assistant_message(
        self,
        session_id: str,
        *,
        content: str,
        turn_id: str = "",
        stream_id: str = "",
    ) -> dict[str, Any]:
        return await self.publish_short_assistant_message(
            session_id,
            content=content,
            turn_id=turn_id,
            stream_id=stream_id,
        )

    async def publish_short_assistant_message(
        self,
        session_id: str,
        *,
        content: str,
        turn_id: str = "",
        stream_id: str = "",
    ) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            return {"delivered": False, "reason": "empty_content"}
        gateway, core_services, thread_row, session_row, binding_metadata, publish_session_id = self._resolve_thread_context(session_id)
        if gateway is None or core_services is None or thread_row is None:
            return {"delivered": False, "reason": "thread_unavailable"}
        home_workspace_row, workspace_row = self._resolve_workspace_rows(
            core_services,
            thread_row=thread_row,
            session_row=session_row,
            binding_metadata=binding_metadata,
        )
        workspace_id = getattr(workspace_row, "workspace_id", "")
        message_id = f"msg_short_{uuid4().hex}"
        effective_turn_id = str(turn_id or "").strip()
        effective_stream_id = str(stream_id or "").strip()
        payload_session_id = publish_session_id or session_id
        if session_row is not None:
            message = core_services.message.create_message(
                thread_id=thread_row.id,
                session_id=session_row.id,
                role="assistant",
                content=text,
                channel="short_reply",
                status="completed",
                active_workspace_id=getattr(workspace_row, "id", None),
                meta={
                    "short_reply": True,
                    "turn_id": effective_turn_id,
                    "stream_id": effective_stream_id,
                    "home_workspace_id": getattr(home_workspace_row, "workspace_id", ""),
                    "active_workspace_id": workspace_id,
                    "workspace_id": workspace_id,
                },
            )
            message_payload = {
                "message_id": message.message_id,
                "thread_id": thread_row.thread_id,
                "session_id": payload_session_id,
                "active_workspace_id": workspace_id,
                "workspace_id": workspace_id,
                "client_id": str(binding_metadata.get("client_id") or ""),
                "role": message.role,
                "content": message.content,
                "status": message.status,
                "channel": message.channel,
                "created_at": message.created_at.isoformat() if getattr(message, "created_at", None) is not None else "",
            }
            message_id = message.message_id
        else:
            message_payload = {
                "message_id": message_id,
                "thread_id": thread_row.thread_id,
                "session_id": payload_session_id,
                "active_workspace_id": workspace_id,
                "workspace_id": workspace_id,
                "client_id": str(binding_metadata.get("client_id") or ""),
                "role": "assistant",
                "content": text,
                "status": "completed",
                "channel": "short_reply",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        await gateway.publish_client_thread_event(
            thread_row.thread_id,
            event_type="message.created",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": payload_session_id,
                "message": message_payload,
            },
        )
        return {
            "delivered": True,
            "thread_id": thread_row.thread_id,
            "session_id": payload_session_id,
            "turn_id": effective_turn_id,
            "stream_id": effective_stream_id,
            "message_id": message_id,
        }

    async def publish_confirm_request(self, event, *, approval_context: dict[str, Any] | None = None) -> None:
        gateway, core_services, thread_row, _, _, _ = self._resolve_thread_context(event.session_id)
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
        gateway, _, thread_row, _, _, _ = self._resolve_thread_context(session_id)
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
        gateway, _, thread_row, _, _, _ = self._resolve_thread_context(event.session_id)
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
        gateway, _, thread_row, _, _, _ = self._resolve_thread_context(session_id)
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
        gateway, _, thread_row, _, _, _ = self._resolve_thread_context(session_id)
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
