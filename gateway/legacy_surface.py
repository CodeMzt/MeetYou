"""
Legacy gateway migration surfaces isolated from the formal client/agent routes.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, WebSocket, status


LEGACY_HTTP_SURFACE_HINTS = {
    "/inputs": {
        "replacement_path": "/client/messages",
        "message": "旧聊天输入入口 /inputs 已停止承载聊天流，请改用 /client/messages。",
    },
    "/controls": {
        "replacement_path": "/client/*",
        "message": "旧控制入口 /controls 已停止承载聊天流，请改用 /client/messages、/client/operations 或 /client/sessions/{session_id}/*。",
    },
    "/session": {
        "replacement_path": "/client/sessions",
        "message": "旧会话入口 /session 已停止承载聊天流，请改用 /client/sessions。",
    },
    "/sessions": {
        "replacement_path": "/client/sessions",
        "message": "根路径 /sessions 已不再是正式会话入口，请改用 /client/sessions。",
    },
    "/messages": {
        "replacement_path": "/client/messages",
        "message": "根路径 /messages 已不再是正式消息入口，请改用 /client/messages。",
    },
}


def register_legacy_gateway_surface(app: FastAPI, gateway: Any) -> None:
    def _legacy_http_route_handler(legacy_path: str):
        async def handler(request: Request):
            gateway._require_http_auth(request)  # noqa: SLF001
            hint = LEGACY_HTTP_SURFACE_HINTS[legacy_path]
            gateway._raise_legacy_http_surface_removed(  # noqa: SLF001
                legacy_path=legacy_path,
                replacement_path=hint["replacement_path"],
                message=hint["message"],
            )

        return handler

    for legacy_path, route_config in (
        ("/inputs", {"methods": ["POST"]}),
        ("/controls", {"methods": ["POST"]}),
        ("/session", {"methods": ["GET", "POST"]}),
        ("/sessions", {"methods": ["GET", "POST"]}),
        ("/messages", {"methods": ["POST"]}),
    ):
        app.add_api_route(
            legacy_path,
            _legacy_http_route_handler(legacy_path),
            methods=route_config["methods"],
            include_in_schema=False,
        )

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        if not await gateway._authorize_websocket(websocket):  # noqa: SLF001
            return
        await gateway._send_ws_error_and_close(  # noqa: SLF001
            websocket,
            code="legacy_websocket_path_removed",
            category="validation",
            message="根路径 /ws 已停止承载聊天流，请改用 /client/ws。",
            details={
                "legacy_path": "/ws",
                "replacement_path": "/client/ws",
                "required_query": ["thread_id"],
            },
            close_code=4404,
        )
