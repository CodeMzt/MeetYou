"""
飞书输入适配器。
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from adapters.feishu_ws_client import FeishuWSClient
from core.io_protocol import (
    ConfirmResponseEvent,
    EventTarget,
    EventType,
    InboundEvent,
    SourceKind,
    TargetKind,
    make_source,
)

logger = logging.getLogger("meetyou.feishu_input")


def _parse_confirm_response(text: str) -> bool | None:
    normalized = text.strip().lower()
    accepted_tokens = {"y", "yes", "确认", "同意", "允许"}
    rejected_tokens = {"n", "no", "拒绝", "取消", "不同意"}
    if normalized in accepted_tokens:
        return True
    if normalized in rejected_tokens:
        return False
    return None


class FeishuInputAdapter:
    def __init__(self, event_bus, session_manager, config):
        self._event_bus = event_bus
        self._session_manager = session_manager
        self._config = config
        self._chat_registry_path = Path(
            self._config.get("feishu_chat_registry_path") or "user/feishu_chat_ids.json"
        )
        self._known_chat_ids = self._load_known_chat_ids()
        self._client = FeishuWSClient(
            self._config.get("feishu_app_id") or "",
            self._config.get("feishu_app_secret") or "",
            self.handle_event,
        )

    def _load_known_chat_ids(self) -> set[str]:
        if not self._chat_registry_path.exists():
            return set()
        try:
            with self._chat_registry_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            logger.warning(f"读取飞书 chat_id 记录失败: {e}")
            return set()

        chats = payload.get("chats", [])
        if not isinstance(chats, list):
            return set()
        return {
            str(item.get("chat_id", "")).strip()
            for item in chats
            if isinstance(item, dict) and str(item.get("chat_id", "")).strip()
        }

    def _write_chat_registry(self, chat_id: str, message: dict, sender_id: str):
        self._chat_registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"chats": []}
        if self._chat_registry_path.exists():
            try:
                with self._chat_registry_path.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception as e:
                logger.warning(f"读取飞书 chat_id 记录失败，准备覆盖写入: {e}")
                payload = {"chats": []}

        chats = payload.get("chats")
        if not isinstance(chats, list):
            chats = []
            payload["chats"] = chats

        now = datetime.now(timezone.utc).isoformat()
        existing = None
        for item in chats:
            if isinstance(item, dict) and item.get("chat_id") == chat_id:
                existing = item
                break

        if existing is None:
            chats.append({
                "chat_id": chat_id,
                "chat_type": message.get("chat_type", ""),
                "sender_id": sender_id,
                "last_message_id": message.get("message_id", ""),
                "first_seen_at": now,
                "last_seen_at": now,
            })
        else:
            existing["chat_type"] = message.get("chat_type", existing.get("chat_type", ""))
            existing["sender_id"] = sender_id or existing.get("sender_id", "")
            existing["last_message_id"] = message.get("message_id", "")
            existing["last_seen_at"] = now

        with self._chat_registry_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _record_chat_id(self, chat_id: str, message: dict, sender_id: str):
        try:
            self._write_chat_registry(chat_id, message, sender_id)
            if chat_id not in self._known_chat_ids:
                logger.info(
                    "已记录新的飞书 chat_id: %s，已写入 %s",
                    chat_id,
                    self._chat_registry_path.as_posix(),
                )
                self._known_chat_ids.add(chat_id)
        except Exception as e:
            logger.error(f"写入飞书 chat_id 记录失败: {e}")

    async def handle_event(self, payload: dict):
        event = payload.get("event", {})
        message = event.get("message", {})
        sender = event.get("sender", {})
        chat_id = message.get("chat_id", "")
        if not chat_id:
            return

        content_raw = message.get("content", "{}")
        try:
            content_obj = json.loads(content_raw)
        except json.JSONDecodeError:
            content_obj = {"text": content_raw}
        text = (content_obj.get("text") or "").strip()
        if not text:
            return

        sender_id = (
            sender.get("sender_id", {}).get("user_id")
            or sender.get("sender_id", {}).get("open_id")
            or ""
        )
        self._record_chat_id(chat_id, message, sender_id)
        source = make_source(
            SourceKind.FEISHU.value,
            chat_id,
            sender_id=sender_id,
            message_id=message.get("message_id", ""),
            chat_type=message.get("chat_type", ""),
        )
        session_id = self._session_manager.get_or_create_session(
            source,
            session_id=f"feishu:chat:{chat_id}",
        )
        confirm_value = _parse_confirm_response(text)
        if (
            confirm_value is not None
            and self._event_bus.has_pending_confirmation
            and session_id == self._event_bus.pending_confirmation_session_id
        ):
            await self._event_bus.inbound_queue.put(
                ConfirmResponseEvent(
                    session_id=session_id,
                    type=EventType.CONFIRM_RESPONSE.value,
                    role="user",
                    content=text,
                    source=source,
                    target=EventTarget(kind=TargetKind.INTERNAL.value),
                    request_id=self._event_bus.pending_request_id,
                    accepted=confirm_value,
                    metadata={
                        "message_id": message.get("message_id", ""),
                        "chat_id": chat_id,
                        "chat_type": message.get("chat_type", ""),
                    },
                )
            )
            return
        await self._event_bus.inbound_queue.put(
            InboundEvent(
                session_id=session_id,
                type=EventType.MESSAGE.value,
                role="user",
                content=text,
                source=source,
                target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                metadata={
                    "message_id": message.get("message_id", ""),
                    "chat_id": chat_id,
                    "chat_type": message.get("chat_type", ""),
                },
            )
        )

    async def run(self):
        await self._client.start()

    async def close(self):
        await self._client.stop()
