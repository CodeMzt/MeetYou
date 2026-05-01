"""
Bridge Core runtime events to Thread / Run / Delivery surfaces.
"""

from __future__ import annotations

import logging
from typing import Any, Callable
from uuid import uuid4


logger = logging.getLogger("meetyou.core.thread_delivery_bridge")
MESSAGE_SESSION_CACHE_MAX = 512


class ThreadDeliveryBridge:
    def __init__(
        self,
        *,
        gateway_getter: Callable[[], Any],
        core_services_getter: Callable[[], Any],
    ) -> None:
        self._gateway_getter = gateway_getter
        self._core_services_getter = core_services_getter
        self._stream_runs: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self._message_sessions: dict[tuple[str, str, str], Any] = {}

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
        except Exception as exc:
            logger.warning("Context pool message record failed: %s", exc)
            return

    async def _publish_thread_event(self, gateway, thread_id: str, *, event_type: str, payload: dict[str, Any]) -> None:
        publisher = getattr(gateway, "publish_thread_delivery_event", None)
        if callable(publisher):
            await publisher(thread_id, event_type=event_type, payload=payload)
            return

    @staticmethod
    def _supports_run_event_log(core_services) -> bool:
        return all(hasattr(core_services, name) for name in ("actor", "run", "run_event"))

    @staticmethod
    def _public_run_event_payload(
        *,
        event,
        run,
        thread_row,
        session_id: str,
        turn_id: str,
        stream_id: str,
    ) -> dict[str, Any]:
        return {
            "event_id": getattr(event, "event_id", ""),
            "run_id": getattr(run, "run_id", ""),
            "thread_id": getattr(thread_row, "thread_id", ""),
            "session_id": session_id,
            "seq": getattr(event, "seq", 0),
            "type": getattr(event, "type", ""),
            "payload": dict(getattr(event, "payload", {}) or {}),
            "durable": bool(getattr(event, "durable", True)),
            "turn_id": turn_id,
            "stream_id": stream_id,
            "created_at": getattr(getattr(event, "created_at", None), "isoformat", lambda: "")(),
        }

    def _ensure_runtime_actor(self, core_services):
        actor_service = getattr(core_services, "actor", None)
        if actor_service is None:
            return None
        actor = actor_service.get_by_actor_id("system.maintenance")
        if actor is not None:
            return actor
        ensure_actor = getattr(actor_service, "ensure_actor", None)
        if not callable(ensure_actor):
            return None
        return ensure_actor(
            actor_id="system.maintenance",
            actor_type="system_maintenance",
            display_name="System Maintenance",
            permission_profile_id="profile.system_maintenance",
        )

    def _stream_run_key(self, *, thread_row, session_id: str, turn_id: str, stream_id: str) -> tuple[str, str, str, str]:
        return (
            str(getattr(thread_row, "thread_id", "") or ""),
            str(session_id or ""),
            str(turn_id or ""),
            str(stream_id or ""),
        )

    def _get_or_create_stream_run(
        self,
        core_services,
        *,
        thread_row,
        workspace_row,
        session_id: str,
        turn_id: str,
        stream_id: str,
    ):
        if not self._supports_run_event_log(core_services):
            return None
        key = self._stream_run_key(thread_row=thread_row, session_id=session_id, turn_id=turn_id, stream_id=stream_id)
        cached = self._stream_runs.get(key)
        get_by_id = getattr(core_services.run, "get_by_id", None)
        if cached and callable(get_by_id):
            run = get_by_id(cached.get("row_id"))
            if run is not None:
                return run
        actor = self._ensure_runtime_actor(core_services)
        create_run = getattr(core_services.run, "create_run", None)
        if actor is None or not callable(create_run):
            return None
        workspace_row_id = getattr(workspace_row, "id", None) or getattr(thread_row, "workspace_id", None)
        if workspace_row_id is None:
            return None
        run = create_run(
            workspace_id=workspace_row_id,
            thread_id=getattr(thread_row, "id", None),
            trigger_type="assistant_turn",
            origin_actor_id=getattr(actor, "id", None),
            status="running",
            input={
                "runtime_action": "assistant.streaming",
                "session_id": session_id,
                "turn_id": turn_id,
                "stream_id": stream_id,
            },
        )
        self._stream_runs[key] = {"row_id": getattr(run, "id", None), "run_id": getattr(run, "run_id", "")}
        return run

    async def _append_stream_run_event(
        self,
        gateway,
        core_services,
        *,
        thread_row,
        workspace_row,
        session_id: str,
        turn_id: str,
        stream_id: str,
        event_type: str,
        payload: dict[str, Any],
        durable: bool,
        finalize_run: bool = False,
        run_output: dict[str, Any] | None = None,
    ) -> bool:
        run = self._get_or_create_stream_run(
            core_services,
            thread_row=thread_row,
            workspace_row=workspace_row,
            session_id=session_id,
            turn_id=turn_id,
            stream_id=stream_id,
        )
        if run is None:
            return False
        append_event = getattr(core_services.run_event, "append_event", None)
        if not callable(append_event):
            return False
        event = append_event(
            run_id=getattr(run, "id", None),
            thread_id=getattr(thread_row, "id", None),
            type=event_type,
            payload=dict(payload or {}),
            durable=durable,
        )
        event_payload = self._public_run_event_payload(
            event=event,
            run=run,
            thread_row=thread_row,
            session_id=session_id,
            turn_id=turn_id,
            stream_id=stream_id,
        )
        publish_endpoint_run_event = getattr(gateway, "publish_endpoint_run_event", None)
        if callable(publish_endpoint_run_event):
            await publish_endpoint_run_event(
                thread_id=getattr(thread_row, "thread_id", ""),
                run_id=getattr(run, "run_id", ""),
                event=event_payload,
            )
        else:
            await self._publish_thread_event(
                gateway,
                getattr(thread_row, "thread_id", ""),
                event_type=event_type,
                payload=event_payload,
            )
        if finalize_run:
            update_status = getattr(core_services.run, "update_status", None)
            if callable(update_status):
                update_status(run_row_id=getattr(run, "id", None), status="succeeded", output=dict(run_output or {}))
            self._stream_runs.pop(
                self._stream_run_key(thread_row=thread_row, session_id=session_id, turn_id=turn_id, stream_id=stream_id),
                None,
            )
        return True

    def _ensure_message_session(self, core_services, *, thread_row, session_row, workspace_row, binding_metadata: dict[str, Any]):
        if session_row is not None:
            return session_row
        session_service = getattr(core_services, "session", None)
        create_session = getattr(session_service, "create_session", None)
        if not callable(create_session):
            return None
        endpoint_row_id = None
        endpoint_key = str(binding_metadata.get("endpoint_id") or binding_metadata.get("origin_endpoint_id") or "").strip()
        cache_key = (
            str(getattr(thread_row, "thread_id", "") or ""),
            str(binding_metadata.get("bridged_session_id") or ""),
            endpoint_key,
        )
        cached_session = self._message_sessions.get(cache_key)
        if cached_session is not None:
            return cached_session
        endpoint_service = getattr(core_services, "endpoint", None)
        get_endpoint = getattr(endpoint_service, "get_by_endpoint_id", None)
        if endpoint_key and callable(get_endpoint):
            endpoint = get_endpoint(endpoint_key)
            endpoint_row_id = getattr(endpoint, "id", None) if endpoint is not None else None
        created = create_session(
            thread_id=getattr(thread_row, "id", None),
            origin_endpoint_id=endpoint_row_id,
            workspace_id=getattr(workspace_row, "id", None) or getattr(thread_row, "workspace_id", None),
        )
        self._message_sessions[cache_key] = created
        while len(self._message_sessions) > MESSAGE_SESSION_CACHE_MAX:
            self._message_sessions.pop(next(iter(self._message_sessions)))
        return created

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
        payload = {
            "thread_id": thread_id,
            "workspace_id": str(metadata.get("workspace_id") or ""),
            "operation_id": operation.operation_id,
            "title": operation.title,
            "operation_type": operation.operation_type,
            "execution_target": operation.execution_target,
            "execution_target_id": str(getattr(operation, "execution_target_id", "") or metadata.get("execution_target_id") or ""),
            "target_endpoint_id": str(metadata.get("target_endpoint_id") or metadata.get("execution_target_id") or ""),
            "tool_key": str(metadata.get("preferred_tool_key") or metadata.get("tool_key") or ""),
            "tool_id": str(metadata.get("tool_id") or metadata.get("capability_id") or ""),
            "status": operation.status,
            "phase": phase,
            "detail": detail,
            "routing_reason": str(metadata.get("routing_reason") or ""),
            **({"error": dict(error)} if isinstance(error, dict) else {}),
        }
        publish_operation_update = getattr(gateway, "publish_endpoint_operation_update", None)
        if callable(publish_operation_update):
            await publish_operation_update(thread_id=thread_id, operation_id=operation.operation_id, payload=payload)

    async def publish_message_delta(self, session_id: str, *, stream_id: str, turn_id: str, delta: str) -> None:
        if not delta:
            return
        gateway, core_services, thread_row, session_row, binding_metadata, publish_session_id = self._resolve_thread_context(session_id)
        if gateway is None or thread_row is None:
            return
        payload_session_id = publish_session_id or session_id
        if core_services is not None:
            _, workspace_row = self._resolve_workspace_rows(
                core_services,
                thread_row=thread_row,
                session_row=session_row,
                binding_metadata=binding_metadata,
            )
            session_row = self._ensure_message_session(
                core_services,
                thread_row=thread_row,
                session_row=session_row,
                workspace_row=workspace_row,
                binding_metadata=binding_metadata,
            )
            if session_row is not None:
                payload_session_id = str(getattr(session_row, "session_id", "") or payload_session_id)
            persisted = await self._append_stream_run_event(
                gateway,
                core_services,
                thread_row=thread_row,
                workspace_row=workspace_row,
                session_id=payload_session_id,
                turn_id=turn_id,
                stream_id=stream_id,
                event_type="message.delta",
                payload={
                    "thread_id": thread_row.thread_id,
                    "session_id": payload_session_id,
                    "stream_id": stream_id,
                    "turn_id": turn_id,
                    "delta": delta,
                },
                durable=False,
            )
            if persisted:
                return
        await self._publish_thread_event(
            gateway,
            thread_row.thread_id,
            event_type="message.delta",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": payload_session_id,
                "stream_id": stream_id,
                "turn_id": turn_id,
                "delta": delta,
            },
        )

    async def publish_runtime_state(self, session_id: str, snapshot: dict[str, Any], *, turn_id: str = "") -> None:
        gateway, _, thread_row, _, _, _ = self._resolve_thread_context(session_id)
        if gateway is None or thread_row is None:
            return
        await self._publish_thread_event(
            gateway,
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
        await self._publish_thread_event(
            gateway,
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
        await self._publish_thread_event(
            gateway,
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
        await self._publish_thread_event(
            gateway,
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
        session_row = self._ensure_message_session(
            core_services,
            thread_row=thread_row,
            session_row=session_row,
            workspace_row=workspace_row,
            binding_metadata=binding_metadata,
        )
        if session_row is not None:
            publish_session_id = str(getattr(session_row, "session_id", "") or publish_session_id or session_id)
            origin_endpoint_public_id = str(binding_metadata.get("endpoint_id") or "")
            endpoint_service = getattr(core_services, "endpoint", None)
            get_endpoint_by_id = getattr(endpoint_service, "get_by_id", None)
            origin_endpoint_row_id = getattr(session_row, "origin_endpoint_id", None)
            if origin_endpoint_row_id is not None and callable(get_endpoint_by_id):
                endpoint_row = get_endpoint_by_id(origin_endpoint_row_id)
                origin_endpoint_public_id = str(getattr(endpoint_row, "endpoint_id", "") or origin_endpoint_public_id)
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
                "origin_endpoint_id": origin_endpoint_public_id,
                "role": message.role,
                "content": message.content,
                "status": message.status,
                "channel": message.channel,
                "created_at": message.created_at.isoformat() if getattr(message, "created_at", None) is not None else "",
            }
        else:
            return
        completed_payload = {
            "thread_id": thread_row.thread_id,
            "session_id": publish_session_id or session_id,
            "message": message_payload,
            "stream_id": stream_id,
            "turn_id": turn_id,
        }
        persisted = await self._append_stream_run_event(
            gateway,
            core_services,
            thread_row=thread_row,
            workspace_row=workspace_row,
            session_id=publish_session_id or session_id,
            turn_id=turn_id,
            stream_id=stream_id,
            event_type="message.completed",
            payload=completed_payload,
            durable=True,
            finalize_run=True,
            run_output={"message_id": message_payload["message_id"], "finish_reason": "completed"},
        )
        publish_endpoint_message = getattr(gateway, "publish_endpoint_message", None)
        if callable(publish_endpoint_message):
            await publish_endpoint_message(thread_id=thread_row.thread_id, message=message_payload)
            return
        if persisted:
            await self._publish_thread_event(
                gateway,
                thread_row.thread_id,
                event_type="message",
                payload=message_payload,
            )
            return
        await self._publish_thread_event(
            gateway,
            thread_row.thread_id,
            event_type="message.completed",
            payload=completed_payload,
        )

    async def publish_progress_notice(
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
        effective_turn_id = str(turn_id or "").strip()
        effective_stream_id = str(stream_id or "").strip()
        payload_session_id = publish_session_id or session_id
        if not all(hasattr(core_services, name) for name in ("actor", "run", "run_event")):
            event_payload = {
                "event_id": f"evt_progress_{uuid4().hex}",
                "run_id": "",
                "thread_id": thread_row.thread_id,
                "session_id": payload_session_id,
                "seq": 0,
                "type": "assistant.progress_notice",
                "payload": {"text": text, "content": text},
                "durable": False,
                "turn_id": effective_turn_id,
                "stream_id": effective_stream_id,
            }
            await self._publish_thread_event(
                gateway,
                thread_row.thread_id,
                event_type="assistant.progress_notice",
                payload=event_payload,
            )
            return {
                "delivered": True,
                "thread_id": thread_row.thread_id,
                "session_id": payload_session_id,
                "turn_id": effective_turn_id,
                "stream_id": effective_stream_id,
                "event_id": event_payload["event_id"],
                "run_id": "",
            }
        actor = core_services.actor.get_by_actor_id("system.maintenance")
        if actor is None:
            actor = core_services.actor.ensure_actor(
                actor_id="system.maintenance",
                actor_type="system_maintenance",
                display_name="System Maintenance",
                permission_profile_id="profile.system_maintenance",
            )
        run = core_services.run.create_run(
            workspace_id=getattr(workspace_row, "id", None) or getattr(thread_row, "workspace_id", None),
            thread_id=thread_row.id,
            trigger_type="runtime_action",
            origin_actor_id=actor.id,
            status="running",
            input={
                "runtime_action": "assistant.progress_notice",
                "session_id": payload_session_id,
                "turn_id": effective_turn_id,
                "stream_id": effective_stream_id,
            },
        )
        event = core_services.run_event.emit_progress_notice(
            run_id=run.id,
            thread_id=thread_row.id,
            text=text,
            durable=False,
        )
        core_services.run.update_status(run_row_id=run.id, status="succeeded")
        event_payload = {
            "event_id": event.event_id,
            "run_id": run.run_id,
            "thread_id": thread_row.thread_id,
            "session_id": payload_session_id,
            "seq": event.seq,
            "type": event.type,
            "payload": dict(event.payload or {}),
            "durable": bool(event.durable),
            "turn_id": effective_turn_id,
            "stream_id": effective_stream_id,
        }
        publish_endpoint_run_event = getattr(gateway, "publish_endpoint_run_event", None)
        if callable(publish_endpoint_run_event):
            await publish_endpoint_run_event(thread_id=thread_row.thread_id, run_id=run.run_id, event=event_payload)
        else:
            await self._publish_thread_event(
            gateway,
                thread_row.thread_id,
                event_type="assistant.progress_notice",
                payload=event_payload,
            )
        return {
            "delivered": True,
            "thread_id": thread_row.thread_id,
            "session_id": payload_session_id,
            "turn_id": effective_turn_id,
            "stream_id": effective_stream_id,
            "event_id": event.event_id,
            "run_id": run.run_id,
        }

    async def publish_confirm_request(self, event, *, approval_context: dict[str, Any] | None = None) -> None:
        gateway, core_services, thread_row, _, _, _ = self._resolve_thread_context(event.session_id)
        if gateway is None or core_services is None or thread_row is None:
            return
        await self._publish_thread_event(
            gateway,
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
        await self._publish_thread_event(
            gateway,
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
        await self._publish_thread_event(
            gateway,
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
        await self._publish_thread_event(
            gateway,
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
        await self._publish_thread_event(
            gateway,
            thread_row.thread_id,
            event_type="control.updated",
            payload={
                "thread_id": thread_row.thread_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "control": dict(payload or {}),
            },
        )
