from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from build_info import load_build_info
from gateway.models import RuntimeEnvelopePayload, RuntimeEnvelopeResponse
from gateway.serialization import make_json_safe


def build_developer_router(gateway) -> APIRouter:
    router = APIRouter(prefix="/developer", tags=["developer"])

    core_build_info = load_build_info(
        Path(__file__).resolve().parents[2] / "core" / "build_info.json",
        component="core",
        package_version="0.0.0",
    )

    @router.get("/runtime/debug", response_model=RuntimeEnvelopeResponse)
    async def developer_runtime_debug(request: Request, session_id: str):
        gateway._require_http_auth(request)
        if gateway._dependencies.runtime_debug_getter is None:
            gateway._raise_http_error(status_code=404, code="runtime_debug_not_found", message="调试服务未启用")
        try:
            payload = await gateway._resolve(gateway._dependencies.runtime_debug_getter, session_id=session_id)
        except Exception as exc:
            gateway._raise_http_error(
                status_code=404,
                code="runtime_debug_not_found",
                message=str(exc),
                details={"session_id": session_id},
            )
        return RuntimeEnvelopeResponse(
            schema_name="meetyou.http.v1",
            runtime=RuntimeEnvelopePayload(
                resource="debug",
                session_id=str(payload.get("session_id") or session_id),
                debug=make_json_safe(dict(payload or {})),
                metadata={"build_info": core_build_info},
            ),
        )

    return router
