from __future__ import annotations

import inspect
from typing import Any


class InteractionResponseService:
    def __init__(self, event_bus) -> None:
        self._event_bus = event_bus

    @staticmethod
    def _call_with_supported_kwargs(callable_obj, *args, **kwargs):
        try:
            signature = inspect.signature(callable_obj)
        except (TypeError, ValueError):
            return callable_obj(*args, **kwargs)
        supported = {
            key: value
            for key, value in kwargs.items()
            if key in signature.parameters
        }
        return callable_obj(*args, **supported)

    def has_pending_confirmation(self, *, session_id: str = "") -> bool:
        if not bool(getattr(self._event_bus, "has_pending_confirmation", False)):
            return False
        pending_session_id = str(getattr(self._event_bus, "pending_confirmation_session_id", "") or "")
        return not session_id or pending_session_id == str(session_id or "")

    def get_confirmation_status(self, *, session_id: str = "") -> dict[str, Any]:
        pending = self.has_pending_confirmation(session_id=session_id)
        resolved_session_id = str(getattr(self._event_bus, "pending_confirmation_session_id", "") or "") if pending else ""
        return {
            "pending": pending,
            "session_id": resolved_session_id,
            "request_id": self.get_pending_confirmation_request_id(session_id=session_id) if pending else "",
        }

    def get_pending_confirmation_request_id(self, *, session_id: str = "") -> str:
        if not self.has_pending_confirmation(session_id=session_id):
            return ""
        return str(getattr(self._event_bus, "pending_request_id", "") or "")

    def get_pending_human_input_request(self, *, session_id: str = ""):
        getter = getattr(self._event_bus, "get_pending_human_input_request", None)
        if callable(getter):
            return getter(session_id=session_id)
        return None

    def get_human_input_status(self, *, session_id: str = "") -> dict[str, Any]:
        pending = self.get_pending_human_input_request(session_id=session_id)
        return {
            "pending": pending is not None,
            "request_id": str(getattr(pending, "request_id", "") or ""),
            "session_id": str(getattr(pending, "session_id", "") or ""),
            "question": str(getattr(pending, "question", "") or ""),
        }

    def normalize_human_input_text(self, text: str, *, session_id: str = "") -> dict[str, Any] | None:
        normalizer = getattr(self._event_bus, "normalize_human_input_text", None)
        if callable(normalizer):
            return normalizer(text, session_id=session_id)
        return None

    def submit_confirmation_response(
        self,
        accepted: bool,
        *,
        request_id: str = "",
        session_id: str = "",
        endpoint_id: str = "",
        approval_id: str = "",
        reason: str = "",
    ) -> bool:
        submitter = getattr(self._event_bus, "submit_confirmation_response", None)
        if not callable(submitter):
            return False
        return bool(
            self._call_with_supported_kwargs(
                submitter,
                accepted,
                request_id=request_id,
                session_id=session_id,
                endpoint_id=endpoint_id,
                approval_id=approval_id,
                reason=reason,
            )
        )

    def submit_human_input_response(
        self,
        answer_text: str = "",
        *,
        request_id: str = "",
        session_id: str = "",
        selected_option: str | None = None,
    ) -> bool:
        submitter = getattr(self._event_bus, "submit_human_input_response", None)
        if not callable(submitter):
            return False
        return bool(
            self._call_with_supported_kwargs(
                submitter,
                answer_text,
                request_id=request_id,
                session_id=session_id,
                selected_option=selected_option,
            )
        )
