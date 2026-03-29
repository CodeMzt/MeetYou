"""
网关请求响应模型。
"""

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
