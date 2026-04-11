from __future__ import annotations

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import ValidationError

from gateway.agent_protocol import (
    AGENT_WS_SCHEMA,
    AgentCapabilitiesSnapshotPayload,
    AgentEnvelope,
    AgentHeartbeatPayload,
    AgentHelloPayload,
    CapabilityCallAcceptedPayload,
    CapabilityCallErrorPayload,
    CapabilityCallProgressPayload,
    CapabilityCallResultPayload,
    build_agent_envelope,
)
from service_runtime.models import RuntimeError


def _workspace_title(workspace_id: str) -> str:
    cleaned = str(workspace_id or "").strip()
    return cleaned.replace("-", " ").replace("_", " ").title() or "Workspace"


def build_agent_router(gateway) -> APIRouter:
    router = APIRouter(prefix="/agent", tags=["agent"])

    async def publish_operation_update(domain, call_row, *, event_type: str, payload: dict):
        operation = domain.services.operation.get_by_id(call_row.operation_id)
        if operation is None:
            return
        thread = domain.services.thread.get_by_id(operation.thread_id)
        if thread is None:
            return
        await gateway.publish_client_thread_event(
            thread.thread_id,
            event_type=event_type,
            payload={
                "thread_id": thread.thread_id,
                "operation_id": operation.operation_id,
                **dict(payload or {}),
            },
        )

    @router.websocket("/ws")
    async def agent_websocket_endpoint(websocket: WebSocket):
        if not await gateway._authorize_agent_websocket(websocket):
            return
        await websocket.accept()
        domain = gateway._require_core_domain()
        current_agent = None
        bound_agent_id = ""

        try:
            while True:
                try:
                    envelope = AgentEnvelope.model_validate(await websocket.receive_json())
                except WebSocketDisconnect:
                    break
                except ValidationError as exc:
                    sent = await gateway._safe_send_json(
                        websocket,
                        {
                            "schema": AGENT_WS_SCHEMA,
                            "kind": "error",
                            "error": RuntimeError(
                                code="invalid_agent_payload",
                                category="validation",
                                message=str(exc),
                            ).model_dump(),
                        },
                    )
                    if not sent:
                        break
                    continue

                if envelope.schema_name != AGENT_WS_SCHEMA:
                    sent = await gateway._safe_send_json(
                        websocket,
                        {
                            "schema": AGENT_WS_SCHEMA,
                            "kind": "error",
                            "error": RuntimeError(
                                code="invalid_agent_schema",
                                category="validation",
                                message=f"unsupported schema: {envelope.schema_name}",
                            ).model_dump(),
                        },
                    )
                    if not sent:
                        break
                    continue

                if bound_agent_id and envelope.agent_id != bound_agent_id:
                    sent = await gateway._safe_send_json(
                        websocket,
                        {
                            "schema": AGENT_WS_SCHEMA,
                            "kind": "error",
                            "error": RuntimeError(
                                code="agent_identity_mismatch",
                                category="validation",
                                message=f"当前连接已绑定 agent: {bound_agent_id}",
                            ).model_dump(),
                        },
                    )
                    if not sent:
                        break
                    continue

                if envelope.type != "agent.hello" and not bound_agent_id:
                    sent = await gateway._safe_send_json(
                        websocket,
                        {
                            "schema": AGENT_WS_SCHEMA,
                            "kind": "error",
                            "error": RuntimeError(
                                code="agent_hello_required",
                                category="validation",
                                message="agent websocket 必须先发送 agent.hello",
                            ).model_dump(),
                        },
                    )
                    if not sent:
                        break
                    continue

                if envelope.type == "agent.hello":
                    payload = AgentHelloPayload.model_validate(envelope.payload)
                    bound_agent_id = envelope.agent_id
                    owner_client = None
                    if payload.owner_client_id:
                        owner_client = domain.services.client.ensure_client(
                            client_id=payload.owner_client_id,
                            principal_id=domain.principal.id,
                            client_type=payload.owner_client_type or "electron",
                            display_name=payload.owner_client_display_name or payload.owner_client_id,
                        )
                    workspace_rows = []
                    for workspace_id in payload.workspace_ids:
                        workspace_rows.append(
                            domain.services.workspace.ensure_workspace(
                                workspace_id=workspace_id,
                                principal_id=domain.principal.id,
                                title=_workspace_title(workspace_id),
                                base_mode="automation" if workspace_id == "desktop-main" else "general",
                            )
                        )
                    current_agent = domain.services.agent.register_agent(
                        principal_id=domain.principal.id,
                        agent_id=envelope.agent_id,
                        agent_type=payload.agent_type,
                        display_name=payload.display_name,
                        transport_profile=payload.transport_profile,
                        workspace_rows=workspace_rows,
                        host_name=str(payload.host.get("hostname") or ""),
                        host_os=str(payload.host.get("os") or ""),
                        host_arch=str(payload.host.get("arch") or ""),
                        supports_offline_cache=payload.supports_offline_cache,
                        owner_client_id=getattr(owner_client, "id", None),
                        meta={"last_hello": envelope.model_dump()},
                    )
                    await gateway.agent_ws_manager.connect(current_agent.agent_id, websocket)
                    sent = await gateway._safe_send_json(
                        websocket,
                        build_agent_envelope(
                            envelope_type="agent.hello.ack",
                            agent_id=envelope.agent_id,
                            message_id=f"ack-{envelope.message_id}",
                            correlation_id=envelope.message_id,
                            payload={
                                "accepted": True,
                                "registered_agent_id": envelope.agent_id,
                                "requires_capability_snapshot": True,
                                "heartbeat_interval_seconds": 20,
                            },
                        ),
                    )
                    if not sent:
                        break
                    continue

                if envelope.type == "agent.capabilities.snapshot":
                    payload = AgentCapabilitiesSnapshotPayload.model_validate(envelope.payload)
                    current_agent = current_agent or domain.services.agent.get_by_agent_id(envelope.agent_id)
                    if current_agent is None:
                        sent = await gateway._safe_send_json(
                            websocket,
                            {
                                "schema": AGENT_WS_SCHEMA,
                                "kind": "error",
                                "error": RuntimeError(
                                    code="agent_not_registered",
                                    message=f"未知 agent: {envelope.agent_id}",
                                ).model_dump(),
                            },
                        )
                        if not sent:
                            break
                        continue
                    workspace_bindings = domain.services.agent.list_workspaces(envelope.agent_id)
                    domain.services.capability.replace_agent_capabilities(
                        agent=current_agent,
                        capabilities=payload.capabilities,
                        workspace_rows=workspace_bindings,
                        revision=payload.revision,
                    )
                    domain.services.agent.store_capability_snapshot(
                        agent=current_agent,
                        revision=payload.revision,
                        status="active",
                        snapshot={"capabilities": payload.capabilities},
                    )
                    sent = await gateway._safe_send_json(
                        websocket,
                        build_agent_envelope(
                            envelope_type="agent.ready",
                            agent_id=envelope.agent_id,
                            message_id=f"ready-{envelope.message_id}",
                            correlation_id=envelope.message_id,
                            payload={
                                "accepted": True,
                                "registered_agent_id": envelope.agent_id,
                                "capability_count": len(payload.capabilities),
                                "revision": payload.revision,
                            },
                        ),
                    )
                    if not sent:
                        break
                    continue

                if envelope.type == "agent.heartbeat":
                    payload = AgentHeartbeatPayload.model_validate(envelope.payload)
                    domain.services.agent.record_heartbeat(
                        agent_id=envelope.agent_id,
                        status=payload.status,
                        metrics=payload.metrics,
                    )
                    continue

                if envelope.type == "capability.call.accepted":
                    payload = CapabilityCallAcceptedPayload.model_validate(envelope.payload)
                    call_row = domain.services.operation_call.mark_accepted(call_id=payload.call_id)
                    if call_row is not None:
                        await publish_operation_update(
                            domain,
                            call_row,
                            event_type="operation.updated",
                            payload={"call_id": payload.call_id, "status": "running", "phase": "accepted"},
                        )
                    continue

                if envelope.type == "capability.call.progress":
                    payload = CapabilityCallProgressPayload.model_validate(envelope.payload)
                    call_row = domain.services.operation_call.mark_progress(
                        call_id=payload.call_id,
                        detail=payload.detail,
                        metadata={"phase": payload.phase},
                    )
                    if call_row is not None:
                        await publish_operation_update(
                            domain,
                            call_row,
                            event_type="operation.updated",
                            payload={
                                "call_id": payload.call_id,
                                "status": "running",
                                "phase": payload.phase,
                                "detail": payload.detail,
                            },
                        )
                    continue

                if envelope.type == "capability.call.result":
                    payload = CapabilityCallResultPayload.model_validate(envelope.payload)
                    result_payload = dict(payload.result or {})
                    if payload.attachment_outputs:
                        result_payload["attachment_outputs"] = domain.services.attachment.normalize_attachment_object_views(payload.attachment_outputs)
                    call_row = domain.services.operation_call.mark_succeeded(call_id=payload.call_id, result=result_payload)
                    await domain.agent_dispatch.notify_call_result(call_id=payload.call_id, result=result_payload)
                    if call_row is not None:
                        await publish_operation_update(
                            domain,
                            call_row,
                            event_type="operation.updated",
                            payload={
                                "call_id": payload.call_id,
                                "status": payload.status,
                                "result": result_payload,
                            },
                        )
                    continue

                if envelope.type == "capability.call.error":
                    payload = CapabilityCallErrorPayload.model_validate(envelope.payload)
                    call_row = domain.services.operation_call.mark_failed(call_id=payload.call_id, error=payload.error)
                    await domain.agent_dispatch.notify_call_error(call_id=payload.call_id, error=payload.error)
                    if call_row is not None:
                        await publish_operation_update(
                            domain,
                            call_row,
                            event_type="operation.updated",
                            payload={
                                "call_id": payload.call_id,
                                "status": payload.status,
                                "error": payload.error,
                            },
                        )
                    continue

                sent = await gateway._safe_send_json(
                    websocket,
                    {
                        "schema": AGENT_WS_SCHEMA,
                        "kind": "error",
                        "error": RuntimeError(
                            code="unsupported_agent_message",
                            category="validation",
                            message=f"不支持的 agent message type: {envelope.type}",
                        ).model_dump(),
                    },
                )
                if not sent:
                    break
        finally:
            if current_agent is not None:
                await gateway.agent_ws_manager.disconnect(current_agent.agent_id, websocket)
                domain.services.agent.record_heartbeat(agent_id=current_agent.agent_id, status="offline", metrics={})

    @router.post("/attachments/upload-ticket")
    async def create_agent_attachment_upload_ticket(request: Request, payload: dict):
        gateway._require_agent_http_auth(request)
        domain = gateway._require_core_domain()
        agent_id = str(payload.get("agent_id") or "").strip()
        owner_type = str(payload.get("owner_type") or "operation").strip() or "operation"
        owner_id = str(payload.get("owner_id") or "").strip()
        if not agent_id or not owner_id:
            gateway._raise_http_error(status_code=400, code="attachment_owner_required", message="agent_id 和 owner_id 为必填字段")
        agent = domain.services.agent.get_by_agent_id(agent_id)
        if agent is None:
            gateway._raise_http_error(status_code=404, code="agent_not_found", message=f"未知 agent: {agent_id}")
        attachment, ticket = domain.services.attachment.create_upload_ticket(
            owner_type=owner_type,
            owner_id=owner_id,
            issuer_type="agent",
            issuer_ref=agent_id,
            kind=str(payload.get("kind") or "file").strip() or "file",
            mime_type=str(payload.get("mime_type") or "application/octet-stream").strip() or "application/octet-stream",
            file_name=str(payload.get("file_name") or "").strip(),
            size_bytes=max(int(payload.get("size_bytes") or 0), 0),
            lifecycle_policy=str(payload.get("lifecycle_policy") or "normal").strip() or "normal",
            origin_agent_id=agent.id,
        )
        upload_url = str(request.base_url).rstrip("/") + f"/agent/attachments/upload/{ticket.ticket_id}"
        return {
            "attachment_id": attachment.attachment_id,
            "ticket_id": ticket.ticket_id,
            "upload_url": upload_url,
            "expires_at": ticket.expires_at,
            "object_key": attachment.object_key,
            "status": attachment.status,
        }

    @router.put("/attachments/upload/{ticket_id}")
    async def upload_agent_attachment_content(ticket_id: str, request: Request):
        gateway._require_agent_http_auth(request)
        domain = gateway._require_core_domain()
        body = await request.body()
        try:
            attachment = domain.services.attachment.store_upload_content(ticket_id, body)
        except ValueError as exc:
            gateway._raise_http_error(status_code=409, code=str(exc), message=str(exc))
        return {
            "attachment_id": attachment.attachment_id,
            "ticket_id": ticket_id,
            "status": attachment.status,
            "size_bytes": attachment.size_bytes,
            "sha256": attachment.sha256,
        }

    @router.post("/attachments/{attachment_id}/complete")
    async def complete_agent_attachment(attachment_id: str, request: Request, payload: dict):
        gateway._require_agent_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            attachment = domain.services.attachment.complete_attachment(
                attachment_id=attachment_id,
                ticket_id=str(payload.get("ticket_id") or "").strip(),
                sha256=str(payload.get("sha256") or "").strip(),
                size_bytes=payload.get("size_bytes"),
            )
        except ValueError as exc:
            gateway._raise_http_error(status_code=409, code=str(exc), message=str(exc))
        return {
            **domain.services.attachment.build_attachment_object_view(attachment),
            "sha256": attachment.sha256,
        }

    @router.get("/attachments/content/{attachment_id}")
    async def download_agent_attachment_content(attachment_id: str, request: Request, ticket_id: str):
        gateway._require_agent_http_auth(request)
        domain = gateway._require_core_domain()
        try:
            attachment = domain.services.attachment.validate_download_ticket(attachment_id=attachment_id, ticket_id=ticket_id)
            content = domain.services.attachment.read_attachment_bytes(attachment_id)
        except ValueError as exc:
            gateway._raise_http_error(status_code=404, code=str(exc), message=str(exc))
        file_name = str((getattr(attachment, "meta", {}) or {}).get("file_name") or attachment.attachment_id)
        return Response(
            content=content,
            media_type=attachment.mime_type,
            headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
        )

    return router
