from __future__ import annotations

import hashlib
from uuid import uuid4

from core.db.repositories import (
    ActorDeliveryPreferenceRepository,
    DeliveryAttemptRepository,
    EndpointAddressRepository,
    EndpointCapabilityRepository,
    EndpointConnectionRepository,
    EndpointOutboxRepository,
    EndpointRepository,
    EndpointThreadBindingRepository,
    ThreadRepository,
)
from core.services.base import ServiceBase


class EndpointThreadBindingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class EndpointRegistryService(ServiceBase):
    def ensure_endpoint(
        self,
        *,
        endpoint_id: str,
        endpoint_type: str,
        provider_type: str,
        transport_type: str,
        owner_actor_id=None,
        workspace_scope: list | None = None,
        status: str = "active",
        labels: list | None = None,
        priority: int = 100,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return EndpointRepository(session).upsert(
                endpoint_id=endpoint_id,
                endpoint_type=endpoint_type,
                provider_type=provider_type,
                transport_type=transport_type,
                owner_actor_id=owner_actor_id,
                workspace_scope=workspace_scope,
                status=status,
                labels=labels,
                priority=priority,
                metadata=metadata,
            )

    def get_by_endpoint_id(self, endpoint_id: str):
        with self.session_scope() as session:
            return EndpointRepository(session).get_by_endpoint_id(endpoint_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return EndpointRepository(session).get_by_id(row_id)

    def list_all(self):
        with self.session_scope() as session:
            return EndpointRepository(session).list_all()

    def set_status(self, *, endpoint_id: str, status: str):
        with self.session_scope() as session:
            return EndpointRepository(session).set_status(endpoint_id=endpoint_id, status=status)


class EndpointConnectionService(ServiceBase):
    def upsert_connection(
        self,
        *,
        endpoint_row_id,
        connection_id: str | None = None,
        transport: str = "websocket",
        protocol_version: str = "meetyou.endpoint.ws.v4",
        status: str = "connected",
        remote_addr: str = "",
        subscriptions: list | None = None,
        capability_snapshot: dict | None = None,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return EndpointConnectionRepository(session).upsert(
                connection_id=connection_id or f"conn_{uuid4().hex}",
                endpoint_id=endpoint_row_id,
                transport=transport,
                protocol_version=protocol_version,
                status=status,
                remote_addr=remote_addr,
                subscriptions=subscriptions,
                capability_snapshot=capability_snapshot,
                metadata=metadata,
            )

    def heartbeat(self, *, connection_id: str, metadata: dict | None = None):
        with self.session_scope() as session:
            return EndpointConnectionRepository(session).update_heartbeat(
                connection_id=connection_id,
                status="connected",
                metadata=metadata,
            )

    def mark_disconnected(self, *, connection_id: str):
        with self.session_scope() as session:
            return EndpointConnectionRepository(session).mark_disconnected(connection_id=connection_id)


class EndpointCapabilityService(ServiceBase):
    def upsert_capability(
        self,
        *,
        endpoint_row_id,
        tool_key: str,
        capability_id: str = "",
        schema: dict | None = None,
        risk_level: str = "read",
        requires_confirmation: bool = False,
        enabled: bool = True,
        constraints: dict | None = None,
        metadata: dict | None = None,
    ):
        normalized_tool_key = str(tool_key or "").strip()
        with self.session_scope() as session:
            return EndpointCapabilityRepository(session).upsert(
                endpoint_id=endpoint_row_id,
                tool_key=normalized_tool_key,
                capability_id=capability_id or f"endpoint.{endpoint_row_id}.{normalized_tool_key}",
                schema=schema,
                risk_level=risk_level,
                requires_confirmation=requires_confirmation,
                enabled=enabled,
                constraints=constraints,
                metadata=metadata,
            )

    def replace_snapshot(self, *, endpoint_row_id, endpoint_public_id: str, capabilities: list[dict]) -> int:
        count = 0
        with self.session_scope() as session:
            repo = EndpointCapabilityRepository(session)
            for item in capabilities or []:
                tool_key = str(item.get("tool_key") or item.get("name") or "").strip()
                if not tool_key:
                    continue
                raw_capability_id = str(item.get("capability_id") or item.get("tool_id") or "").strip()
                if raw_capability_id and not raw_capability_id.startswith("endpoint."):
                    raw_capability_id = ""
                input_schema = (
                    item.get("input_schema")
                    if isinstance(item.get("input_schema"), dict)
                    else item.get("schema")
                    if isinstance(item.get("schema"), dict)
                    else {}
                )
                output_schema = item.get("output_schema") if isinstance(item.get("output_schema"), dict) else {}
                metadata = {
                    k: v
                    for k, v in dict(item).items()
                    if k not in {"schema", "input_schema", "output_schema", "constraints"}
                }
                metadata["input_schema"] = dict(input_schema or {})
                metadata["output_schema"] = dict(output_schema or {})
                repo.upsert(
                    endpoint_id=endpoint_row_id,
                    tool_key=tool_key,
                    capability_id=raw_capability_id or f"endpoint.{endpoint_public_id}.{tool_key}",
                    schema=input_schema,
                    risk_level=str(item.get("risk_level") or "read"),
                    requires_confirmation=bool(item.get("requires_confirmation", False)),
                    enabled=bool(item.get("enabled", True)),
                    constraints=item.get("constraints") if isinstance(item.get("constraints"), dict) else {},
                    metadata=metadata,
                )
                count += 1
        return count

    def get_by_capability_id(self, capability_id: str):
        with self.session_scope() as session:
            return EndpointCapabilityRepository(session).get_by_capability_id(capability_id)

    def list_for_endpoint(self, *, endpoint_row_id):
        with self.session_scope() as session:
            return EndpointCapabilityRepository(session).list_for_endpoint(endpoint_id=endpoint_row_id)

    def list_enabled_for_tool(self, *, tool_key: str):
        with self.session_scope() as session:
            return EndpointCapabilityRepository(session).list_enabled_for_tool(tool_key=tool_key)


class EndpointAddressService(ServiceBase):
    def upsert_address(
        self,
        *,
        endpoint_row_id,
        provider_type: str,
        address_type: str,
        external_ref: str,
        address_id: str = "",
        display_name: str = "",
        workspace_scope: list | None = None,
        status: str = "sendable",
        capabilities: list | None = None,
        last_seen_at=None,
        last_verified_at=None,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return EndpointAddressRepository(session).upsert(
                endpoint_id=endpoint_row_id,
                provider_type=provider_type,
                address_type=address_type,
                external_ref=external_ref,
                address_id=address_id,
                display_name=display_name,
                workspace_scope=workspace_scope,
                status=status,
                capabilities=capabilities,
                last_seen_at=last_seen_at,
                last_verified_at=last_verified_at,
                metadata=metadata,
            )

    def get_by_address_id(self, address_id: str):
        with self.session_scope() as session:
            return EndpointAddressRepository(session).get_by_address_id(address_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return EndpointAddressRepository(session).get_by_id(row_id)

    def list_addresses(
        self,
        *,
        provider_type: str = "",
        address_type: str = "",
        workspace_id: str = "",
        status: str = "",
    ):
        with self.session_scope() as session:
            return EndpointAddressRepository(session).list_all(
                provider_type=str(provider_type or "").strip(),
                address_type=str(address_type or "").strip(),
                workspace_id=str(workspace_id or "").strip(),
                status=str(status or "").strip(),
            )

    def delete_address(self, *, address_id: str) -> bool:
        with self.session_scope() as session:
            return EndpointAddressRepository(session).delete(address_id=address_id)


class EndpointThreadBindingService(ServiceBase):
    _VALID_STRATEGIES = {"per_conversation", "per_address", "shared_endpoint", "explicit_thread"}

    @staticmethod
    def _binding_id(*parts: str) -> str:
        digest = hashlib.sha256("\n".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:32]
        return f"etb.{digest}"

    @staticmethod
    def _clean_key(value: str) -> str:
        return str(value or "").strip()

    def _canonical_key(
        self,
        *,
        thread_strategy: str,
        endpoint_public_id: str,
        conversation_key: str = "",
        address=None,
        explicit_thread_id: str = "",
    ) -> str:
        if thread_strategy == "shared_endpoint":
            return f"endpoint:{endpoint_public_id}"
        if thread_strategy == "per_address":
            address_id = str(getattr(address, "address_id", "") or "").strip()
            external_ref = str(getattr(address, "external_ref", "") or "").strip()
            key = address_id or self._clean_key(conversation_key) or external_ref
            if not key:
                raise EndpointThreadBindingError("conversation_key_required", "per_address requires address_id or conversation_key.")
            return f"address:{key}"
        if thread_strategy == "explicit_thread":
            key = self._clean_key(explicit_thread_id)
            if not key:
                raise EndpointThreadBindingError("explicit_thread_id_required", "explicit_thread requires explicit_thread_id.")
            return f"thread:{key}"
        key = self._clean_key(conversation_key)
        if not key:
            raise EndpointThreadBindingError("conversation_key_required", "per_conversation requires conversation_key.")
        return f"conversation:{key}"

    def resolve_thread(
        self,
        *,
        principal_id,
        endpoint_row_id,
        endpoint_public_id: str,
        workspace_row_id,
        workspace_public_id: str = "",
        thread_strategy: str = "per_conversation",
        conversation_key: str = "",
        address_row_id=None,
        title: str = "",
        display_name: str = "",
        explicit_thread_id: str = "",
        metadata: dict | None = None,
    ):
        strategy = str(thread_strategy or "per_conversation").strip() or "per_conversation"
        if strategy not in self._VALID_STRATEGIES:
            raise EndpointThreadBindingError("unsupported_thread_strategy", f"Unsupported endpoint thread strategy: {strategy}")

        with self.session_scope() as session:
            binding_repo = EndpointThreadBindingRepository(session)
            thread_repo = ThreadRepository(session)
            address = EndpointAddressRepository(session).get_by_id(address_row_id) if address_row_id is not None else None
            canonical_key = self._canonical_key(
                thread_strategy=strategy,
                endpoint_public_id=endpoint_public_id,
                conversation_key=conversation_key,
                address=address,
                explicit_thread_id=explicit_thread_id,
            )
            binding = binding_repo.get_by_endpoint_strategy_key(
                endpoint_id=endpoint_row_id,
                thread_strategy=strategy,
                conversation_key=canonical_key,
            )
            explicit_thread = thread_repo.get_by_thread_id(explicit_thread_id) if explicit_thread_id else None
            explicit_thread_error: EndpointThreadBindingError | None = None
            if explicit_thread_id and explicit_thread is None:
                explicit_thread_error = EndpointThreadBindingError("explicit_thread_not_found", f"Unknown explicit thread: {explicit_thread_id}")
            if explicit_thread is not None:
                if str(getattr(explicit_thread, "status", "") or "") == "deleted":
                    explicit_thread_error = EndpointThreadBindingError("explicit_thread_deleted", f"Explicit thread is deleted: {explicit_thread_id}")
                elif str(getattr(explicit_thread, "principal_id", "") or "") != str(principal_id or ""):
                    explicit_thread_error = EndpointThreadBindingError("explicit_thread_forbidden", "Explicit thread does not belong to the current principal.")
                elif workspace_row_id is not None and getattr(explicit_thread, "home_workspace_id", None) != workspace_row_id:
                    explicit_thread_error = EndpointThreadBindingError("explicit_thread_workspace_mismatch", "Explicit thread does not belong to the requested workspace.")
            if strategy == "explicit_thread" and explicit_thread_error is not None:
                raise explicit_thread_error
            if strategy != "explicit_thread" and explicit_thread_error is not None:
                explicit_thread = None

            thread = None
            if binding is not None:
                thread = thread_repo.get_by_id(getattr(binding, "thread_id", None))
                if thread is not None and str(getattr(thread, "status", "") or "") == "deleted":
                    thread = None
            if thread is None:
                thread = explicit_thread
            if thread is None:
                thread = thread_repo.create(
                    thread_id=f"thr_{uuid4().hex}",
                    principal_id=principal_id,
                    home_workspace_id=workspace_row_id,
                    title=str(title or display_name or canonical_key).strip()[:255],
                    metadata={
                        **dict(metadata or {}),
                        "endpoint_thread_binding": True,
                        "endpoint_id": endpoint_public_id,
                        "workspace_id": workspace_public_id,
                        "thread_strategy": strategy,
                        "conversation_key": canonical_key,
                    },
                )

            binding_metadata = {
                **dict(metadata or {}),
                "endpoint_id": endpoint_public_id,
                "workspace_id": workspace_public_id,
                "thread_id": getattr(thread, "thread_id", ""),
                "raw_conversation_key": self._clean_key(conversation_key),
                "explicit_thread_id": self._clean_key(explicit_thread_id),
            }
            binding = binding_repo.upsert(
                endpoint_id=endpoint_row_id,
                thread_id=getattr(thread, "id", None),
                workspace_id=workspace_row_id,
                address_id=address_row_id,
                thread_strategy=strategy,
                conversation_key=canonical_key,
                binding_id=self._binding_id(str(endpoint_public_id), strategy, canonical_key),
                display_name=display_name or title,
                status="active",
                metadata=binding_metadata,
            )
            return binding, thread


class ActorDeliveryPreferenceService(ServiceBase):
    def upsert_preference(
        self,
        *,
        actor_row_id,
        provider_type: str,
        address_row_id,
        alias: str = "me",
        preference_id: str = "",
        is_default: bool = True,
        verified: bool = False,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return ActorDeliveryPreferenceRepository(session).upsert(
                actor_id=actor_row_id,
                provider_type=provider_type,
                address_id=address_row_id,
                alias=alias,
                preference_id=preference_id,
                is_default=is_default,
                verified=verified,
                metadata=metadata,
            )

    def list_for_actor(self, *, actor_row_id, provider_type: str = "", alias: str = ""):
        with self.session_scope() as session:
            return ActorDeliveryPreferenceRepository(session).list_for_actor(
                actor_id=actor_row_id,
                provider_type=str(provider_type or "").strip(),
                alias=str(alias or "").strip(),
            )

    def get_default(self, *, actor_row_id, provider_type: str, alias: str = "me"):
        with self.session_scope() as session:
            return ActorDeliveryPreferenceRepository(session).get_default(
                actor_id=actor_row_id,
                provider_type=str(provider_type or "").strip(),
                alias=str(alias or "me").strip() or "me",
            )


class EndpointOutboxService(ServiceBase):
    def enqueue(
        self,
        *,
        target_endpoint_id,
        target_address_id=None,
        message_type: str,
        payload: dict,
        available_at=None,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return EndpointOutboxRepository(session).create(
                outbox_id=f"outbox_{uuid4().hex}",
                target_endpoint_id=target_endpoint_id,
                target_address_id=target_address_id,
                message_type=message_type,
                payload=payload,
                available_at=available_at,
                metadata=metadata,
            )

    def list_due(self, *, target_endpoint_id=None, limit: int = 50):
        with self.session_scope() as session:
            return EndpointOutboxRepository(session).list_due(
                target_endpoint_id=target_endpoint_id,
                limit=limit,
            )

    def mark_inflight(self, *, outbox_id):
        with self.session_scope() as session:
            return EndpointOutboxRepository(session).mark_inflight(outbox_id=outbox_id)

    def mark_sent(self, *, outbox_id):
        with self.session_scope() as session:
            return EndpointOutboxRepository(session).mark_sent(outbox_id=outbox_id)

    def reschedule_failure(
        self,
        *,
        outbox_id,
        error: str,
        max_attempts: int = 5,
        base_delay_seconds: int = 2,
        max_delay_seconds: int = 300,
    ):
        with self.session_scope() as session:
            return EndpointOutboxRepository(session).reschedule_failure(
                outbox_id=outbox_id,
                error=error,
                max_attempts=max_attempts,
                base_delay_seconds=base_delay_seconds,
                max_delay_seconds=max_delay_seconds,
            )


class DeliveryAttemptService(ServiceBase):
    def record(
        self,
        *,
        target_endpoint_id,
        target_address_id=None,
        message_type: str,
        payload: dict,
        status: str = "pending",
        outbox_id=None,
        error: dict | None = None,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return DeliveryAttemptRepository(session).create(
                delivery_id=f"delivery_{uuid4().hex}",
                outbox_id=outbox_id,
                target_endpoint_id=target_endpoint_id,
                target_address_id=target_address_id,
                message_type=message_type,
                payload=payload,
                status=status,
                error=error,
                metadata=metadata,
            )
