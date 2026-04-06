"""
网关请求响应模型。
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from service_runtime.models import RuntimeError, RuntimeHealth


class ThinkingOptions(BaseModel):
    enabled: bool | None = None
    effort: str | None = None
    budget_tokens: int | None = None


class InputOptions(BaseModel):
    thinking: ThinkingOptions | None = None


class InputRequest(BaseModel):
    content: str
    session_id: str | None = None
    source_id: str = "web-client"
    client_message_id: str | None = None
    role: str = "user"
    preferred_mode: str | None = None
    metadata: dict = Field(default_factory=dict)
    options: InputOptions | None = None


class InputAcceptedResponse(BaseModel):
    accepted: bool = True
    session_id: str
    event_id: str


class HealthResponse(RuntimeHealth):
    pass


class AckPayload(BaseModel):
    action: str
    accepted: bool = True
    session_id: str = ""
    event_id: str = ""
    request_id: str = ""
    status: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class AckResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_name: str = Field(default="meetyou.http.v1", alias="schema")
    kind: str = "ack"
    ack: AckPayload


class ErrorResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_name: str = Field(default="meetyou.http.v1", alias="schema")
    kind: str = "error"
    error: RuntimeError


class HealthEnvelopeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_name: str = Field(default="meetyou.http.v1", alias="schema")
    kind: str = "health"
    health: HealthResponse


class WebSocketCommand(BaseModel):
    action: str
    request_id: str | None = None
    accepted: bool | None = None
    answer_text: str | None = None
    selected_option: str | None = None
    guidance: str | None = None
    checkpoint_id: str | None = None
    turn_id: str | None = None
    stream_id: str | None = None
    client_request_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class ControlRequest(BaseModel):
    action: str
    session_id: str | None = None
    source_id: str = "web-client"
    client_request_id: str | None = None
    guidance: str | None = None
    checkpoint_id: str | None = None
    turn_id: str | None = None
    stream_id: str | None = None
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


class SchemaOptionResponse(BaseModel):
    label: str
    value: str


class ConfigFieldSchemaResponse(BaseModel):
    key: str
    title: str
    description: str
    group: str
    input: str
    options: list[SchemaOptionResponse] = Field(default_factory=list)
    placeholder: str = ""
    advanced: bool = False


class ConfigGroupDefinitionResponse(BaseModel):
    key: str
    title: str
    description: str


class UiProtocolSchemaResponse(BaseModel):
    http_schema: str
    ws_schema: str
    ws_frame_kinds: list[str] = Field(default_factory=list)
    ws_event_types: list[str] = Field(default_factory=list)
    ws_runtime_resources: list[str] = Field(default_factory=list)
    runtime_statuses: list[str] = Field(default_factory=list)
    providers: list[SchemaOptionResponse] = Field(default_factory=list)
    thinking_efforts: list[SchemaOptionResponse] = Field(default_factory=list)
    config_groups: list[ConfigGroupDefinitionResponse] = Field(default_factory=list)
    config_fields: list[ConfigFieldSchemaResponse] = Field(default_factory=list)


class UiProtocolSchemaEnvelopeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_name: str = Field(default="meetyou.http.v1", alias="schema")
    kind: str = "schema"
    ui_schema: UiProtocolSchemaResponse


class ConfigPatchRequest(BaseModel):
    updates: dict[str, Any] = Field(default_factory=dict)


class ConfigPatchResponse(BaseModel):
    applied_keys: list[str] = Field(default_factory=list)
    reloaded_components: list[str] = Field(default_factory=list)
    restart_required_keys: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RuntimeStateSnapshotResponse(BaseModel):
    session_id: str = ""
    status: str = "idle"
    detail: str = ""
    active_tools: list[str] = Field(default_factory=list)
    current_mode: str = ""
    route_reason: str = ""
    action_risk: str = "read"
    source_profile: str = ""
    stream_id: str = ""
    turn_id: str = ""
    finish_reason: str = ""
    reply_control: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = ""


class RuntimeStateResponse(BaseModel):
    global_state: RuntimeStateSnapshotResponse
    heartbeat_state: RuntimeStateSnapshotResponse
    session_state: RuntimeStateSnapshotResponse | None = None


class ContextBreakdownResponse(BaseModel):
    system: int = 0
    history: int = 0
    tool_history: int = 0
    memory_context: int = 0
    policy: int = 0
    current_input: int = 0
    proprioception: int = 0
    total: int = 0


class UsageCountersResponse(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0


class SessionUsageTotalsResponse(UsageCountersResponse):
    turn_count: int = 0


class RuntimeUsageResponse(BaseModel):
    session_id: str
    usage_ready: bool = False
    context_limit_tokens: int = 0
    context_limit_source: str = ""
    context_limit_model: str = ""
    context_limit_confidence: str = ""
    current_context_tokens_estimated: int = 0
    context_breakdown: ContextBreakdownResponse
    last_turn_usage: UsageCountersResponse
    session_totals: SessionUsageTotalsResponse
    usage_source: str = "estimated"
    updated_at: str = ""


class RuntimeEnvelopePayload(BaseModel):
    resource: str
    session_id: str = ""
    state: RuntimeStateResponse | None = None
    usage: RuntimeUsageResponse | None = None
    debug: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    event_id: str = ""


class RuntimeEnvelopeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_name: str = Field(default="meetyou.http.v1", alias="schema")
    kind: str = "runtime"
    runtime: RuntimeEnvelopePayload


class MemoryViewScopeResponse(BaseModel):
    source_id: str = ""
    session_id: str = ""


class MemoryMetadataResponse(BaseModel):
    embedding_model: str = ""
    embedding_api_url: str = ""
    updated_at: str = ""


class WorkingSummariesResponse(BaseModel):
    global_summary: str = ""
    session_summary: str = ""
    session_id: str = ""


class MemoryRecordScopeResponse(BaseModel):
    user_id: str = ""
    session_id: str = ""


class MemoryRecordResponse(BaseModel):
    id: str
    type: str
    scope: MemoryRecordScopeResponse
    content: str = ""
    strength: float = 0.0
    importance: float = 0.0
    confidence: float = 0.0
    created_at: str = ""
    last_accessed_at: str = ""
    last_updated_at: str = ""
    access_count: int = 0
    status: str = "active"
    tags: list[str] = Field(default_factory=list)
    entity_keys: list[str] = Field(default_factory=list)
    source_record_ids: list[str] = Field(default_factory=list)
    fact_key: str | None = None
    fact_value: str | None = None


class MemoryEdgeResponse(BaseModel):
    from_id: str
    to_id: str
    semantic_sim: float = 0.0
    same_entity: bool = False
    same_project: bool = False
    derived_from: bool = False
    contradicts: bool = False
    updated_at: str = ""


class MemoryStatsResponse(BaseModel):
    record_count: int = 0
    edge_count: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)


class MemorySnapshotResponse(BaseModel):
    metadata: MemoryMetadataResponse
    scope: MemoryViewScopeResponse
    working_summaries: WorkingSummariesResponse
    records: list[MemoryRecordResponse] = Field(default_factory=list)
    edges: list[MemoryEdgeResponse] = Field(default_factory=list)
    stats: MemoryStatsResponse


class MemoryGraphNodeResponse(BaseModel):
    id: str
    type: str
    label: str = ""
    content: str = ""
    status: str = "active"
    scope: MemoryRecordScopeResponse
    strength: float = 0.0
    importance: float = 0.0
    confidence: float = 0.0
    created_at: str = ""
    last_accessed_at: str = ""
    last_updated_at: str = ""
    access_count: int = 0
    tags: list[str] = Field(default_factory=list)
    entity_keys: list[str] = Field(default_factory=list)
    source_record_ids: list[str] = Field(default_factory=list)
    fact_key: str | None = None
    fact_value: str | None = None


class MemoryGraphEdgeResponse(BaseModel):
    source: str
    target: str
    semantic_sim: float = 0.0
    same_entity: bool = False
    same_project: bool = False
    derived_from: bool = False
    contradicts: bool = False
    updated_at: str = ""


class MemoryGraphResponse(BaseModel):
    metadata: MemoryMetadataResponse
    scope: MemoryViewScopeResponse
    working_summaries: WorkingSummariesResponse
    nodes: list[MemoryGraphNodeResponse] = Field(default_factory=list)
    edges: list[MemoryGraphEdgeResponse] = Field(default_factory=list)
    stats: MemoryStatsResponse
