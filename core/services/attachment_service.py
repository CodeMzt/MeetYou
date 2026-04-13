from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from core.db.models.attachment import Attachment, AttachmentUploadTicket
from core.db.repositories import AttachmentRepository, AttachmentUploadTicketRepository
from core.services.base import ServiceBase
from core.storage.object_store import LocalObjectStore


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


_DOWNLOAD_TICKET_MIN_TTL_SECONDS = 60
_EPHEMERAL_ATTACHMENT_TTL_SECONDS = 24 * 60 * 60
_SCREENSHOT_ATTACHMENT_KINDS = {"screenshot", "screen_capture", "capture_screenshot"}


class AttachmentService(ServiceBase):
    def __init__(self, session_factory, *, storage_root: Path | None = None, object_store=None) -> None:
        super().__init__(session_factory)
        self._object_store = object_store or LocalObjectStore(Path(storage_root or Path("user") / "attachments"))
        self._download_tickets: dict[str, dict] = {}

    def _ensure_storage_root(self) -> Path:
        return self._object_store.root

    @staticmethod
    def _sanitize_name(file_name: str) -> str:
        text = str(file_name or "").strip().replace("\\", "_").replace("/", "_")
        return text or "blob.bin"

    def _attachment_path(self, attachment_id: str, file_name: str) -> Path:
        path = self._ensure_storage_root() / attachment_id / self._sanitize_name(file_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _coerce_size_bytes(value) -> int:
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0

    def _attachment_file_name(self, attachment) -> str:
        return self._sanitize_name(str((getattr(attachment, "meta", {}) or {}).get("file_name") or attachment.attachment_id))

    @staticmethod
    def _read_iso_datetime(value: str) -> datetime:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)

    @staticmethod
    def _normalize_lifecycle_policy(*, kind: str, lifecycle_policy: str) -> str:
        normalized_kind = str(kind or "").strip().lower()
        normalized_policy = str(lifecycle_policy or "").strip().lower() or "normal"
        if normalized_policy not in {"normal", "ephemeral", "retained"}:
            normalized_policy = "normal"
        if normalized_kind in _SCREENSHOT_ATTACHMENT_KINDS and normalized_policy == "normal":
            return "ephemeral"
        return normalized_policy

    @staticmethod
    def _resolve_attachment_expires_at(*, lifecycle_policy: str, now: datetime) -> str | None:
        if lifecycle_policy != "ephemeral":
            return None
        return _iso(now + timedelta(seconds=_EPHEMERAL_ATTACHMENT_TTL_SECONDS))

    def _attachment_is_expired(self, attachment, *, now: datetime | None = None) -> bool:
        expires_at = str(getattr(attachment, "expires_at", "") or "").strip()
        if not expires_at:
            return False
        try:
            expires_at_dt = self._read_iso_datetime(expires_at)
        except ValueError:
            return False
        return expires_at_dt <= (now or _utcnow())

    def _delete_attachment_object(self, object_key: str) -> bool:
        deleter = getattr(self._object_store, "delete_object", None)
        if not callable(deleter):
            return False
        try:
            deleter(object_key)
        except FileNotFoundError:
            return False
        return True

    def _build_direct_download_url(self, attachment, *, expires_in_seconds: int, file_name: str) -> str:
        generator = getattr(self._object_store, "generate_presigned_download_url", None)
        if not callable(generator):
            return ""
        try:
            return str(
                generator(
                    attachment.object_key,
                    expires_in_seconds=max(int(expires_in_seconds or 0), _DOWNLOAD_TICKET_MIN_TTL_SECONDS),
                    file_name=file_name,
                    mime_type=str(getattr(attachment, "mime_type", "") or ""),
                )
                or ""
            ).strip()
        except Exception:
            return ""

    def create_upload_ticket(
        self,
        *,
        owner_type: str,
        owner_id: str,
        issuer_type: str,
        issuer_ref: str,
        kind: str,
        mime_type: str,
        file_name: str = "",
        size_bytes: int = 0,
        lifecycle_policy: str = "normal",
        origin_client_id=None,
        origin_agent_id=None,
        expires_in_seconds: int = 900,
    ):
        attachment_key = f"att_{uuid4().hex}"
        ticket_key = f"att_up_{uuid4().hex}"
        sanitized_name = self._sanitize_name(file_name)
        now = _utcnow()
        ticket_expires_at = _iso(now + timedelta(seconds=max(expires_in_seconds, _DOWNLOAD_TICKET_MIN_TTL_SECONDS)))
        normalized_lifecycle_policy = self._normalize_lifecycle_policy(kind=kind, lifecycle_policy=lifecycle_policy)
        attachment_expires_at = self._resolve_attachment_expires_at(
            lifecycle_policy=normalized_lifecycle_policy,
            now=now,
        )
        object_key = f"attachments/{attachment_key}/{sanitized_name}"
        with self.session_scope() as session:
            attachment_repo = AttachmentRepository(session)
            ticket_repo = AttachmentUploadTicketRepository(session)
            attachment = attachment_repo.create(
                attachment_id=attachment_key,
                owner_type=owner_type,
                owner_id=owner_id,
                origin_agent_id=origin_agent_id,
                origin_client_id=origin_client_id,
                kind=kind,
                mime_type=mime_type,
                object_key=object_key,
                size_bytes=size_bytes,
                lifecycle_policy=normalized_lifecycle_policy,
                expires_at=attachment_expires_at,
                status="pending_upload",
                metadata={
                    "file_name": sanitized_name,
                    **({"attachment_expires_at": attachment_expires_at} if attachment_expires_at else {}),
                },
            )
            ticket = ticket_repo.create(
                ticket_id=ticket_key,
                attachment_id=attachment.id,
                issuer_type=issuer_type,
                issuer_ref=issuer_ref,
                expires_at=ticket_expires_at,
                metadata={"attachment_id": attachment.attachment_id},
            )
            return attachment, ticket

    def get_upload_ticket(self, ticket_id: str):
        with self.session_scope() as session:
            return AttachmentUploadTicketRepository(session).get_by_ticket_id(ticket_id)

    def get_by_attachment_id(self, attachment_id: str):
        with self.session_scope() as session:
            return AttachmentRepository(session).get_by_attachment_id(attachment_id)

    def build_attachment_object_view(
        self,
        attachment,
        *,
        download_url: str = "",
        fallback_download_url: str = "",
        download_strategy: str = "",
    ) -> dict[str, object]:
        return {
            "attachment_id": attachment.attachment_id,
            "kind": attachment.kind,
            "mime_type": attachment.mime_type,
            "file_name": self._attachment_file_name(attachment),
            "size_bytes": self._coerce_size_bytes(getattr(attachment, "size_bytes", 0)),
            "lifecycle_policy": str(getattr(attachment, "lifecycle_policy", "") or "normal"),
            "expires_at": str(getattr(attachment, "expires_at", "") or ""),
            "status": str(getattr(attachment, "status", "") or "").strip(),
            "download_url": str(download_url or "").strip(),
            "fallback_download_url": str(fallback_download_url or "").strip(),
            "download_strategy": str(download_strategy or "").strip(),
        }

    def normalize_attachment_object_view(self, payload: dict | None) -> dict[str, object] | None:
        if not isinstance(payload, dict):
            return None
        attachment_id = str(payload.get("attachment_id") or "").strip()
        if not attachment_id:
            return None
        download_url = str(payload.get("download_url") or "").strip()
        fallback_download_url = str(payload.get("fallback_download_url") or "").strip()
        download_strategy = str(payload.get("download_strategy") or "").strip()
        attachment = self.get_by_attachment_id(attachment_id)
        if attachment is not None:
            return self.build_attachment_object_view(
                attachment,
                download_url=download_url,
                fallback_download_url=fallback_download_url,
                download_strategy=download_strategy,
            )
        return {
            "attachment_id": attachment_id,
            "kind": str(payload.get("kind") or "file").strip() or "file",
            "mime_type": str(payload.get("mime_type") or "application/octet-stream").strip() or "application/octet-stream",
            "file_name": self._sanitize_name(str(payload.get("file_name") or "").strip()),
            "size_bytes": self._coerce_size_bytes(payload.get("size_bytes")),
            "lifecycle_policy": str(payload.get("lifecycle_policy") or "normal").strip() or "normal",
            "expires_at": str(payload.get("expires_at") or "").strip(),
            "status": str(payload.get("status") or "").strip(),
            "download_url": download_url,
            "fallback_download_url": fallback_download_url,
            "download_strategy": download_strategy,
        }

    def normalize_attachment_object_views(self, payloads: list[dict] | None) -> list[dict[str, object]]:
        normalized: list[dict[str, object]] = []
        for item in payloads or []:
            view = self.normalize_attachment_object_view(item)
            if view is not None:
                normalized.append(view)
        return normalized

    def store_upload_content(self, ticket_id: str, content: bytes):
        now = _utcnow()
        with self.session_scope() as session:
            ticket_repo = AttachmentUploadTicketRepository(session)
            attachment_repo = AttachmentRepository(session)
            ticket = ticket_repo.get_by_ticket_id(ticket_id)
            if ticket is None:
                raise ValueError("attachment_upload_ticket_not_found")
            if ticket.status not in {"issued", "uploaded"}:
                raise ValueError("attachment_upload_ticket_invalid")
            if self._read_iso_datetime(ticket.expires_at) < now:
                raise ValueError("attachment_upload_ticket_expired")
            attachment = attachment_repo.get_by_id(ticket.attachment_id)
            if attachment is None:
                raise ValueError("attachment_not_found")
            if self._attachment_is_expired(attachment, now=now):
                raise ValueError("attachment_expired")

            file_name = self._attachment_file_name(attachment)
            self._object_store.put_bytes(attachment.object_key, content)
            digest = hashlib.sha256(content).hexdigest()
            attachment = attachment_repo.update_attachment(
                attachment.attachment_id,
                status="uploaded",
                size_bytes=len(content),
                sha256=digest,
                metadata={"file_name": file_name, "uploaded_at": _iso(now)},
            )
            ticket_repo.update_status(ticket_id, status="uploaded", metadata={"uploaded_at": _iso(now)})
            return attachment

    def complete_attachment(
        self,
        *,
        attachment_id: str,
        ticket_id: str = "",
        sha256: str = "",
        size_bytes: int | None = None,
    ):
        now = _utcnow()
        with self.session_scope() as session:
            attachment_repo = AttachmentRepository(session)
            ticket_repo = AttachmentUploadTicketRepository(session)
            attachment = attachment_repo.get_by_attachment_id(attachment_id)
            if attachment is None:
                raise ValueError("attachment_not_found")
            if self._attachment_is_expired(attachment, now=now):
                raise ValueError("attachment_expired")
            if ticket_id:
                ticket = ticket_repo.get_by_ticket_id(ticket_id)
                if ticket is None or ticket.attachment_id != attachment.id:
                    raise ValueError("attachment_upload_ticket_not_found")
                if ticket.status not in {"issued", "uploaded"}:
                    raise ValueError("attachment_upload_ticket_invalid")
                ticket_repo.update_status(ticket_id, status="completed", metadata={"completed_at": _iso(now)})
            if sha256 and attachment.sha256 and sha256 != attachment.sha256:
                raise ValueError("attachment_sha256_mismatch")
            attachment = attachment_repo.update_attachment(
                attachment_id,
                status="ready",
                size_bytes=size_bytes if size_bytes is not None else attachment.size_bytes,
                sha256=sha256 or attachment.sha256,
                metadata={"completed_at": _iso(now)},
            )
            return attachment

    def create_download_ticket(
        self,
        *,
        attachment_id: str,
        issuer_type: str,
        issuer_ref: str,
        expires_in_seconds: int = 300,
        fallback_download_url: str = "",
    ) -> dict:
        attachment = self.get_by_attachment_id(attachment_id)
        if attachment is None:
            raise ValueError("attachment_not_found")
        if attachment.status != "ready":
            raise ValueError("attachment_not_ready")
        if self._attachment_is_expired(attachment):
            raise ValueError("attachment_expired")
        ticket_id = f"att_down_{uuid4().hex}"
        normalized_expires_in_seconds = max(int(expires_in_seconds or 0), _DOWNLOAD_TICKET_MIN_TTL_SECONDS)
        expires_at = _iso(_utcnow() + timedelta(seconds=normalized_expires_in_seconds))
        self._download_tickets[ticket_id] = {
            "attachment_id": attachment_id,
            "issuer_type": issuer_type,
            "issuer_ref": issuer_ref,
            "expires_at": expires_at,
        }
        file_name = self._attachment_file_name(attachment)
        direct_download_url = self._build_direct_download_url(
            attachment,
            expires_in_seconds=normalized_expires_in_seconds,
            file_name=file_name,
        )
        download_strategy = "presigned" if direct_download_url else "proxy"
        selected_download_url = direct_download_url or str(fallback_download_url or "").strip()
        return {
            "ticket_id": ticket_id,
            "expires_at": expires_at,
            "attachment": attachment,
            "download_url": selected_download_url,
            "fallback_download_url": str(fallback_download_url or "").strip(),
            "download_strategy": download_strategy,
        }

    def validate_download_ticket(self, *, attachment_id: str, ticket_id: str):
        ticket = dict(self._download_tickets.get(ticket_id) or {})
        if not ticket:
            raise ValueError("attachment_download_ticket_not_found")
        if str(ticket.get("attachment_id") or "") != attachment_id:
            raise ValueError("attachment_download_ticket_not_found")
        if self._read_iso_datetime(str(ticket.get("expires_at") or "")) < _utcnow():
            self._download_tickets.pop(ticket_id, None)
            raise ValueError("attachment_download_ticket_expired")
        attachment = self.get_by_attachment_id(attachment_id)
        if attachment is None:
            raise ValueError("attachment_not_found")
        if self._attachment_is_expired(attachment):
            raise ValueError("attachment_expired")
        return attachment

    def resolve_attachment_path(self, attachment_id: str) -> Path:
        attachment = self.get_by_attachment_id(attachment_id)
        if attachment is None:
            raise ValueError("attachment_not_found")
        if self._attachment_is_expired(attachment):
            raise ValueError("attachment_expired")
        resolver = getattr(self._object_store, "resolve_path", None)
        if not callable(resolver):
            raise ValueError("attachment_path_unavailable")
        try:
            return resolver(attachment.object_key)
        except FileNotFoundError:
            raise ValueError("attachment_content_not_found")

    def read_attachment_bytes(self, attachment_id: str) -> bytes:
        attachment = self.get_by_attachment_id(attachment_id)
        if attachment is None:
            raise ValueError("attachment_not_found")
        if self._attachment_is_expired(attachment):
            raise ValueError("attachment_expired")
        reader = getattr(self._object_store, "read_bytes", None)
        if not callable(reader):
            raise ValueError("attachment_content_unavailable")
        try:
            return reader(attachment.object_key)
        except FileNotFoundError:
            raise ValueError("attachment_content_not_found")

    def purge_expired_download_tickets(self, *, now: datetime | None = None) -> int:
        current_time = now or _utcnow()
        expired_ticket_ids = []
        for ticket_id, ticket in list(self._download_tickets.items()):
            expires_at = str(ticket.get("expires_at") or "").strip()
            if not expires_at:
                continue
            try:
                expires_at_dt = self._read_iso_datetime(expires_at)
            except ValueError:
                continue
            if expires_at_dt <= current_time:
                expired_ticket_ids.append(ticket_id)
        for ticket_id in expired_ticket_ids:
            self._download_tickets.pop(ticket_id, None)
        return len(expired_ticket_ids)

    def cleanup_expired_resources(self, *, now: datetime | None = None) -> dict[str, int]:
        current_time = now or _utcnow()
        current_time_iso = _iso(current_time)
        counters = {
            "expired_download_tickets": self.purge_expired_download_tickets(now=current_time),
            "expired_upload_tickets": 0,
            "expired_attachments": 0,
            "deleted_objects": 0,
        }
        expired_attachment_ids: set[str] = set()
        with self.session_scope() as session:
            attachment_repo = AttachmentRepository(session)
            ticket_repo = AttachmentUploadTicketRepository(session)
            upload_tickets = list(session.query(AttachmentUploadTicket).all())
            attachments = list(session.query(Attachment).all())

            for ticket in upload_tickets:
                if str(getattr(ticket, "status", "") or "").strip() in {"completed", "expired"}:
                    continue
                try:
                    expires_at_dt = self._read_iso_datetime(str(ticket.expires_at or ""))
                except ValueError:
                    continue
                if expires_at_dt > current_time:
                    continue
                ticket_repo.update_status(
                    ticket.ticket_id,
                    status="expired",
                    metadata={"expired_at": current_time_iso},
                )
                counters["expired_upload_tickets"] += 1
                attachment = attachment_repo.get_by_id(ticket.attachment_id)
                if attachment is None:
                    continue
                if str(getattr(attachment, "status", "") or "").strip() in {"expired", "deleted", "ready"}:
                    continue
                if self._delete_attachment_object(str(getattr(attachment, "object_key", "") or "")):
                    counters["deleted_objects"] += 1
                attachment_repo.update_attachment(
                    attachment.attachment_id,
                    status="expired",
                    metadata={
                        "expired_at": current_time_iso,
                        "expired_reason": "upload_ticket_expired",
                    },
                )
                expired_attachment_ids.add(attachment.attachment_id)
                counters["expired_attachments"] += 1

            for attachment in attachments:
                attachment_id = str(getattr(attachment, "attachment_id", "") or "").strip()
                if not attachment_id or attachment_id in expired_attachment_ids:
                    continue
                if str(getattr(attachment, "status", "") or "").strip() in {"expired", "deleted"}:
                    continue
                if not self._attachment_is_expired(attachment, now=current_time):
                    continue
                if self._delete_attachment_object(str(getattr(attachment, "object_key", "") or "")):
                    counters["deleted_objects"] += 1
                attachment_repo.update_attachment(
                    attachment.attachment_id,
                    status="expired",
                    metadata={
                        "expired_at": current_time_iso,
                        "expired_reason": "attachment_ttl_expired",
                    },
                )
                counters["expired_attachments"] += 1
        return counters
