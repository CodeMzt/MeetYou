"""
Legacy gateway migration surfaces isolated from the formal Runtime routes.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketException, status


LEGACY_HTTP_SURFACE_HINTS = {
    "/inputs": {
        "replacement_path": "/runtime/messages",
        "message": "旧聊天输入入口 /inputs 已停止承载聊天流，请改用 /runtime/messages。",
    },
    "/controls": {
        "replacement_path": "/runtime/*",
        "message": "旧控制入口 /controls 已停止承载聊天流，请改用 /runtime/messages、/runtime/operations 或 /runtime/sessions/{session_id}/*。",
    },
    "/session": {
        "replacement_path": "/runtime/sessions",
        "message": "旧会话入口 /session 已停止承载聊天流，请改用 /runtime/sessions。",
    },
    "/sessions": {
        "replacement_path": "/runtime/sessions",
        "message": "根路径 /sessions 已不再是正式会话入口，请改用 /runtime/sessions。",
    },
    "/messages": {
        "replacement_path": "/runtime/messages",
        "message": "根路径 /messages 已不再是正式消息入口，请改用 /runtime/messages。",
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

    async def removed_client_http_surface(request: Request):
        gateway._require_http_auth(request)  # noqa: SLF001
        gateway._raise_legacy_http_surface_removed(  # noqa: SLF001
            legacy_path=str(request.url.path),
            replacement_path="/runtime/*",
            message="V4 已移除 /client/* HTTP 入口，请改用 /runtime/*。",
        )

    app.add_api_route(
        "/client/{legacy_path:path}",
        removed_client_http_surface,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        del websocket
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Root /ws is removed in V4; use /endpoint/ws.",
        )

    @app.websocket("/client/ws")
    async def client_websocket_endpoint(websocket: WebSocket):
        del websocket
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="V4 removed /client/ws; use /endpoint/ws.",
        )
