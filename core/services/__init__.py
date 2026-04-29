from __future__ import annotations

from dataclasses import dataclass

from core.services.approval_service import ApprovalService
from core.services.attachment_service import AttachmentService
from core.services.actor_service import ActorService
from core.services.capability_service import CapabilityService
from core.services.config_state_service import ConfigStateService
from core.services.context_pool_service import ContextPoolService
from core.services.delivery_service import DeliveryService
from core.services.endpoint_service import (
    DeliveryAttemptService,
    EndpointCapabilityService,
    EndpointConnectionService,
    EndpointOutboxService,
    EndpointRegistryService,
)
from core.services.heartbeat_workflow import HeartbeatWorkflow
from core.services.memory_state_service import MemoryStateService
from core.services.message_service import MessageService
from core.services.operation_service import OperationService
from core.services.operation_call_service import OperationCallService
from core.services.principal_service import PrincipalService
from core.services.run_service import RunEventService, RunService
from core.services.scheduler_service import ScheduledJobRunService, SchedulerService
from core.services.session_service import SessionService
from core.services.state_blob_service import RuntimeStateBlobService
from core.services.task_state_service import TaskStateService
from core.services.thread_service import ThreadService
from core.services.tool_router_service import ToolRouterService
from core.services.workspace_service import WorkspaceService


@dataclass(slots=True)
class CoreServices:
    principal: PrincipalService
    actor: ActorService
    workspace: WorkspaceService
    endpoint: EndpointRegistryService
    endpoint_connection: EndpointConnectionService
    endpoint_capability: EndpointCapabilityService
    endpoint_outbox: EndpointOutboxService
    delivery_attempt: DeliveryAttemptService
    delivery: DeliveryService
    capability: CapabilityService
    tool: CapabilityService
    thread: ThreadService
    session: SessionService
    run: RunService
    run_event: RunEventService
    scheduler: SchedulerService
    scheduled_job_run: ScheduledJobRunService
    tool_router: ToolRouterService
    state_blob: RuntimeStateBlobService
    operation: OperationService
    operation_call: OperationCallService
    approval: ApprovalService
    attachment: AttachmentService
    message: MessageService
    config_state: ConfigStateService
    context_pool: ContextPoolService
    memory_state: MemoryStateService
    task_state: TaskStateService


__all__ = [
    "ApprovalService",
    "AttachmentService",
    "ActorService",
    "CapabilityService",
    "ConfigStateService",
    "ContextPoolService",
    "CoreServices",
    "DeliveryAttemptService",
    "DeliveryService",
    "EndpointCapabilityService",
    "EndpointConnectionService",
    "EndpointOutboxService",
    "EndpointRegistryService",
    "HeartbeatWorkflow",
    "MemoryStateService",
    "MessageService",
    "OperationService",
    "OperationCallService",
    "PrincipalService",
    "RunEventService",
    "RunService",
    "ScheduledJobRunService",
    "SchedulerService",
    "SessionService",
    "RuntimeStateBlobService",
    "TaskStateService",
    "ThreadService",
    "ToolRouterService",
    "WorkspaceService",
]
