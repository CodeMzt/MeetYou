from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass


class ProviderEventBus:
    has_pending_confirmation = False
    pending_confirmation_session_id = ""
    pending_request_id = ""

    def get_pending_human_input_request(self, *, session_id: str = ""):
        del session_id
        return None

    def normalize_human_input_text(self, text: str, *, session_id: str = ""):
        del text, session_id
        return None

    def submit_confirmation_response(self, accepted: bool, **kwargs) -> bool:
        del accepted, kwargs
        return False

    def submit_human_input_response(self, answer_text: str = "", **kwargs) -> bool:
        del answer_text, kwargs
        return False


@dataclass(frozen=True)
class _InboundKey:
    session_id: str
    source_kind: str
    source_id: str
    message_id: str


class ProviderSessionManager:
    def __init__(self, max_recent: int = 4096):
        self._max_recent = max(128, int(max_recent or 4096))
        self._recent: dict[_InboundKey, str] = {}

    @staticmethod
    def _source_part(source, name: str) -> str:
        if isinstance(source, dict):
            return str(source.get(name) or "").strip()
        return str(getattr(source, name, "") or "").strip()

    def get_recent_inbound_event_id(self, session_id: str, source, message_id: str) -> str:
        key = _InboundKey(
            session_id=str(session_id or "").strip(),
            source_kind=self._source_part(source, "kind"),
            source_id=self._source_part(source, "id"),
            message_id=str(message_id or "").strip(),
        )
        return self._recent.get(key, "")

    def remember_inbound_event_id(self, session_id: str, source, message_id: str, event_id: str) -> None:
        if len(self._recent) >= self._max_recent:
            self._recent.clear()
        key = _InboundKey(
            session_id=str(session_id or "").strip(),
            source_kind=self._source_part(source, "kind"),
            source_id=self._source_part(source, "id"),
            message_id=str(message_id or "").strip(),
        )
        self._recent[key] = str(event_id or "").strip()


async def wait_until_stopped() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, signal_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass
    await stop_event.wait()
