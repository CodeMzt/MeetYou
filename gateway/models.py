"""
网关请求与响应模型。
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.public_contract import normalize_execution_target, to_public_assistant_mode
from service_runtime.models import RuntimeError, RuntimeHealth


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
    context_pool: int = 0
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
    workspace_tags: list[str] = Field(default_factory=list)
    origin_workspace_id: str = ""
    source_label: str = ""


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
    workspace_tags: list[str] = Field(default_factory=list)
    origin_workspace_id: str = ""
    source_label: str = ""


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


class MemoryClearResponse(BaseModel):
    ok: bool = True
    cleared_record_count: int = 0
    cleared_edge_count: int = 0
    cleared_session_summary_count: int = 0
    cleared_global_summary: bool = False
    cleared_session_count: int = 0
    active_session_count: int = 0
    updated_at: str = ""


class MemoryRecordPatchRequest(BaseModel):
    status: str


class MemoryRecordMutationResponse(BaseModel):
    ok: bool = True
    memory_id: str
    status: str = ""
    deleted: bool = False
    updated_at: str = ""
    record: MemoryRecordResponse | None = None


class RuntimeThreadCreateRequest(BaseModel):
    home_workspace_id: str = ""
    workspace_id: str = ""
    title: str = ""
    mode: str = "general"

    @property
    def resolved_home_workspace_id(self) -> str:
        return str(self.home_workspace_id or self.workspace_id or "").strip()

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> str:
        return to_public_assistant_mode(value)


class RuntimeDefaultThreadRequest(BaseModel):
    workspace_id: str = ""
    default_key: str = "frontend.default"
    title: str = "Desktop Chat"
    mode: str = "general"

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> str:
        return to_public_assistant_mode(value)


class RuntimeThreadResponse(BaseModel):
    thread_id: str
    home_workspace_id: str
    workspace_id: str = ""
    title: str = ""
    status: str = "active"
    summary: str = ""


class RuntimeSessionCreateRequest(BaseModel):
    thread_id: str
    active_workspace_id: str = ""
    workspace_id: str = ""
    endpoint_id: str
    endpoint_type: str = "electron"
    display_name: str = ""

    @property
    def resolved_active_workspace_id(self) -> str:
        return str(self.active_workspace_id or self.workspace_id or "").strip()


class RuntimeSessionResponse(BaseModel):
    session_id: str
    thread_id: str
    active_workspace_id: str
    workspace_id: str = ""
    endpoint_id: str
    status: str = "active"


class RuntimeActiveWorkspacePatchRequest(BaseModel):
    active_workspace_id: str
    endpoint_id: str = ""


class RuntimeMessageCreateRequest(BaseModel):
    thread_id: str
    active_workspace_id: str | None = None
    workspace_id: str | None = None
    endpoint_id: str
    content: str
    session_id: str | None = None
    endpoint_type: str = "electron"
    display_name: str = ""
    role: str = "user"
    endpoint_message_id: str | None = None
    preferred_mode: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("preferred_mode", mode="before")
    @classmethod
    def _normalize_preferred_mode(cls, value: Any) -> str | None:
        if value is None or str(value).strip() == "":
            return None
        return to_public_assistant_mode(value)

    @property
    def resolved_active_workspace_id(self) -> str:
        return str(self.active_workspace_id or self.workspace_id or "").strip()


class RuntimeMessageResponse(BaseModel):
    message_id: str
    thread_id: str
    session_id: str = ""
    active_workspace_id: str
    workspace_id: str = ""
    endpoint_id: str = ""
    role: str
    content: str
    status: str = "completed"
    channel: str = "message"
    created_at: str = ""


class RuntimeConfirmResponseRequest(BaseModel):
    accepted: bool
    request_id: str
    reason: str = ""
    endpoint_id: str = ""


class RuntimeConfirmResponseResult(BaseModel):
    request_id: str
    session_id: str
    accepted: bool
    approval_id: str = ""
    approval_status: str = ""
    operation_id: str = ""


class RuntimeHumanInputResponseRequest(BaseModel):
    request_id: str
    answer_text: str = ""
    selected_option: str | None = None
    endpoint_id: str = ""


class RuntimeHumanInputResponseResult(BaseModel):
    request_id: str
    session_id: str
    answer_text: str = ""
    selected_option: str | None = None


class RuntimeAttachmentUploadTicketRequest(BaseModel):
    owner_type: str
    owner_id: str
    kind: str
    mime_type: str
    file_name: str = ""
    size_bytes: int = 0
    lifecycle_policy: str = "normal"
    endpoint_id: str = ""


class RuntimeAttachmentUploadTicketResponse(BaseModel):
    attachment_id: str
    ticket_id: str
    upload_url: str
    expires_at: str
    object_key: str
    status: str
    created_at: str = ""
    updated_at: str = ""


class RuntimeAttachmentUploadResult(BaseModel):
    attachment_id: str
    ticket_id: str
    status: str
    size_bytes: int
    sha256: str
    created_at: str = ""
    updated_at: str = ""
    uploaded_at: str = ""


class RuntimeAttachmentCompleteRequest(BaseModel):
    ticket_id: str = ""
    sha256: str = ""
    size_bytes: int | None = None


class RuntimeAttachmentResponse(BaseModel):
    attachment_id: str
    owner_type: str
    owner_id: str
    kind: str
    mime_type: str
    file_name: str
    object_key: str
    size_bytes: int
    lifecycle_policy: str = "normal"
    expires_at: str = ""
    sha256: str
    status: str
    created_at: str = ""
    updated_at: str = ""
    uploaded_at: str = ""
    completed_at: str = ""
    deleted_at: str = ""
    created_at: str = ""
    updated_at: str = ""


class RuntimeAttachmentDownloadTicketResponse(BaseModel):
    attachment_id: str
    ticket_id: str
    download_url: str
    fallback_download_url: str = ""
    download_strategy: str = ""
    expires_at: str
    mime_type: str
    file_name: str
    size_bytes: int


class RuntimeOperationCreateRequest(BaseModel):
    thread_id: str
    workspace_id: str
    endpoint_id: str = ""
    session_id: str | None = None
    title: str = ""
    operation_type: str
    execution_target: str = ""
    target_endpoint_id: str | None = None
    tool_key: str | None = None
    tool_id: str | None = None
    capability_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("execution_target", mode="before")
    @classmethod
    def _normalize_execution_target(cls, value: Any) -> str:
        if value is None or str(value).strip() == "":
            return ""
        return normalize_execution_target(value)


class RuntimeOperationResponse(BaseModel):
    operation_id: str
    thread_id: str
    workspace_id: str
    title: str = ""
    operation_type: str
    execution_target: str
    target_endpoint_id: str = ""
    tool_key: str = ""
    tool_id: str = ""
    capability_id: str = ""
    status: str = "queued"
    approval_id: str = ""
    approval_status: str = ""
    approval_required: bool = False
    routing_reason: str = ""

    @field_validator("execution_target", mode="before")
    @classmethod
    def _normalize_execution_target(cls, value: Any) -> str:
        return normalize_execution_target(value)


class RuntimeApprovalDecisionRequest(BaseModel):
    decision: str
    reason: str = ""
    endpoint_id: str = ""


class RuntimeApprovalResponse(BaseModel):
    approval_id: str
    operation_id: str
    approval_type: str
    risk_level: str
    status: str
    decision: str = ""
    reason: str = ""
    operation_status: str = ""


class RuntimeWorkspaceResponse(BaseModel):
    workspace_id: str
    title: str
    status: str
    base_mode: str
    description: str = ""
    prompt_overlay: str = ""
    default_execution_target: str = "core.local"
    tool_policy: str = "allow_all"
    allowed_tool_ids: list[str] = Field(default_factory=list)
    preferred_target_endpoint_ids: list[str] = Field(default_factory=list)
    preferred_endpoint_provider_types: list[str] = Field(default_factory=list)
    preferred_source_profiles: list[str] = Field(default_factory=list)
    tool_target_routing_policy: str = "balanced"
    memory_ranking_policy: str = "workspace_first"
    tool_routing_overrides: dict[str, Any] = Field(default_factory=dict)

    @field_validator("base_mode", mode="before")
    @classmethod
    def _normalize_base_mode(cls, value: Any) -> str:
        return to_public_assistant_mode(value)

    @field_validator("default_execution_target", mode="before")
    @classmethod
    def _normalize_default_execution_target(cls, value: Any) -> str:
        return normalize_execution_target(value)


class RuntimeDanxiSessionLoginRequest(BaseModel):
    session_key: str = "default"
    encrypted_credentials: dict[str, Any] | None = None
    use_webvpn: bool | None = None
    email: str = ""
    password: str = ""
    webvpn_cookie: str = ""


class RuntimeDanxiWebvpnCookiePatchRequest(BaseModel):
    session_key: str = "default"
    encrypted_credentials: dict[str, Any] | None = None
    cookie_header: str = ""
    enable_webvpn: bool = True


class RuntimeDanxiSessionResponse(BaseModel):
    session_key: str
    email: str = ""
    transport: str = ""
    webvpn_enabled: bool = False
    has_webvpn_cookie: bool = False
    webvpn_required: bool = False
    direct_connect_available: bool = False
    logged_in: bool = False
    user_profile: dict[str, Any] | None = None


class RuntimeDanxiListResponse(BaseModel):
    count: int = 0
    items: list[Any] = Field(default_factory=list)
    scope: str = ""


class RuntimeDanxiPostResponse(BaseModel):
    hole: dict[str, Any] = Field(default_factory=dict)


class RuntimeDanxiSearchResponse(BaseModel):
    query: str = ""
    floor_hits: int = 0
    hole_ids: list[int] = Field(default_factory=list)
    hits_by_hole: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    items: list[dict[str, Any]] = Field(default_factory=list)


class RuntimeDanxiProfileResponse(BaseModel):
    session_key: str = ""
    logged_in: bool = False
    transport: str = ""
    webvpn_enabled: bool = False
    has_webvpn_cookie: bool = False
    webvpn_required: bool = False
    direct_connect_available: bool = False
    profile: dict[str, Any] | None = None


class RuntimeDanxiMessageTargetResponse(BaseModel):
    floor_id: int
    hole_id: int


class RuntimeDanxiReplyCreateRequest(BaseModel):
    session_key: str = "default"
    content: str = ""


class RuntimeDanxiReplyUpdateRequest(BaseModel):
    session_key: str = "default"
    content: str = ""


class RuntimeDanxiActionResponse(BaseModel):
    ok: bool = False
    status_code: int = 200
    message: str = ""
    hole_id: int | None = None
    floor_id: int | None = None


class RuntimeDanxiSummaryResponse(BaseModel):
    hole_id: int
    title: str = ""
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    reply_highlights: list[str] = Field(default_factory=list)
    floor_count: int = 0
    participant_count: int = 0
    generated_at: str = ""


class EndpointAvailableResponse(BaseModel):
    endpoint_id: str
    display_name: str
    endpoint_type: str = ""
    provider_type: str
    status: str
    workspace_ids: list[str] = Field(default_factory=list)
    transport_profile: str = ""
    available_tools: list[str] = Field(default_factory=list)
    executable_tools: list[str] = Field(default_factory=list)
    membership_role: str = "member"
    enabled: bool = True


class ContextPoolQueryItemResponse(BaseModel):
    context_id: str
    item_type: str
    role: str = ""
    content: str
    score: float = 0.0
    same_session: bool = False
    same_thread: bool = False
    same_workspace: bool = False
    workspace_tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class ContextPoolQueryResponse(BaseModel):
    query: str
    count: int = 0
    items: list[ContextPoolQueryItemResponse] = Field(default_factory=list)


class OperatorWorkspaceCreateRequest(BaseModel):
    workspace_id: str
    title: str = ""
    description: str = ""
    base_mode: str = "general"
    prompt_overlay: str = ""
    default_execution_target: str = "core.local"
    tool_policy: str = ""
    allowed_tool_ids: list[str] = Field(default_factory=list)
    preferred_target_endpoint_ids: list[str] = Field(default_factory=list)
    preferred_endpoint_provider_types: list[str] = Field(default_factory=list)
    preferred_source_profiles: list[str] = Field(default_factory=list)
    tool_target_routing_policy: str = ""
    memory_ranking_policy: str = "workspace_first"
    tool_routing_overrides: dict[str, Any] = Field(default_factory=dict)

    @field_validator("base_mode", mode="before")
    @classmethod
    def _normalize_base_mode(cls, value: Any) -> str:
        return to_public_assistant_mode(value)

    @field_validator("default_execution_target", mode="before")
    @classmethod
    def _normalize_default_execution_target(cls, value: Any) -> str:
        return normalize_execution_target(value)


class OperatorWorkspaceUpdateRequest(BaseModel):
    base_mode: str | None = None
    preferred_source_profiles: list[str] | None = None
    memory_ranking_policy: str | None = None

    @field_validator("base_mode", mode="before")
    @classmethod
    def _normalize_base_mode(cls, value: Any) -> str | None:
        if value is None:
            return None
        return to_public_assistant_mode(value)


class OperatorSourceProfileResponse(BaseModel):
    profile_name: str
    label: str = ""
    description: str = ""
    official_only: bool = False
    default_freshness: str = ""


class OperatorWorkspaceResponse(BaseModel):
    workspace_id: str
    title: str
    status: str
    base_mode: str
    description: str = ""
    prompt_overlay: str = ""
    default_execution_target: str = "core.local"
    tool_policy: str = "allow_all"
    allowed_tool_ids: list[str] = Field(default_factory=list)
    preferred_target_endpoint_ids: list[str] = Field(default_factory=list)
    preferred_endpoint_provider_types: list[str] = Field(default_factory=list)
    preferred_source_profiles: list[str] = Field(default_factory=list)
    tool_target_routing_policy: str = "balanced"
    memory_ranking_policy: str = "workspace_first"
    tool_routing_overrides: dict[str, Any] = Field(default_factory=dict)

    @field_validator("base_mode", mode="before")
    @classmethod
    def _normalize_base_mode(cls, value: Any) -> str:
        return to_public_assistant_mode(value)

    @field_validator("default_execution_target", mode="before")
    @classmethod
    def _normalize_default_execution_target(cls, value: Any) -> str:
        return normalize_execution_target(value)


class OperatorEndpointResponse(BaseModel):
    endpoint_id: str
    endpoint_type: str
    provider_type: str
    transport_type: str
    status: str
    connected: bool = False
    connection_count: int = 0
    workspace_ids: list[str] = Field(default_factory=list)
    capability_count: int = 0
    labels: list[str] = Field(default_factory=list)
    last_seen_at: str = ""


class OperatorScheduledJobCreateRequest(BaseModel):
    job_id: str | None = None
    kind: str = "scheduled_workflow"
    name: str = ""
    workspace_id: str | None = None
    singleton_key: str | None = None
    enabled: bool = True
    trigger_type: str = "interval"
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    interval_seconds: int | None = None
    timezone: str = "UTC"
    action_ref: str = "core.workflow.scheduled_workflow"
    run_template: dict[str, Any] = Field(default_factory=dict)
    execution_policy: dict[str, Any] = Field(default_factory=dict)
    delivery_policy: dict[str, Any] = Field(default_factory=dict)
    concurrency_policy: dict[str, Any] = Field(default_factory=dict)
    misfire_policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OperatorScheduledJobUpdateRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    trigger_config: dict[str, Any] | None = None
    interval_seconds: int | None = None
    timezone: str | None = None
    action_ref: str | None = None
    run_template: dict[str, Any] | None = None
    execution_policy: dict[str, Any] | None = None
    delivery_policy: dict[str, Any] | None = None
    concurrency_policy: dict[str, Any] | None = None
    misfire_policy: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class OperatorScheduledJobResponse(BaseModel):
    job_id: str
    kind: str
    name: str = ""
    workspace_id: str = ""
    singleton_key: str = ""
    enabled: bool = True
    deletable: bool = True
    editable_fields: list[str] = Field(default_factory=list)
    trigger_type: str = "interval"
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    timezone: str = "UTC"
    action_ref: str = ""
    run_template: dict[str, Any] = Field(default_factory=dict)
    execution_policy: dict[str, Any] = Field(default_factory=dict)
    delivery_policy: dict[str, Any] = Field(default_factory=dict)
    concurrency_policy: dict[str, Any] = Field(default_factory=dict)
    misfire_policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class OperatorScheduledJobDeleteResponse(BaseModel):
    job_id: str
    deleted: bool
