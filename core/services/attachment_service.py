from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from core.db.repositories import AttachmentRepository, AttachmentUploadTicketRepository
from core.services.base import ServiceBase
from core.storage.object_store import LocalObjectStore


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
        expires_at = _iso(_utcnow() + timedelta(seconds=max(expires_in_seconds, 60)))
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
                lifecycle_policy=lifecycle_policy,
                status="pending_upload",
                metadata={"file_name": sanitized_name},
            )
            ticket = ticket_repo.create(
                ticket_id=ticket_key,
                attachment_id=attachment.id,
                issuer_type=issuer_type,
                issuer_ref=issuer_ref,
                expires_at=expires_at,
                metadata={"attachment_id": attachment.attachment_id},
            )
            return attachment, ticket

    def get_upload_ticket(self, ticket_id: str):
        with self.session_scope() as session:
            return AttachmentUploadTicketRepository(session).get_by_ticket_id(ticket_id)

    def get_by_attachment_id(self, attachment_id: str):
        with self.session_scope() as session:
            return AttachmentRepository(session).get_by_attachment_id(attachment_id)

    def build_attachment_object_view(self, attachment, *, download_url: str = "") -> dict[str, object]:
        return {
            "attachment_id": attachment.attachment_id,
            "kind": attachment.kind,
            "mime_type": attachment.mime_type,
            "file_name": self._attachment_file_name(attachment),
            "size_bytes": self._coerce_size_bytes(getattr(attachment, "size_bytes", 0)),
            "status": str(getattr(attachment, "status", "") or "").strip(),
            "download_url": str(download_url or "").strip(),
        }

    def normalize_attachment_object_view(self, payload: dict | None) -> dict[str, object] | None:
        if not isinstance(payload, dict):
            return None
        attachment_id = str(payload.get("attachment_id") or "").strip()
        if not attachment_id:
            return None
        download_url = str(payload.get("download_url") or "").strip()
        attachment = self.get_by_attachment_id(attachment_id)
        if attachment is not None:
            return self.build_attachment_object_view(attachment, download_url=download_url)
        return {
            "attachment_id": attachment_id,
            "kind": str(payload.get("kind") or "file").strip() or "file",
            "mime_type": str(payload.get("mime_type") or "application/octet-stream").strip() or "application/octet-stream",
            "file_name": self._sanitize_name(str(payload.get("file_name") or "").strip()),
            "size_bytes": self._coerce_size_bytes(payload.get("size_bytes")),
            "status": str(payload.get("status") or "").strip(),
            "download_url": download_url,
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

            file_name = self._attachment_file_name(attachment)
            path = self._attachment_path(attachment.attachment_id, file_name)
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
        with self.session_scope() as session:
            attachment_repo = AttachmentRepository(session)
            ticket_repo = AttachmentUploadTicketRepository(session)
            attachment = attachment_repo.get_by_attachment_id(attachment_id)
            if attachment is None:
                raise ValueError("attachment_not_found")
            if ticket_id:
                ticket = ticket_repo.get_by_ticket_id(ticket_id)
                if ticket is None or ticket.attachment_id != attachment.id:
                    raise ValueError("attachment_upload_ticket_not_found")
                if ticket.status not in {"issued", "uploaded"}:
                    raise ValueError("attachment_upload_ticket_invalid")
                ticket_repo.update_status(ticket_id, status="completed", metadata={"completed_at": _iso(_utcnow())})
            if sha256 and attachment.sha256 and sha256 != attachment.sha256:
                raise ValueError("attachment_sha256_mismatch")
            attachment = attachment_repo.update_attachment(
                attachment_id,
                status="ready",
                size_bytes=size_bytes if size_bytes is not None else attachment.size_bytes,
                sha256=sha256 or attachment.sha256,
                metadata={"completed_at": _iso(_utcnow())},
            )
            return attachment

    def create_download_ticket(self, *, attachment_id: str, issuer_type: str, issuer_ref: str, expires_in_seconds: int = 300) -> dict:
        attachment = self.get_by_attachment_id(attachment_id)
        if attachment is None:
            raise ValueError("attachment_not_found")
        if attachment.status != "ready":
            raise ValueError("attachment_not_ready")
        ticket_id = f"att_down_{uuid4().hex}"
        expires_at = _iso(_utcnow() + timedelta(seconds=max(expires_in_seconds, 60)))
        self._download_tickets[ticket_id] = {
            "attachment_id": attachment_id,
            "issuer_type": issuer_type,
            "issuer_ref": issuer_ref,
            "expires_at": expires_at,
        }
        return {
            "ticket_id": ticket_id,
            "expires_at": expires_at,
            "attachment": attachment,
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
        return attachment

    def resolve_attachment_path(self, attachment_id: str) -> Path:
        attachment = self.get_by_attachment_id(attachment_id)
        if attachment is None:
            raise ValueError("attachment_not_found")
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
        reader = getattr(self._object_store, "read_bytes", None)
        if not callable(reader):
            raise ValueError("attachment_content_unavailable")
        try:
            return reader(attachment.object_key)
        except FileNotFoundError:
            raise ValueError("attachment_content_not_found")
