from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from core.status import utcnow_iso


class ToolSourceType(str, Enum):
    BUILTIN = "builtin"
    MCP = "mcp"
    UNKNOWN = "unknown"


class ToolContentKind(str, Enum):
    JSON = "json"
    TEXT = "text"
    EMPTY = "empty"


class ToolErrorCategory(str, Enum):
    PERMISSION = "permission"
    VALIDATION = "validation"
    TIMEOUT = "timeout"
    DEPENDENCY = "dependency"
    EXECUTION = "execution"
    NOT_FOUND = "not_found"


class ToolCallContent(BaseModel):
    kind: str = ToolContentKind.EMPTY.value
    text: str = ""
    data: Any = None


class ToolCallError(BaseModel):
    code: str
    category: str = ToolErrorCategory.EXECUTION.value
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: str = Field(default_factory=utcnow_iso)


class ToolCallResult(BaseModel):
    tool_name: str
    ok: bool
    source: str = ToolSourceType.UNKNOWN.value
    action_risk: str = "read"
    content: ToolCallContent = Field(default_factory=ToolCallContent)
    error: ToolCallError | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def as_message_content(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, default=str)

    @classmethod
    def success(
        cls,
        *,
        tool_name: str,
        source: str | ToolSourceType,
        action_risk: str,
        raw_output: Any,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolCallResult":
        resolved_source = source.value if isinstance(source, ToolSourceType) else str(source)
        return cls(
            tool_name=tool_name,
            ok=True,
            source=resolved_source,
            action_risk=action_risk,
            content=normalize_tool_output(raw_output),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def failure(
        cls,
        *,
        tool_name: str,
        source: str | ToolSourceType,
        action_risk: str,
        code: str,
        category: str | ToolErrorCategory,
        message: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolCallResult":
        resolved_source = source.value if isinstance(source, ToolSourceType) else str(source)
        resolved_category = category.value if isinstance(category, ToolErrorCategory) else str(category)
        return cls(
            tool_name=tool_name,
            ok=False,
            source=resolved_source,
            action_risk=action_risk,
            content=ToolCallContent(),
            error=ToolCallError(
                code=code,
                category=resolved_category,
                message=message,
                retryable=retryable,
                details=dict(details or {}),
            ),
            metadata=dict(metadata or {}),
        )


class ToolExecutionCapability(BaseModel):
    tool_name: str
    source: str = ToolSourceType.UNKNOWN.value
    action_risk: str = "read"
    safe_parallel: bool = False
    parallel_group: str = "default"
    resource_key: str = ""
    mutates_state: bool = False
    requires_order: bool = True
    max_concurrency: int | None = 1
    requires_approval: bool = False


def normalize_tool_output(raw_output: Any) -> ToolCallContent:
    if isinstance(raw_output, ToolCallContent):
        return raw_output
    if raw_output is None:
        return ToolCallContent()
    if isinstance(raw_output, (dict, list, int, float, bool)):
        text = json.dumps(raw_output, ensure_ascii=False, default=str)
        return ToolCallContent(
            kind=ToolContentKind.JSON.value,
            text=text,
            data=raw_output,
        )
    if isinstance(raw_output, str):
        text = raw_output.strip()
        if not text:
            return ToolCallContent()
        try:
            data = json.loads(raw_output)
        except (json.JSONDecodeError, TypeError):
            return ToolCallContent(
                kind=ToolContentKind.TEXT.value,
                text=raw_output,
            )
        return ToolCallContent(
            kind=ToolContentKind.JSON.value,
            text=raw_output,
            data=data,
        )
    return ToolCallContent(
        kind=ToolContentKind.TEXT.value,
        text=str(raw_output),
    )


def normalize_tool_result(
    raw_result: Any,
    *,
    tool_name: str,
    source: str | ToolSourceType = ToolSourceType.UNKNOWN.value,
    action_risk: str = "read",
    metadata: dict[str, Any] | None = None,
) -> ToolCallResult:
    if isinstance(raw_result, ToolCallResult):
        return raw_result
    if isinstance(raw_result, dict) and {"tool_name", "ok"}.issubset(raw_result.keys()):
        try:
            return ToolCallResult.model_validate(raw_result)
        except Exception:
            pass
    return ToolCallResult.success(
        tool_name=tool_name,
        source=source,
        action_risk=action_risk,
        raw_output=raw_result,
        metadata=metadata,
    )
