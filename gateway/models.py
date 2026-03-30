"""
网关请求响应模型。
"""

from typing import Any

from pydantic import BaseModel, Field


class InputRequest(BaseModel):
    content: str
    session_id: str | None = None
    source_id: str = "web-client"
    role: str = "user"
    metadata: dict = Field(default_factory=dict)


class InputAcceptedResponse(BaseModel):
    accepted: bool = True
    session_id: str
    event_id: str


class HealthResponse(BaseModel):
    status: str = "ok"


class WebSocketCommand(BaseModel):
    action: str
    request_id: str | None = None
    accepted: bool | None = None
    metadata: dict = Field(default_factory=dict)


class ConfigEntryResponse(BaseModel):
    key: str
    value: Any = None
    is_secret: bool = False
    has_value: bool = False
    source: str = "default"
    env_key: str | None = None


class ConfigSnapshotResponse(BaseModel):
    items: dict[str, ConfigEntryResponse]


class ConfigPatchRequest(BaseModel):
    updates: dict[str, Any] = Field(default_factory=dict)


class ConfigPatchResponse(BaseModel):
    applied_keys: list[str] = Field(default_factory=list)
    reloaded_components: list[str] = Field(default_factory=list)
    restart_required_keys: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
