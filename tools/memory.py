from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, TypedDict
from uuid import uuid4

try:
    import aiohttp
except ImportError:
    aiohttp = None
import numpy as np

from core.runtime_context import get_event_context
from core.repositories import MemoryRepository
from tools.memory_layers import MemoryConsolidatorLayer, MemoryRetrieverLayer, MemoryStoreLayer, MemoryViewLayer, dt_to_iso, utcnow

logger = logging.getLogger("meetyou.memory")

SPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
EXPLICIT_REMEMBER_TAG = "remember_knowledge"
REMEMBER_CATEGORY_TAG_PREFIX = "remember_category:"


class _FallbackClientSession:
    async def close(self):
        return None


class MemoryScope(TypedDict):
    user_id: str
    session_id: str


class MemoryRecord(TypedDict, total=False):
    id: str
    type: str
    scope: MemoryScope
    content: str
    canonical_text: str
    embedding: list[float]
    embedding_model: str
    strength: float
    importance: float
    confidence: float
    created_at: str
    last_accessed_at: str
    last_updated_at: str
    access_count: int
    status: str
    tags: list[str]
    entity_keys: list[str]
    source_record_ids: list[str]
    fact_key: str
    fact_value: str
    workspace_tags: list[str]
    origin_workspace_id: str


class MemoryEdge(TypedDict, total=False):
    from_id: str
    to_id: str
    semantic_sim: float
    same_entity: bool
    same_project: bool
    derived_from: bool
    contradicts: bool
    updated_at: str


