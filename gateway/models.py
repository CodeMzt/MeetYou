"""
网关请求响应模型。
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


class ClientThreadCreateRequest(BaseModel):
    workspace_id: str
    title: str = ""
    mode: str = "general"
    pinned_procedure_id: str | None = None

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> str:
        return to_public_assistant_mode(value)


class ClientProcedureResponse(BaseModel):
    procedure_id: str
    title: str = ""
    description: str = ""
    applicable_modes: list[str] = Field(default_factory=list)
    recommended_capabilities: list[str] = Field(default_factory=list)
    preferred_capability_ref: str = ""
    preferred_agent_ids: list[str] = Field(default_factory=list)
    preferred_agent_types: list[str] = Field(default_factory=list)
    agent_routing_policy: str = "balanced"
    default_execution_target: str = ""
    risk_profile: str = ""
    status: str = "active"

    @field_validator("applicable_modes", mode="before")
    @classmethod
    def _normalize_applicable_modes(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result = []
        seen = set()
        for item in value:
            normalized = to_public_assistant_mode(item)
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    @field_validator("default_execution_target", mode="before")
    @classmethod
    def _normalize_default_execution_target(cls, value: Any) -> str:
        return normalize_execution_target(value)


class ClientProcedureDetailResponse(ClientProcedureResponse):
    prompt_overlay: str = ""
    recommended_source_profiles: list[str] = Field(default_factory=list)
    infer_keywords: list[str] = Field(default_factory=list)


class ClientThreadProcedureContextResponse(BaseModel):
    source: str = "none"
    pinned_procedure: ClientProcedureDetailResponse | None = None
    latest_inferred_procedure: ClientProcedureDetailResponse | None = None
    effective_procedure: ClientProcedureDetailResponse | None = None
    latest_inferred_reason: str = ""
    latest_inferred_score: int = 0
    latest_inferred_at: str = ""


class ClientThreadPinnedProcedureRequest(BaseModel):
    procedure_id: str


class ClientThreadResponse(BaseModel):
    thread_id: str
    workspace_id: str
    title: str = ""
    status: str = "active"
    summary: str = ""
    pinned_procedure_id: str | None = None


class ClientSessionCreateRequest(BaseModel):
    thread_id: str
    workspace_id: str
    client_id: str
    client_type: str = "electron"
    display_name: str = ""


class ClientSessionResponse(BaseModel):
    session_id: str
    thread_id: str
    workspace_id: str
    client_id: str
    status: str = "active"


class ClientMessageCreateRequest(BaseModel):
    thread_id: str
    workspace_id: str
    client_id: str
    content: str
    session_id: str | None = None
    client_type: str = "electron"
    display_name: str = ""
    role: str = "user"
    client_message_id: str | None = None
    preferred_mode: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("preferred_mode", mode="before")
    @classmethod
    def _normalize_preferred_mode(cls, value: Any) -> str | None:
        if value is None or str(value).strip() == "":
            return None
        return to_public_assistant_mode(value)


class ClientMessageResponse(BaseModel):
    message_id: str
    thread_id: str
    session_id: str = ""
    workspace_id: str
    client_id: str = ""
    role: str
    content: str
    status: str = "completed"
    channel: str = "message"
    created_at: str = ""


class ClientWsCommand(BaseModel):
    action: str
    session_id: str | None = None
    request_id: str | None = None
    accepted: bool | None = None
    answer_text: str | None = None
    selected_option: str | None = None
    guidance: str | None = None
    checkpoint_id: str | None = None
    turn_id: str | None = None
    stream_id: str | None = None
    client_request_id: str | None = None
    client_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClientConfirmResponseRequest(BaseModel):
    accepted: bool
    request_id: str
    reason: str = ""
    client_id: str = ""


class ClientConfirmResponseResult(BaseModel):
    request_id: str
    session_id: str
    accepted: bool
    approval_id: str = ""
    approval_status: str = ""
    operation_id: str = ""


class ClientHumanInputResponseRequest(BaseModel):
    request_id: str
    answer_text: str = ""
    selected_option: str | None = None
    client_id: str = ""


class ClientHumanInputResponseResult(BaseModel):
    request_id: str
    session_id: str
    answer_text: str = ""
    selected_option: str | None = None


class ClientAttachmentUploadTicketRequest(BaseModel):
    owner_type: str
    owner_id: str
    kind: str
    mime_type: str
    file_name: str = ""
    size_bytes: int = 0
    lifecycle_policy: str = "normal"
    client_id: str = ""


class ClientAttachmentUploadTicketResponse(BaseModel):
    attachment_id: str
    ticket_id: str
    upload_url: str
    expires_at: str
    object_key: str
    status: str
    created_at: str = ""
    updated_at: str = ""


class ClientAttachmentUploadResult(BaseModel):
    attachment_id: str
    ticket_id: str
    status: str
    size_bytes: int
    sha256: str
    created_at: str = ""
    updated_at: str = ""
    uploaded_at: str = ""


class ClientAttachmentCompleteRequest(BaseModel):
    ticket_id: str = ""
    sha256: str = ""
    size_bytes: int | None = None


class ClientAttachmentResponse(BaseModel):
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


class ClientAttachmentDownloadTicketResponse(BaseModel):
    attachment_id: str
    ticket_id: str
    download_url: str
    fallback_download_url: str = ""
    download_strategy: str = ""
    expires_at: str
    mime_type: str
    file_name: str
    size_bytes: int


class ClientOperationCreateRequest(BaseModel):
    thread_id: str
    workspace_id: str
    client_id: str = ""
    session_id: str | None = None
    title: str = ""
    operation_type: str
    execution_target: str = ""
    target_agent_id: str | None = None
    capability_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("execution_target", mode="before")
    @classmethod
    def _normalize_execution_target(cls, value: Any) -> str:
        if value is None or str(value).strip() == "":
            return ""
        return normalize_execution_target(value)


class ClientOperationResponse(BaseModel):
    operation_id: str
    thread_id: str
    workspace_id: str
    title: str = ""
    operation_type: str
    execution_target: str
    target_agent_id: str = ""
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


class ClientApprovalDecisionRequest(BaseModel):
    decision: str
    reason: str = ""
    client_id: str = ""


class ClientApprovalResponse(BaseModel):
    approval_id: str
    operation_id: str
    approval_type: str
    risk_level: str
    status: str
    decision: str = ""
    reason: str = ""
    operation_status: str = ""


class ClientWorkspaceResponse(BaseModel):
    workspace_id: str
    title: str
    status: str
    base_mode: str
    description: str = ""
    prompt_overlay: str = ""
    default_execution_target: str = "core_only"
    capability_policy: str = "allow_all"
    allowed_capability_ids: list[str] = Field(default_factory=list)
    preferred_agent_ids: list[str] = Field(default_factory=list)
    preferred_agent_types: list[str] = Field(default_factory=list)
    preferred_source_profiles: list[str] = Field(default_factory=list)
    agent_routing_policy: str = "balanced"
    memory_ranking_policy: str = "workspace_first"
    capability_routing_overrides: dict[str, Any] = Field(default_factory=dict)

    @field_validator("base_mode", mode="before")
    @classmethod
    def _normalize_base_mode(cls, value: Any) -> str:
        return to_public_assistant_mode(value)

    @field_validator("default_execution_target", mode="before")
    @classmethod
    def _normalize_default_execution_target(cls, value: Any) -> str:
        return normalize_execution_target(value)


class ClientDanxiSessionLoginRequest(BaseModel):
    session_key: str = "default"
    encrypted_credentials: dict[str, Any] | None = None
    use_webvpn: bool | None = None
    email: str = ""
    password: str = ""
    webvpn_cookie: str = ""


class ClientDanxiWebvpnCookiePatchRequest(BaseModel):
    session_key: str = "default"
    encrypted_credentials: dict[str, Any] | None = None
    cookie_header: str = ""
    enable_webvpn: bool = True


class ClientDanxiSessionResponse(BaseModel):
    session_key: str
    email: str = ""
    transport: str = ""
    webvpn_enabled: bool = False
    has_webvpn_cookie: bool = False
    webvpn_required: bool = False
    direct_connect_available: bool = False
    logged_in: bool = False
    user_profile: dict[str, Any] | None = None


class ClientDanxiListResponse(BaseModel):
    count: int = 0
    items: list[Any] = Field(default_factory=list)
    scope: str = ""


class ClientDanxiPostResponse(BaseModel):
    hole: dict[str, Any] = Field(default_factory=dict)


class ClientDanxiSearchResponse(BaseModel):
    query: str = ""
    floor_hits: int = 0
    hole_ids: list[int] = Field(default_factory=list)
    hits_by_hole: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    items: list[dict[str, Any]] = Field(default_factory=list)


class ClientDanxiProfileResponse(BaseModel):
    session_key: str = ""
    logged_in: bool = False
    transport: str = ""
    webvpn_enabled: bool = False
    has_webvpn_cookie: bool = False
    webvpn_required: bool = False
    direct_connect_available: bool = False
    profile: dict[str, Any] | None = None


class ClientDanxiMessageTargetResponse(BaseModel):
    floor_id: int
    hole_id: int


class ClientDanxiReplyCreateRequest(BaseModel):
    session_key: str = "default"
    content: str = ""


class ClientDanxiReplyUpdateRequest(BaseModel):
    session_key: str = "default"
    content: str = ""


class ClientDanxiActionResponse(BaseModel):
    ok: bool = False
    status_code: int = 200
    message: str = ""
    hole_id: int | None = None
    floor_id: int | None = None


class ClientDanxiSummaryResponse(BaseModel):
    hole_id: int
    title: str = ""
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    reply_highlights: list[str] = Field(default_factory=list)
    floor_count: int = 0
    participant_count: int = 0
    generated_at: str = ""


class ClientAvailableAgentResponse(BaseModel):
    agent_id: str
    display_name: str
    agent_type: str
    status: str
    transport_profile: str
    owner_client_id: str = ""
    workspace_ids: list[str] = Field(default_factory=list)


class OperatorWorkspaceCreateRequest(BaseModel):
    workspace_id: str
    title: str = ""
    description: str = ""
    base_mode: str = "general"
    prompt_overlay: str = ""
    default_execution_target: str = "core_only"
    capability_policy: str = ""
    allowed_capability_ids: list[str] = Field(default_factory=list)
    preferred_agent_ids: list[str] = Field(default_factory=list)
    preferred_agent_types: list[str] = Field(default_factory=list)
    preferred_source_profiles: list[str] = Field(default_factory=list)
    agent_routing_policy: str = ""
    memory_ranking_policy: str = "workspace_first"
    capability_routing_overrides: dict[str, Any] = Field(default_factory=dict)

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
    default_execution_target: str = "core_only"
    capability_policy: str = "allow_all"
    allowed_capability_ids: list[str] = Field(default_factory=list)
    preferred_agent_ids: list[str] = Field(default_factory=list)
    preferred_agent_types: list[str] = Field(default_factory=list)
    preferred_source_profiles: list[str] = Field(default_factory=list)
    agent_routing_policy: str = "balanced"
    memory_ranking_policy: str = "workspace_first"
    capability_routing_overrides: dict[str, Any] = Field(default_factory=dict)

    @field_validator("base_mode", mode="before")
    @classmethod
    def _normalize_base_mode(cls, value: Any) -> str:
        return to_public_assistant_mode(value)

    @field_validator("default_execution_target", mode="before")
    @classmethod
    def _normalize_default_execution_target(cls, value: Any) -> str:
        return normalize_execution_target(value)


class OperatorAgentResponse(BaseModel):
    agent_id: str
    agent_type: str
    display_name: str
    transport_profile: str
    status: str
    last_seen_at: str = ""
    owner_client_id: str = ""
    workspace_ids: list[str] = Field(default_factory=list)
