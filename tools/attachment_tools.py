from __future__ import annotations

import base64
from typing import Any


class AttachmentTools:
    def __init__(self) -> None:
        self._core_domain = None

    def set_core_domain(self, core_domain) -> None:
        self._core_domain = core_domain

    def _require_core_domain(self):
        if self._core_domain is None:
            error = RuntimeError("Core domain is not ready")
            error.tool_error_code = "core_domain_unavailable"
            error.tool_error_message = "Attachment tools are unavailable before the Core domain finishes booting."
            error.tool_error_retryable = True
            raise error
        return self._core_domain

    @staticmethod
    def _raise_tool_error(code: str, message: str, **details) -> None:
        error = RuntimeError(message)
        error.tool_error_code = code
        error.tool_error_message = message
        error.tool_error_details = dict(details or {})
        raise error

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        try:
            return min(max(int(limit or 0), 1), 100)
        except (TypeError, ValueError):
            return 20

    @staticmethod
    def _normalize_max_bytes(max_bytes: int) -> int:
        try:
            return min(max(int(max_bytes or 0), 1), 1024 * 1024)
        except (TypeError, ValueError):
            return 8192

    @staticmethod
    def _is_text_like_mime_type(mime_type: str) -> bool:
        normalized = str(mime_type or "").strip().lower()
        return normalized.startswith("text/") or normalized in {
            "application/json",
            "application/xml",
            "application/javascript",
        }

    @staticmethod
    def _decode_preview(content: bytes, *, mime_type: str, encoding: str, max_bytes: int) -> dict[str, Any]:
        clipped = bytes(content[:max_bytes])
        preview = {
            "bytes_read": len(clipped),
            "content_truncated": len(content) > len(clipped),
            "content_encoding": str(encoding or "utf-8").strip() or "utf-8",
        }
        if AttachmentTools._is_text_like_mime_type(mime_type):
            preview["content_text"] = clipped.decode(preview["content_encoding"], errors="replace")
            return preview
        preview["content_base64"] = base64.b64encode(clipped).decode("ascii")
        return preview

    async def list_attachments(
        self,
        *,
        owner_type: str,
        owner_id: str,
        include_deleted: bool = False,
        limit: int = 20,
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> dict[str, Any]:
        del session_id, source, route_context, activity_callback
        domain = self._require_core_domain()
        try:
            attachments = domain.services.attachment.list_attachments(
                owner_type=owner_type,
                owner_id=owner_id,
                include_deleted=include_deleted,
                limit=self._normalize_limit(limit),
            )
        except ValueError as exc:
            self._raise_tool_error(str(exc), f"Failed to list attachments: {exc}")
        return {
            "owner_type": str(owner_type or "").strip(),
            "owner_id": str(owner_id or "").strip(),
            "count": len(attachments),
            "attachments": attachments,
        }

    async def read_attachment(
        self,
        *,
        attachment_id: str,
        include_content: bool = False,
        include_deleted: bool = False,
        encoding: str = "utf-8",
        max_bytes: int = 8192,
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> dict[str, Any]:
        del session_id, source, route_context, activity_callback
        domain = self._require_core_domain()
        try:
            attachment = domain.services.attachment.get_attachment_record(
                attachment_id=str(attachment_id or "").strip(),
                include_deleted=include_deleted,
            )
        except ValueError as exc:
            self._raise_tool_error(str(exc), f"Failed to read attachment metadata: {exc}", attachment_id=attachment_id)
        if not include_content:
            return attachment
        try:
            content = domain.services.attachment.read_attachment_bytes(str(attachment_id or "").strip())
        except ValueError as exc:
            self._raise_tool_error(str(exc), f"Failed to read attachment content: {exc}", attachment_id=attachment_id)
        attachment.update(
            self._decode_preview(
                content,
                mime_type=str(attachment.get("mime_type") or ""),
                encoding=encoding,
                max_bytes=self._normalize_max_bytes(max_bytes),
            )
        )
        return attachment

    async def delete_attachment(
        self,
        *,
        attachment_id: str,
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> dict[str, Any]:
        del session_id, source, route_context, activity_callback
        domain = self._require_core_domain()
        try:
            return domain.services.attachment.delete_attachment(str(attachment_id or "").strip())
        except ValueError as exc:
            self._raise_tool_error(str(exc), f"Failed to delete attachment: {exc}", attachment_id=attachment_id)