class Memory(MemoryRepository):
    def __init__(self):
        self._memory_file_path = "memory.json"
        self._embedding_model = ""
        self._embedding_api_key = ""
        self._embedding_api_url = ""
        self._http_session: aiohttp.ClientSession | None = None
        self._housekeeping_adapter = None
        self._store: dict[str, Any] = {}
        self._store_backend = None
        self._store_layer = MemoryStoreLayer(self)
        self._view_layer = MemoryViewLayer(self)
        self._retriever_layer = MemoryRetrieverLayer(self)
        self._consolidator_layer = MemoryConsolidatorLayer(self)
        self._store = self._store_layer.empty_store()
        self._db_sync_callback = None

    def _tokens(self, text: str) -> list[str]:
        return TOKEN_RE.findall(str(text or ""))

    def _canonicalize(self, text: str) -> str:
        return SPACE_RE.sub(" ", str(text or "").strip()).lower()

    def _clamp(self, value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def _make_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:16]}"

    async def init_memory(self, config):
        self._memory_file_path = config.get("memory_file_path") or self._memory_file_path
        self.refresh_config(config)
        self._http_session = aiohttp.ClientSession() if aiohttp is not None else _FallbackClientSession()
        self._store = self._store_layer.empty_store()
        if os.path.exists(self._memory_file_path):
            try:
                self._store = self._store_layer.load_store()
            except Exception as exc:
                logger.warning("加载记忆文件失败，使用空记忆初始化: %s", exc)
        logger.info("记忆系统初始化完成: %s 条记录", len(self._store["records"]))

    def refresh_config(self, config):
        self._embedding_model = config.get("embedding_model") or ""
        self._embedding_api_key = config.get("embedding_api_key") or ""
        self._embedding_api_url = config.get("embedding_api_url") or ""
        self._store_layer.ensure_repository_metadata()
        self._store["metadata"]["embedding_model"] = self._embedding_model
        self._store["metadata"]["embedding_api_url"] = self._embedding_api_url
        self._store["metadata"]["updated_at"] = dt_to_iso(utcnow())

    def set_housekeeping_adapter(self, adapter):
        self._housekeeping_adapter = adapter

    async def close_memory(self):
        if self._http_session is not None:
            await self._http_session.close()
            self._http_session = None

    async def _get_embedding(self, text: str) -> list[float]:
        if not text or self._http_session is None:
            return []
        if not self._embedding_api_url or not self._embedding_model:
            return []
        headers = {
            "Authorization": f"Bearer {self._embedding_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self._embedding_model, "input": text}
        try:
            async with self._http_session.post(self._embedding_api_url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception as exc:
            logger.error("获取 embedding 失败: %s", exc)
            return []
        embedding = data.get("embedding")
        if isinstance(embedding, list):
            return embedding
        items = data.get("data", [])
        if isinstance(items, list) and items:
            first = items[0] if isinstance(items[0], dict) else {}
            embedding = first.get("embedding")
            if isinstance(embedding, list):
                return embedding
        return []

    @staticmethod
    def _calc_cosine(vec1: list[float] | np.ndarray, vec2: list[float] | np.ndarray) -> float:
        arr1 = np.array(vec1, dtype=np.float32)
        arr2 = np.array(vec2, dtype=np.float32)
        n1 = np.linalg.norm(arr1)
        n2 = np.linalg.norm(arr2)
        if n1 == 0 or n2 == 0:
            return 0.0
        return float(np.dot(arr1, arr2) / (n1 * n2))

    def _resolve_user_id(self, source) -> str:
        if source is None:
            return "global"
        kind = getattr(source, "kind", "") or (source.get("kind") if isinstance(source, dict) else "")
        source_id = getattr(source, "id", "") or (source.get("id") if isinstance(source, dict) else "")
        if kind in {"system", "heart"}:
            return "global"
        return str(source_id).strip() or "global"

    def _record_scope(self, user_id: str, session_id: str, record_type: str) -> MemoryScope:
        return {"user_id": user_id, "session_id": session_id if record_type == "episode" else ""}

    @staticmethod
    def _normalize_workspace_id(value: Any) -> str:
        return str(value or "").strip()

    def _normalize_workspace_tags(self, values: list[Any] | tuple[Any, ...] | None) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            workspace_id = self._normalize_workspace_id(value)
            if not workspace_id or workspace_id in seen:
                continue
            seen.add(workspace_id)
            normalized.append(workspace_id)
        return normalized

    def _current_workspace_id(self) -> str:
        return self._normalize_workspace_id(get_event_context().get("workspace_id"))

    def _enrich_record_workspace_scope(self, record: MemoryRecord) -> MemoryRecord:
        inferred_tags: list[str] = []
        existing_tags = record.get("workspace_tags")
        if isinstance(existing_tags, list):
            inferred_tags.extend(existing_tags)
        existing_workspace_ids = record.get("workspace_ids")
        if isinstance(existing_workspace_ids, list):
            inferred_tags.extend(existing_workspace_ids)
        origin_workspace_id = self._normalize_workspace_id(record.get("origin_workspace_id"))
        if origin_workspace_id:
            inferred_tags.append(origin_workspace_id)
        active_workspace_id = self._current_workspace_id()
        if active_workspace_id:
            inferred_tags.append(active_workspace_id)
            if not origin_workspace_id:
                origin_workspace_id = active_workspace_id
        record["workspace_tags"] = self._normalize_workspace_tags(inferred_tags)
        if origin_workspace_id:
            record["origin_workspace_id"] = origin_workspace_id
        elif record.get("origin_workspace_id"):
            record["origin_workspace_id"] = self._normalize_workspace_id(record.get("origin_workspace_id"))
        return record

    async def save_memory_graph(self):
        await self._store_layer.save()
        if self._db_sync_callback is not None:
            await self._db_sync_callback()

    def set_store_backend(self, backend, *, migrate_current: bool = False) -> None:
        self._store_backend = backend
        if not migrate_current:
            self._store = self._store_layer.load_store()
            return
        loaded = self._store_backend.load()
        if isinstance(loaded, dict) and (loaded.get("records") or loaded.get("edges")):
            self._store = self._store_layer.normalize_loaded_store(loaded)
            return
        self._store_backend.save(self._store)

    def set_db_sync_callback(self, callback) -> None:
        self._db_sync_callback = callback

    def _remember_category(self, record: MemoryRecord) -> str:
        for tag in record.get("tags", []):
            text = str(tag or "").strip()
            if text.startswith(REMEMBER_CATEGORY_TAG_PREFIX):
                return text[len(REMEMBER_CATEGORY_TAG_PREFIX):].strip().lower()
        return ""

    def _is_explicit_memory(self, record: MemoryRecord) -> bool:
        return EXPLICIT_REMEMBER_TAG in record.get("tags", [])

    def _summary_store(self) -> dict[str, Any]:
        layer = self._store.get("conversation_summaries")
        if not isinstance(layer, dict):
            layer = self._store.get("working_summaries")
        if not isinstance(layer, dict):
            layer = {"global": "", "by_session": {}}
        layer["global"] = str(layer.get("global", "") or "")
        by_session = layer.get("by_session")
        layer["by_session"] = by_session if isinstance(by_session, dict) else {}
        self._store["working_summaries"] = layer
        self._store["conversation_summaries"] = layer
        return layer

    async def _apply_strong_consistent_memory_write(self, user_id: str, record: MemoryRecord) -> bool:
        if not self._is_explicit_memory(record):
            return False
        return await self._consolidator_layer.apply_explicit_memory_record(user_id, record)

    async def save_memory(
        self,
        memory_text: str,
        text_emotion_intensity: float = 1.0,
        session_id: str = "",
        source=None,
        tags: list[str] | None = None,
    ) -> str:
        content = str(memory_text or "").strip()
        if not content:
            return "记忆内容为空"

        from tools.memory_layers import IDEMPOTENCY_WINDOW, iso_to_dt

        now = utcnow()
        user_id = self._resolve_user_id(source)
        canonical_text = self._canonicalize(content)
        existing = None
        for record in reversed(self._store["records"]):
            if record.get("type") != "episode":
                continue
            if record.get("scope", {}).get("user_id") != user_id:
                continue
            if record.get("scope", {}).get("session_id") != session_id:
                continue
            if record.get("canonical_text") != canonical_text:
                continue
            if now - iso_to_dt(record.get("last_updated_at")) <= IDEMPOTENCY_WINDOW:
                existing = record
                break
        if existing is not None:
            existing["last_updated_at"] = dt_to_iso(now)
            existing["strength"] = min(1.0, float(existing.get("strength", 0.4) or 0.4) + 0.04)
            existing_tags = existing.setdefault("tags", [])
            if "pending_consolidation" not in existing_tags:
                existing_tags.append("pending_consolidation")
            for tag in tags or []:
                tag_text = str(tag or "").strip()
                if tag_text and tag_text not in existing_tags:
                    existing_tags.append(tag_text)
            self._enrich_record_workspace_scope(existing)
            if await self._apply_strong_consistent_memory_write(user_id, existing):
                existing_tags = [tag for tag in existing_tags if tag != "pending_consolidation"]
                existing["tags"] = existing_tags
            await self.save_memory_graph()
            return f"记忆已更新, id={existing['id']}"

        embedding = await self._get_embedding(content)
        if not embedding:
            return "获取内容向量失败"

        emotion = self._clamp(float(text_emotion_intensity), 0.0, 1.0)
        record_tags = ["pending_consolidation"]
        for tag in tags or []:
            tag_text = str(tag or "").strip()
            if tag_text and tag_text not in record_tags:
                record_tags.append(tag_text)
        record: MemoryRecord = {
            "id": self._make_id("ep"),
            "type": "episode",
            "scope": self._record_scope(user_id, session_id, "episode"),
            "content": content,
            "canonical_text": canonical_text,
            "embedding": embedding,
            "embedding_model": self._embedding_model,
            "strength": self._clamp(0.35 + 0.35 * emotion, 0.2, 1.0),
            "importance": self._clamp(0.4 + 0.5 * emotion, 0.1, 1.0),
            "confidence": 0.6,
            "created_at": dt_to_iso(now),
            "last_accessed_at": dt_to_iso(now),
            "last_updated_at": dt_to_iso(now),
            "access_count": 0,
            "status": "active",
            "tags": record_tags,
            "entity_keys": [],
            "source_record_ids": [],
        }
        self._enrich_record_workspace_scope(record)
        self._store["records"].append(record)
        self._store_layer.link_semantic_edges(record)
        if await self._apply_strong_consistent_memory_write(user_id, record):
            record["tags"] = [tag for tag in record.get("tags", []) if tag != "pending_consolidation"]
        await self.save_memory_graph()
        return f"成功保存记忆, id={record['id']}"

    async def update_working_summary(self, context: str, session_id: str = "") -> str:
        text = str(context or "").strip()
        working = self._summary_store()
        if session_id:
            if text:
                working["by_session"][session_id] = text
            else:
                working["by_session"].pop(session_id, None)
        else:
            working["global"] = text
        await self.save_memory_graph()
        return "成功更新上下文"

    async def load_working_summary(self, session_id: str = "") -> str:
        working = self._summary_store()
        if session_id:
            text = working.get("by_session", {}).get(session_id, "").strip()
            if text:
                return text
        text = str(working.get("global", "")).strip()
        return text or "当前没有暂存的上下文信息。"

    async def clear_all(self) -> dict[str, Any]:
        working = self._summary_store()
        by_session = working.get("by_session", {}) if isinstance(working.get("by_session"), dict) else {}
        cleared_record_count = len(list(self._store.get("records", [])))
        cleared_edge_count = len(list(self._store.get("edges", [])))
        cleared_session_summary_count = sum(1 for value in by_session.values() if str(value or "").strip())
        cleared_global_summary = bool(str(working.get("global", "") or "").strip())

        self._store = self._store_layer.empty_store()
        self._store["metadata"]["embedding_model"] = self._embedding_model
        self._store["metadata"]["embedding_api_url"] = self._embedding_api_url
        await self.save_memory_graph()
        return {
            "cleared_record_count": cleared_record_count,
            "cleared_edge_count": cleared_edge_count,
            "cleared_session_summary_count": cleared_session_summary_count,
            "cleared_global_summary": cleared_global_summary,
        }

    def _project_memory_record_by_id(self, memory_id: str) -> dict[str, Any] | None:
        target_id = str(memory_id or "").strip()
        if not target_id:
            return None
        snapshot = self.get_memory_snapshot(include_invalidated=True)
        for record in snapshot.get("records", []):
            if str(record.get("id") or "") == target_id:
                return dict(record)
        return None

    async def update_record_status(self, memory_id: str, status: str) -> dict[str, Any]:
        target_id = str(memory_id or "").strip()
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in {"active", "invalidated"}:
            raise ValueError("memory_status_invalid")
        if not target_id:
            raise ValueError("memory_id_required")

        from tools.memory_layers import dt_to_iso, utcnow

        updated_at = dt_to_iso(utcnow())
        for record in self._store.get("records", []):
            if str(record.get("id") or "") != target_id:
                continue
            record["status"] = normalized_status
            record["last_updated_at"] = updated_at
            await self.save_memory_graph()
            return {
                "ok": True,
                "memory_id": target_id,
                "status": normalized_status,
                "deleted": False,
                "updated_at": updated_at,
                "record": self._project_memory_record_by_id(target_id),
            }
        raise KeyError(target_id)

    async def delete_record(self, memory_id: str) -> dict[str, Any]:
        target_id = str(memory_id or "").strip()
        if not target_id:
            raise ValueError("memory_id_required")

        from tools.memory_layers import dt_to_iso, utcnow

        if self._project_memory_record_by_id(target_id) is None:
            raise KeyError(target_id)
        changed = self._store_layer.delete_records({target_id})
        if not changed:
            raise KeyError(target_id)
        updated_at = dt_to_iso(utcnow())
        await self.save_memory_graph()
        return {
            "ok": True,
            "memory_id": target_id,
            "status": "deleted",
            "deleted": True,
            "updated_at": updated_at,
            "record": None,
        }

    def get_memory_snapshot(
        self,
        source_id: str = "",
        session_id: str = "",
        include_invalidated: bool = False,
    ) -> dict[str, Any]:
        return self._view_layer.get_memory_snapshot(
            source_id=source_id,
            session_id=session_id,
            include_invalidated=include_invalidated,
        )

    def get_memory_graph_view(
        self,
        source_id: str = "",
        session_id: str = "",
        include_invalidated: bool = False,
    ) -> dict[str, Any]:
        return self._view_layer.get_memory_graph_view(
            source_id=source_id,
            session_id=session_id,
            include_invalidated=include_invalidated,
        )

    async def search_records(self, query_text: str, session_id: str = "", source=None) -> list[dict[str, Any]]:
        return await self._retriever_layer.search_records(query_text, session_id=session_id, source=source)

    def _format_profile_entry(self, entry: dict[str, Any]) -> str:
        key = str(entry.get("fact_key") or "").strip()
        value = str(entry.get("fact_value") or "").strip()
        suffix = self._format_source_suffix(entry)
        if key and value:
            return f"- {key}: {value}{suffix}"
        return f"- {str(entry.get('content') or '').strip()}{suffix}"

    def _format_fact_entry(self, entry: dict[str, Any]) -> str:
        key = str(entry.get("fact_key") or "").strip()
        value = str(entry.get("fact_value") or "").strip()
        suffix = self._format_source_suffix(entry)
        if key and value:
            return f"- {key}: {value}{suffix}"
        return f"- {str(entry.get('content') or '').strip()}{suffix}"

    def _format_event_entry(self, entry: dict[str, Any]) -> str:
        return f"- {str(entry.get('content') or '').strip()}{self._format_source_suffix(entry)}"

    @staticmethod
    def _format_source_suffix(entry: dict[str, Any]) -> str:
        source_label = str(entry.get("source_label") or "").strip()
        return f" [来源: {source_label}]" if source_label else ""

    async def recall_memory(self, query_text: str, session_id: str = "", source=None, reinforce: bool = True) -> str:
        payload = await self._retriever_layer.build_recall_payload(
            query_text,
            session_id=session_id,
            source=source,
            reinforce=reinforce,
        )
        if not any(payload[key] for key in ("profile", "facts", "recent_events")):
            return "未找到相关记忆"

        sections = []
        if payload["profile"]:
            sections.append("[用户画像]\n" + "\n".join(self._format_profile_entry(item) for item in payload["profile"]))
        if payload["facts"]:
            sections.append("[长期事实]\n" + "\n".join(self._format_fact_entry(item) for item in payload["facts"]))
        if payload["recent_events"]:
            sections.append("[最近事件]\n" + "\n".join(self._format_event_entry(item) for item in payload["recent_events"]))
        return "\n\n".join(sections) if sections else "未找到相关记忆"

    async def recall_memory_structured(
        self,
        query_text: str,
        session_id: str = "",
        source=None,
        reinforce: bool = True,
    ) -> str:
        payload = await self._retriever_layer.build_recall_payload(
            query_text,
            session_id=session_id,
            source=source,
            reinforce=reinforce,
        )
        return json.dumps(payload, ensure_ascii=False)

    async def _apply_profile_upsert(self, user_id: str, payload: dict[str, Any]) -> bool:
        return await self._consolidator_layer.apply_profile_upsert(user_id, payload)

    async def _apply_fact_upsert(self, user_id: str, payload: dict[str, Any]) -> bool:
        return await self._consolidator_layer.apply_fact_upsert(user_id, payload)

    async def consolidate_pending_records(self, session, api_url: str, api_key: str, model: str) -> bool:
        return await self._consolidator_layer.consolidate_pending_records(session, api_url, api_key, model)

    async def run_housekeeping(self, session, api_url: str, api_key: str, model: str) -> None:
        changed = self._store_layer.prune_records()
        changed = await self.consolidate_pending_records(session, api_url, api_key, model) or changed
        if changed:
            await self.save_memory_graph()
