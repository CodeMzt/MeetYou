"""
飞书输入适配器。
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from clients.gateway_client import GatewayConversationClient, resolve_core_base_url
from adapters.feishu_ws_client import FeishuWSClient
from core.endpoint_tool_bundles import EXTERNAL_ENDPOINT_BASIC_TOOL_BUNDLE
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
        self._session_manager = session_manager
        self._config = config
        self._output_adapter = output_adapter
        self._app_id = str(self._config.get("feishu_app_id") or "").strip()
        self._chat_registry_path = Path(
            self._config.get("feishu_chat_registry_path") or "user/feishu_chat_ids.json"
        )
        self._known_chat_ids = self._load_known_chat_ids()
        self._gateway_clients: dict[str, GatewayConversationClient] = {}
        self._provider_gateway_client: GatewayConversationClient | None = None
        self._gateway_base_url = resolve_core_base_url(self._config)
        self._gateway_access_token = str(self._config.get("gateway_access_token") or "").strip()
        self._client = FeishuWSClient(
            self._app_id,
            self._config.get("feishu_app_secret") or "",
            self.handle_event,
        )
        logger.info("Feishu 输入使用 Endpoint API + /endpoint/ws 主链。")

    @property
    def _provider_endpoint_id(self) -> str:
        return "feishu.provider.ui"

    def _configured_chat_ids(self) -> set[str]:
        values: list[str] = []
        default_chat_id = str(self._config.get("feishu_default_chat_id") or "").strip()
        if default_chat_id:
            values.append(default_chat_id)
        raw_broadcast = self._config.get("feishu_broadcast_chat_ids") or []
        if isinstance(raw_broadcast, str):
            values.extend(item.strip() for item in raw_broadcast.split(","))
        elif isinstance(raw_broadcast, list):
            values.extend(str(item).strip() for item in raw_broadcast)
        return {item for item in values if item}

    def _address_payload(self, chat_id: str, *, chat_type: str = "", display_name: str = "") -> dict:
        normalized_chat_id = str(chat_id or "").strip()
        normalized_type = str(chat_type or "").strip().lower()
        address_type = "group" if normalized_type in {"group", "group_chat"} else "direct"
        return {
            "address_id": f"addr.feishu.{address_type}.{normalized_chat_id}",
            "provider_type": "feishu",
            "address_type": address_type,
            "external_ref": normalized_chat_id,
            "display_name": display_name or f"Feishu {normalized_chat_id}",
            "workspace_ids": ["personal"],
            "status": "sendable",
            "capabilities": ["receive_message"],
            "supports_markdown": False,
            "metadata": {"chat_type": normalized_type, "supports_markdown": False},
        }

    async def _get_provider_gateway_client(self) -> GatewayConversationClient:
        if self._provider_gateway_client is None:
            known_chat_ids = sorted(self._known_chat_ids | self._configured_chat_ids())
            self._provider_gateway_client = GatewayConversationClient(
                base_url=self._gateway_base_url,
                provider_id="feishu-provider",
                provider_type="feishu",
                display_name="Feishu Provider",
                workspace_id="personal",
                access_token=self._gateway_access_token,
                thread_title="Feishu Provider",
                endpoint_id=self._provider_endpoint_id,
                endpoint_addresses=[self._address_payload(chat_id) for chat_id in known_chat_ids],
                supports_markdown=False,
                event_handler=(
                    (lambda payload: self._output_adapter.send_runtime_event("", payload))
                    if self._output_adapter is not None
                    else None
                ),
            )
        await self._provider_gateway_client.start()
        return self._provider_gateway_client

    async def _get_gateway_client(self, chat_id: str) -> GatewayConversationClient:
        client = self._gateway_clients.get(chat_id)
        if client is None:
            client = GatewayConversationClient(
                base_url=self._gateway_base_url,
                provider_id=f"feishu-chat-{chat_id}",
                provider_type="feishu",
                display_name=f"Feishu {chat_id}",
                workspace_id="personal",
                access_token=self._gateway_access_token,
                thread_title=f"Feishu Chat {chat_id}",
                endpoint_id=self._provider_endpoint_id,
                supports_markdown=False,
                event_handler=(
                    (lambda payload, cid=chat_id: self._output_adapter.send_runtime_event(cid, payload))
                    if self._output_adapter is not None
                    else None
                ),
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
        client = await self._get_gateway_client(chat_id)
        with __import__("contextlib").suppress(Exception):
            await client.upsert_address(self._address_payload(chat_id, chat_type=message.get("chat_type", "")))
        source = make_source(
            SourceKind.FEISHU.value,
            chat_id,
            sender_id=sender_id,
            message_id=message.get("message_id", ""),
            chat_type=message.get("chat_type", ""),
        )
        message_id = str(message.get("message_id", "")).strip()
        if message_id:
            dedupe_session_id = f"feishu:chat:{chat_id}"
            existing_event_id = self._session_manager.get_recent_inbound_event_id(
                dedupe_session_id,
                source,
                message_id,
            )
            if existing_event_id:
                return
            self._session_manager.remember_inbound_event_id(
                dedupe_session_id,
                source,
                message_id,
                f"feishu-endpoint:{message_id}",
            )
        confirm_value = _parse_confirm_response(text)
        pending_confirm = (
            self._output_adapter.get_pending_confirm_request(chat_id)
            if self._output_adapter is not None
            else None
        )
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
        pending_human_input = (
            self._output_adapter.resolve_human_input(chat_id, text)
            if self._output_adapter is not None
            else None
        )
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
                "supports_markdown": False,
                "progress_notice_policy": "prefer_before_nontrivial_final",
                "tool_scope": "basic",
                "allowed_tool_bundle": list(EXTERNAL_ENDPOINT_BASIC_TOOL_BUNDLE),
                "allowed_mcp_servers": [],
                "message_id": message.get("message_id", ""),
                "chat_id": chat_id,
                "chat_type": message.get("chat_type", ""),
            },
            preferred_mode=_infer_preferred_mode(text),
        )

    async def run(self):
        await self._get_provider_gateway_client()
        await self._client.start()

    async def close(self):
        for client in self._gateway_clients.values():
            await client.close()
        self._gateway_clients.clear()
        if self._provider_gateway_client is not None:
            await self._provider_gateway_client.close()
            self._provider_gateway_client = None
        await self._client.stop()

