from __future__ import annotations

from fastapi import APIRouter, Request

from gateway.models import RuntimeEnvelopePayload, RuntimeEnvelopeResponse


def build_developer_router(gateway) -> APIRouter:
    router = APIRouter(prefix="/developer", tags=["developer"])

    @router.get("/runtime/debug", response_model=RuntimeEnvelopeResponse)
    async def developer_runtime_debug(request: Request, session_id: str):
        gateway._require_http_auth(request)
        if gateway._dependencies.runtime_debug_getter is None:
            gateway._raise_http_error(status_code=404, code="runtime_debug_not_found", message="调试服务未启用")
        payload = await gateway._resolve(gateway._dependencies.runtime_debug_getter, session_id=session_id)
        return RuntimeEnvelopeResponse(
            schema_name="meetyou.http.v1",
            runtime=RuntimeEnvelopePayload(
                resource="debug",
                session_id=str(payload.get("session_id") or session_id),
                debug=dict(payload or {}),
            ),
        )

    return router
