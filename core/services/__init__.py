from __future__ import annotations

from dataclasses import dataclass

from core.services.approval_service import ApprovalService
from core.services.attachment_service import AttachmentService
from core.services.capability_service import CapabilityService
from core.services.client_service import ClientService
from core.services.config_state_service import ConfigStateService
from core.services.context_pool_service import ContextPoolService
from core.services.memory_state_service import MemoryStateService
from core.services.message_service import MessageService
from core.services.operation_service import OperationService
from core.services.operation_call_service import OperationCallService
from core.services.principal_service import PrincipalService
from core.services.procedure_service import ProcedureService
from core.services.session_service import SessionService
from core.services.state_blob_service import RuntimeStateBlobService
from core.services.task_state_service import TaskStateService
from core.services.thread_service import ThreadService
from core.services.workspace_service import WorkspaceService


@dataclass(slots=True)
class CoreServices:
    principal: PrincipalService
    workspace: WorkspaceService
    client: ClientService
    capability: CapabilityService
    tool: CapabilityService
    procedure: ProcedureService
    thread: ThreadService
    session: SessionService
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
    "CapabilityService",
    "ClientService",
    "ConfigStateService",
    "ContextPoolService",
    "CoreServices",
    "MemoryStateService",
    "MessageService",
    "OperationService",
    "OperationCallService",
    "PrincipalService",
    "ProcedureService",
    "SessionService",
    "RuntimeStateBlobService",
    "TaskStateService",
    "ThreadService",
    "WorkspaceService",
]
