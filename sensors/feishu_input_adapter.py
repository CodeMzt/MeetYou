"""
飞书输入适配器。
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from clients.gateway_client import GatewayConversationClient
from adapters.feishu_ws_client import FeishuWSClient
from core.client_tool_bundles import EXTERNAL_CLIENT_BASIC_TOOL_BUNDLE
from core.interaction_response_service import InteractionResponseService
from core.io_protocol import (
    SourceKind,
    make_source,
)

logger = logging.getLogger("meetyou.feishu_input")

_DANXI_MODE_KEYWORDS = (
    "danxi",
    "旦夕",
    "fduhole",
    "论坛",
    "帖子",
    "楼层",
    "分区",
    "收藏",
    "订阅",
    "webvpn",
)


def _parse_confirm_response(text: str) -> bool | None:
    normalized = text.strip().lower()
    accepted_tokens = {"y", "yes", "确认", "同意", "允许"}
    rejected_tokens = {"n", "no", "拒绝", "取消", "不同意"}
    if normalized in accepted_tokens:
        return True
    if normalized in rejected_tokens:
        return False
    return None


def _infer_preferred_mode(text: str) -> str | None:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return None
    for keyword in _DANXI_MODE_KEYWORDS:
        if keyword.lower() in normalized:
            return "danxi"
    return None


class FeishuInputAdapter:
    def __init__(self, event_bus, session_manager, config, output_adapter=None):
        self._event_bus = event_bus
        self._interaction_responses = InteractionResponseService(event_bus)
        self._session_manager = session_manager
        self._config = config
        self._output_adapter = output_adapter
        self._formal_client_chain_enabled = output_adapter is not None
        self._app_id = str(self._config.get("feishu_app_id") or "").strip()
        self._chat_registry_path = Path(
            self._config.get("feishu_chat_registry_path") or "user/feishu_chat_ids.json"
        )
        self._known_chat_ids = self._load_known_chat_ids()
        self._gateway_clients: dict[str, GatewayConversationClient] = {}
        host = str(self._config.get("gateway_host") or "127.0.0.1").strip() or "127.0.0.1"
        if host in {"0.0.0.0", "::", "::0"}:
            host = "127.0.0.1"
        port = int(self._config.get("gateway_port") or 8000)
        self._gateway_base_url = f"http://{host}:{port}"
        self._gateway_access_token = str(self._config.get("gateway_access_token") or "").strip()
        self._client = FeishuWSClient(
            self._app_id,
            self._config.get("feishu_app_secret") or "",
            self.handle_event,
        )
        if self._formal_client_chain_enabled:
            logger.info("Feishu 输入已切到 Endpoint API + /endpoint/ws 正式主链。")
        else:
            logger.warning("Feishu 输入仍处于兼容事件总线模式；正式运行请通过 Endpoint API + /endpoint/ws 主链接入。")

    def _use_formal_client_chain(self) -> bool:
        return self._formal_client_chain_enabled

    async def _get_gateway_client(self, chat_id: str) -> GatewayConversationClient:
        client = self._gateway_clients.get(chat_id)
        if client is None:
            client = GatewayConversationClient(
                base_url=self._gateway_base_url,
                client_id=f"feishu-{chat_id}",
                client_type="feishu",
                display_name=f"Feishu {chat_id}",
                workspace_id="personal",
                access_token=self._gateway_access_token,
                thread_title=f"Feishu Chat {chat_id}",
                event_handler=lambda payload, cid=chat_id: self._output_adapter.send_client_event(cid, payload),
            )
            self._gateway_clients[chat_id] = client
        await client.start()
        return client

    def _is_self_message(self, sender: dict) -> bool:
        sender = sender or {}
        sender_type = str(sender.get("sender_type") or "").strip().lower()
        if sender_type in {"app", "bot"}:
            return True

        sender_id = sender.get("sender_id", {}) or {}
        app_id = str(sender_id.get("app_id") or "").strip()
        if app_id and self._app_id and app_id == self._app_id:
            return True
        return False

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
        if self._is_self_message(sender):
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
        if self._use_formal_client_chain():
            client = await self._get_gateway_client(chat_id)
            confirm_value = _parse_confirm_response(text)
            pending_confirm = self._output_adapter.get_pending_confirm_request(chat_id)
            if confirm_value is not None and pending_confirm:
                try:
                    await client.submit_confirm_response(
                        request_id=pending_confirm,
                        accepted=confirm_value,
                    )
                except Exception:
                    await client.send_command(
                        "confirm_response",
                        request_id=pending_confirm,
                        accepted=confirm_value,
                        metadata={"source": "feishu", "chat_id": chat_id},
                    )
                return
            pending_human_input = self._output_adapter.resolve_human_input(chat_id, text)
            if pending_human_input is not None:
                try:
                    await client.submit_human_input_response(
                        request_id=pending_human_input.get("request_id", ""),
                        answer_text=pending_human_input.get("answer_text", ""),
                        selected_option=pending_human_input.get("selected_option"),
                    )
                except Exception:
                    await client.send_command(
                        "input_response",
                        request_id=pending_human_input.get("request_id", ""),
                        answer_text=pending_human_input.get("answer_text", ""),
                        selected_option=pending_human_input.get("selected_option"),
                        metadata={"source": "feishu", "chat_id": chat_id},
                    )
                return
            await client.send_message(
                text,
                metadata={
                    "source": "feishu",
                    "transport": "feishu",
                    "response_transport": "non_streaming_external_client",
                    "supports_streaming_reply": False,
                    "progress_notice_policy": "prefer_before_nontrivial_final",
                    "tool_scope": "basic",
                    "allowed_tool_bundle": list(EXTERNAL_CLIENT_BASIC_TOOL_BUNDLE),
                    "allowed_mcp_servers": [],
                    "message_id": message.get("message_id", ""),
                    "chat_id": chat_id,
                    "chat_type": message.get("chat_type", ""),
                },
                preferred_mode=_infer_preferred_mode(text),
            )
            return

        session_id = self._session_manager.bind_runtime_session(
            source,
            session_id=f"feishu:chat:{chat_id}",
        )
        interaction_responses = getattr(self, "_interaction_responses", None) or InteractionResponseService(self._event_bus)
        message_id = str(message.get("message_id", "")).strip()
        if message_id:
            existing_event_id = self._session_manager.get_recent_inbound_event_id(
                session_id,
                source,
                message_id,
            )
            if existing_event_id:
                return
        confirm_value = _parse_confirm_response(text)
        if confirm_value is not None and interaction_responses.has_pending_confirmation(session_id=session_id):
            if message_id:
                self._session_manager.remember_inbound_event_id(
                    session_id,
                    source,
                    message_id,
                    f"feishu-confirm:{message_id}",
                )
            interaction_responses.submit_confirmation_response(
                confirm_value,
                request_id=interaction_responses.get_pending_confirmation_request_id(session_id=session_id),
                session_id=session_id,
                client_id="feishu-bot",
            )
            return
        if interaction_responses.get_pending_human_input_request(session_id=session_id) is not None:
            response = interaction_responses.normalize_human_input_text(text, session_id=session_id)
            if response is not None:
                if message_id:
                    self._session_manager.remember_inbound_event_id(
                        session_id,
                        source,
                        message_id,
                        f"feishu-human-input:{message_id}",
                    )
                interaction_responses.submit_human_input_response(
                    response.get("answer_text", ""),
                    request_id=response.get("request_id", ""),
                    session_id=response.get("session_id", session_id),
                    selected_option=response.get("selected_option"),
                )
                return
        from core.io_protocol import EventTarget, EventType, InboundEvent, TargetKind

        inbound_event = InboundEvent(
            session_id=session_id,
            type=EventType.MESSAGE.value,
            role="user",
            content=text,
            source=source,
            target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
            metadata={
                "message_id": message_id,
                "chat_id": chat_id,
                "chat_type": message.get("chat_type", ""),
            },
        )
        if message_id:
            remembered_event_id = self._session_manager.remember_inbound_event_id(
                session_id,
                source,
                message_id,
                inbound_event.event_id,
            )
            if remembered_event_id != inbound_event.event_id:
                return
        await self._event_bus.inbound_queue.put(inbound_event)

    async def run(self):
        await self._client.start()

    async def close(self):
        for client in self._gateway_clients.values():
            await client.close()
        self._gateway_clients.clear()
        await self._client.stop()

