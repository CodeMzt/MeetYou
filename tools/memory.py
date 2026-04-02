"""
长期记忆与工作摘要管理。
"""

from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict
from uuid import uuid4

import aiohttp
import numpy as np

logger = logging.getLogger("meetyou.memory")

IDEMPOTENCY_WINDOW = timedelta(minutes=30)
PENDING_TRIGGER_COUNT = 5
PENDING_TRIGGER_AGE = timedelta(minutes=10)
PENDING_BATCH_SIZE = 20
SEARCH_TOP_K = 12
ANCHOR_TOP_K = 4
ANCHOR_MIN_SIM = 0.45
EDGE_SIM_THRESHOLD = 0.75
MERGE_SIM_THRESHOLD = 0.92
CONFLICT_CONFIDENCE_THRESHOLD = 0.70
INVALIDATED_RETENTION_DAYS = 30
MIN_EFFECTIVE_STRENGTH = 0.05

HALF_LIFE_DAYS = {"profile_fact": 180.0, "episode": 14.0}

SPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

EXPLICIT_REMEMBER_TAG = "remember_knowledge"
REMEMBER_CATEGORY_TAG_PREFIX = "remember_category:"
NON_TASK_REMEMBER_CATEGORIES = {"profile", "preference", "relationship"}
TASKLIKE_REMEMBER_CATEGORIES = {"project", "commitment"}


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
    task_key: str
    project: str
    task_status: str
    deadline: str | None


class MemoryEdge(TypedDict, total=False):
    from_id: str
    to_id: str
    semantic_sim: float
    same_entity: bool
    same_project: bool
    derived_from: bool
    contradicts: bool
    updated_at: str


class ConsolidationPatch(TypedDict, total=False):
    profile_upserts: list[dict[str, Any]]
    task_upserts: list[dict[str, Any]]
    links: list[dict[str, Any]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso_to_dt(value: str | None) -> datetime:
    if not value:
        return _utcnow()
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return _utcnow()


def _canonicalize(text: str) -> str:
    return SPACE_RE.sub(" ", str(text or "").strip()).lower()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class Memory:
    def __init__(self):
        self._memory_file_path = "memory.json"
        self._embedding_model = ""
        self._embedding_api_key = ""
        self._embedding_api_url = ""
        self._http_session: aiohttp.ClientSession | None = None
        self._housekeeping_adapter = None
        self._store = self._empty_store()

    def _empty_store(self) -> dict[str, Any]:
        now = _dt_to_iso(_utcnow())
        return {
            "metadata": {
                "embedding_model": "",
                "embedding_api_url": "",
                "updated_at": now,
            },
            "records": [],
            "edges": [],
            "working_summaries": {"global": "", "by_session": {}},
        }

    async def init_memory(self, config):
        self._memory_file_path = config.get("memory_file_path") or self._memory_file_path
        self.refresh_config(config)
        self._http_session = aiohttp.ClientSession()
        self._store = self._empty_store()
        if os.path.exists(self._memory_file_path):
            try:
                with open(self._memory_file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    data = json.loads(content)
                    if self._is_valid_store(data):
                        self._store = data
                        self._normalize_store()
                    else:
                        logger.warning("记忆文件格式无效，使用空记忆初始化")
            except Exception as e:
                logger.warning("加载记忆文件失败，使用空记忆初始化: %s", e)
        logger.info("记忆系统初始化完成: %s 条记录", len(self._store["records"]))

    def refresh_config(self, config):
        self._embedding_model = config.get("embedding_model") or ""
        self._embedding_api_key = config.get("embedding_api_key") or ""
        self._embedding_api_url = config.get("embedding_api_url") or ""
        self._store.setdefault("metadata", {})
        self._store["metadata"]["embedding_model"] = self._embedding_model
        self._store["metadata"]["embedding_api_url"] = self._embedding_api_url
        self._store["metadata"]["updated_at"] = _dt_to_iso(_utcnow())

    def set_housekeeping_adapter(self, adapter):
        self._housekeeping_adapter = adapter

    async def close_memory(self):
        if self._http_session:
            await self._http_session.close()
            self._http_session = None

    def _is_valid_store(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        if not isinstance(data.get("metadata"), dict):
            return False
        if not isinstance(data.get("records"), list):
            return False
        if not isinstance(data.get("edges"), list):
            return False
        summaries = data.get("working_summaries")
        if not isinstance(summaries, dict):
            return False
        if not isinstance(summaries.get("global", ""), str):
            return False
        return isinstance(summaries.get("by_session", {}), dict)

    def _normalize_store(self):
        metadata = self._store.setdefault("metadata", {})
        metadata["embedding_model"] = metadata.get("embedding_model") or self._embedding_model
        metadata["embedding_api_url"] = metadata.get("embedding_api_url") or self._embedding_api_url
        metadata["updated_at"] = metadata.get("updated_at") or _dt_to_iso(_utcnow())
        working = self._store.setdefault("working_summaries", {})
        working["global"] = working.get("global") or ""
        by_session = working.get("by_session")
        working["by_session"] = by_session if isinstance(by_session, dict) else {}
        for record in self._store.get("records", []):
            record.setdefault("tags", [])
            record.setdefault("entity_keys", [])
            record.setdefault("source_record_ids", [])
            record.setdefault("status", "active")
            record.setdefault("access_count", 0)

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
        except Exception as e:
            logger.error("获取 embedding 失败: %s", e)
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

    def _touch_updated(self):
        self._store["metadata"]["updated_at"] = _dt_to_iso(_utcnow())

    async def save_memory_graph(self):
        self._touch_updated()
        with open(self._memory_file_path, "w", encoding="utf-8") as f:
            json.dump(self._store, f, ensure_ascii=False, indent=2)

    def _record_by_id(self, record_id: str) -> MemoryRecord | None:
        for record in self._store["records"]:
            if record.get("id") == record_id:
                return record
        return None

    def _edge_endpoints(self, left: str, right: str) -> tuple[str, str]:
        return tuple(sorted((left, right)))

    def _edge_by_pair(self, left: str, right: str) -> MemoryEdge | None:
        a, b = self._edge_endpoints(left, right)
        for edge in self._store["edges"]:
            if edge.get("from_id") == a and edge.get("to_id") == b:
                return edge
        return None

    def _upsert_edge(
        self,
        left: str,
        right: str,
        *,
        semantic_sim: float = 0.0,
        same_entity: bool = False,
        same_project: bool = False,
        derived_from: bool = False,
        contradicts: bool = False,
    ):
        if left == right:
            return False
        a, b = self._edge_endpoints(left, right)
        edge = self._edge_by_pair(a, b)
        now = _dt_to_iso(_utcnow())
        if edge is None:
            self._store["edges"].append({
                "from_id": a,
                "to_id": b,
                "semantic_sim": float(semantic_sim),
                "same_entity": bool(same_entity),
                "same_project": bool(same_project),
                "derived_from": bool(derived_from),
                "contradicts": bool(contradicts),
                "updated_at": now,
            })
            return True
        before = (
            float(edge.get("semantic_sim", 0.0)),
            bool(edge.get("same_entity")),
            bool(edge.get("same_project")),
            bool(edge.get("derived_from")),
            bool(edge.get("contradicts")),
        )
        edge["semantic_sim"] = max(float(edge.get("semantic_sim", 0.0)), float(semantic_sim))
        edge["same_entity"] = bool(edge.get("same_entity")) or bool(same_entity)
        edge["same_project"] = bool(edge.get("same_project")) or bool(same_project)
        edge["derived_from"] = bool(edge.get("derived_from")) or bool(derived_from)
        edge["contradicts"] = bool(edge.get("contradicts")) or bool(contradicts)
        edge["updated_at"] = now
        after = (
            float(edge.get("semantic_sim", 0.0)),
            bool(edge.get("same_entity")),
            bool(edge.get("same_project")),
            bool(edge.get("derived_from")),
            bool(edge.get("contradicts")),
        )
        return after != before

    def _semantic_edge_candidates(self, record: MemoryRecord) -> list[MemoryRecord]:
        results = []
        for other in self._store["records"]:
            if other.get("id") == record.get("id"):
                continue
            if other.get("status") != "active":
                continue
            if other.get("embedding_model") != record.get("embedding_model"):
                continue
            if not other.get("embedding"):
                continue
            if other.get("scope", {}).get("user_id") not in {record.get("scope", {}).get("user_id"), "global"}:
                continue
            results.append(other)
        return results

    def _link_semantic_edges(self, record: MemoryRecord):
        if not record.get("embedding"):
            return
        for other in self._semantic_edge_candidates(record):
            sim = self._calc_cosine(record["embedding"], other["embedding"])
            if sim >= EDGE_SIM_THRESHOLD:
                self._upsert_edge(record["id"], other["id"], semantic_sim=sim)

    def _episode_pending(self, record: MemoryRecord) -> bool:
        return record.get("type") == "episode" and "pending_consolidation" in record.get("tags", [])

    def _remember_category(self, record: MemoryRecord) -> str:
        for tag in record.get("tags", []):
            text = str(tag or "").strip()
            if text.startswith(REMEMBER_CATEGORY_TAG_PREFIX):
                return text[len(REMEMBER_CATEGORY_TAG_PREFIX):].strip().lower()
        return ""

    def _is_explicit_memory(self, record: MemoryRecord) -> bool:
        return EXPLICIT_REMEMBER_TAG in record.get("tags", [])

    def _source_remember_categories(self, records: list[MemoryRecord]) -> set[str]:
        categories: set[str] = set()
        for record in records:
            category = self._remember_category(record)
            if category:
                categories.add(category)
        return categories

    def _looks_like_actionable_task(self, summary: str) -> bool:
        text = str(summary or "").strip().lower()
        if not text:
            return False
        patterns = (
            "todo",
            "fix",
            "finish",
            "ship",
            "deadline",
            "blocker",
            "bug",
            "project",
            "task",
            "remind",
            "负责",
            "项目",
            "任务",
            "修复",
            "提醒",
            "截止",
            "阻塞",
            "上线",
            "推进",
        )
        return any(token in text for token in patterns)

    def _find_recent_episode(self, user_id: str, session_id: str, canonical_text: str, now: datetime) -> MemoryRecord | None:
        for record in reversed(self._store["records"]):
            if record.get("type") != "episode":
                continue
            if record.get("scope", {}).get("user_id") != user_id:
                continue
            if record.get("scope", {}).get("session_id") != session_id:
                continue
            if record.get("canonical_text") != canonical_text:
                continue
            if now - _iso_to_dt(record.get("last_updated_at")) <= IDEMPOTENCY_WINDOW:
                return record
        return None

    def _lexical_score(self, query_text: str, record: MemoryRecord) -> float:
        query = _canonicalize(query_text)
        haystack = _canonicalize(record.get("content", ""))
        if not query or not haystack:
            return 0.0
        if query in haystack:
            return 1.0
        query_tokens = TOKEN_RE.findall(query)
        record_tokens = set(TOKEN_RE.findall(haystack))
        if not query_tokens or not record_tokens:
            return 0.0
        overlap = sum(1 for token in query_tokens if token in record_tokens)
        return overlap / max(len(query_tokens), 1)

    def _half_life_days(self, record: MemoryRecord) -> float:
        if record.get("type") == "task":
            return 7.0 if record.get("task_status") == "done" else 30.0
        return HALF_LIFE_DAYS.get(record.get("type", ""), 14.0)

    def _age_days(self, record: MemoryRecord, now: datetime) -> float:
        return max((now - _iso_to_dt(record.get("created_at"))).total_seconds() / 86400.0, 0.0)

    def _recency_score(self, record: MemoryRecord, now: datetime) -> float:
        return 0.5 ** (self._age_days(record, now) / self._half_life_days(record))

    def _effective_strength(self, record: MemoryRecord, now: datetime) -> float:
        return float(record.get("strength", 0.0)) * self._recency_score(record, now)

    def _eligible_records(self, user_id: str) -> list[MemoryRecord]:
        current_model = self._embedding_model
        results = []
        for record in self._store["records"]:
            if record.get("type") not in {"profile_fact", "task", "episode"}:
                continue
            if record.get("status") != "active":
                continue
            if record.get("scope", {}).get("user_id") not in {user_id, "global"}:
                continue
            if record.get("embedding_model") != current_model:
                continue
            results.append(record)
        return results

    def _graph_neighbors(self, record_id: str) -> list[str]:
        neighbors: list[str] = []
        for edge in self._store["edges"]:
            if edge.get("contradicts"):
                continue
            sim_ok = float(edge.get("semantic_sim", 0.0)) >= EDGE_SIM_THRESHOLD
            relation_ok = bool(edge.get("same_entity")) or bool(edge.get("same_project"))
            if not sim_ok and not relation_ok:
                continue
            if edge.get("from_id") == record_id:
                neighbors.append(str(edge.get("to_id")))
            elif edge.get("to_id") == record_id:
                neighbors.append(str(edge.get("from_id")))
        return neighbors

    def _graph_score(self, record_id: str, anchor_ids: set[str]) -> float:
        if record_id in anchor_ids:
            return 1.0
        best = 0.0
        for anchor_id in anchor_ids:
            edge = self._edge_by_pair(record_id, anchor_id)
            if edge is None or edge.get("contradicts"):
                continue
            score = float(edge.get("semantic_sim", 0.0))
            if edge.get("derived_from"):
                score = max(score, 0.7)
            if edge.get("same_project"):
                score = max(score, 0.9)
            if edge.get("same_entity"):
                score = max(score, 1.0)
            best = max(best, score)
        return best

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

        now = _utcnow()
        user_id = self._resolve_user_id(source)
        canonical_text = _canonicalize(content)
        existing = self._find_recent_episode(user_id, session_id, canonical_text, now)
        if existing is not None:
            existing["last_updated_at"] = _dt_to_iso(now)
            existing["strength"] = min(1.0, float(existing.get("strength", 0.4)) + 0.04)
            existing_tags = existing.setdefault("tags", [])
            if "pending_consolidation" not in existing_tags:
                existing_tags.append("pending_consolidation")
            for tag in tags or []:
                tag_text = str(tag or "").strip()
                if tag_text and tag_text not in existing_tags:
                    existing_tags.append(tag_text)
            await self.save_memory_graph()
            return f"记忆已更新, id={existing['id']}"

        embedding = await self._get_embedding(content)
        if not embedding:
            return "获取内容向量失败"

        emotion = _clamp(float(text_emotion_intensity), 0.0, 1.0)
        record_tags = ["pending_consolidation"]
        for tag in tags or []:
            tag_text = str(tag or "").strip()
            if tag_text and tag_text not in record_tags:
                record_tags.append(tag_text)
        record: MemoryRecord = {
            "id": _make_id("ep"),
            "type": "episode",
            "scope": self._record_scope(user_id, session_id, "episode"),
            "content": content,
            "canonical_text": canonical_text,
            "embedding": embedding,
            "embedding_model": self._embedding_model,
            "strength": _clamp(0.35 + 0.35 * emotion, 0.2, 1.0),
            "importance": _clamp(0.4 + 0.5 * emotion, 0.1, 1.0),
            "confidence": 0.6,
            "created_at": _dt_to_iso(now),
            "last_accessed_at": _dt_to_iso(now),
            "last_updated_at": _dt_to_iso(now),
            "access_count": 0,
            "status": "active",
            "tags": record_tags,
            "entity_keys": [],
            "source_record_ids": [],
        }
        self._store["records"].append(record)
        self._link_semantic_edges(record)
        await self.save_memory_graph()
        return f"成功保存记忆, id={record['id']}"

    async def update_working_summary(self, context: str, session_id: str = "") -> str:
        text = str(context or "").strip()
        working = self._store["working_summaries"]
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
        working = self._store["working_summaries"]
        if session_id:
            text = working.get("by_session", {}).get(session_id, "").strip()
            if text:
                return text
        text = str(working.get("global", "")).strip()
        return text or "当前没有暂存的上下文信息。"

    def _viewable_records(self, source_id: str = "", include_invalidated: bool = False) -> list[MemoryRecord]:
        requested_user_id = str(source_id or "").strip()
        allowed_status = {"active", "invalidated"} if include_invalidated else {"active"}
        records: list[MemoryRecord] = []
        for record in self._store["records"]:
            if record.get("type") not in {"profile_fact", "task", "episode"}:
                continue
            if record.get("status") not in allowed_status:
                continue
            if requested_user_id and record.get("scope", {}).get("user_id") not in {requested_user_id, "global"}:
                continue
            records.append(deepcopy(record))
        return records

    def _viewable_edges(self, record_ids: set[str]) -> list[MemoryEdge]:
        edges: list[MemoryEdge] = []
        for edge in self._store["edges"]:
            if edge.get("from_id") in record_ids and edge.get("to_id") in record_ids:
                edges.append(deepcopy(edge))
        return edges

    def _working_summary_view(self, session_id: str = "") -> dict[str, str]:
        working = self._store.get("working_summaries", {})
        by_session = working.get("by_session", {})
        session_summary = ""
        if session_id and isinstance(by_session, dict):
            session_summary = str(by_session.get(session_id, "") or "")
        return {
            "global_summary": str(working.get("global", "") or ""),
            "session_summary": session_summary,
            "session_id": str(session_id or ""),
        }

    def _memory_stats(self, records: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
        by_type = {"profile_fact": 0, "task": 0, "episode": 0}
        for record in records:
            record_type = str(record.get("type") or "")
            if record_type in by_type:
                by_type[record_type] += 1
        return {
            "record_count": len(records),
            "edge_count": len(edges),
            "by_type": by_type,
        }

    def get_memory_snapshot(
        self,
        source_id: str = "",
        session_id: str = "",
        include_invalidated: bool = False,
    ) -> dict[str, Any]:
        records = self._viewable_records(source_id=source_id, include_invalidated=include_invalidated)
        record_ids = {str(record.get("id")) for record in records}
        edges = self._viewable_edges(record_ids)
        return {
            "metadata": deepcopy(self._store.get("metadata", {})),
            "scope": {
                "source_id": str(source_id or ""),
                "session_id": str(session_id or ""),
            },
            "working_summaries": self._working_summary_view(session_id),
            "records": records,
            "edges": edges,
            "stats": self._memory_stats(records, edges),
        }

    def _graph_label(self, record: MemoryRecord) -> str:
        if record.get("type") == "profile_fact":
            value = str(record.get("fact_value") or "").strip()
            key = str(record.get("fact_key") or "").strip()
            text = value or key or str(record.get("content") or "").strip()
        else:
            text = str(record.get("content") or "").strip()
        return text[:18] + "..." if len(text) > 18 else text

    def _graph_node(self, record: MemoryRecord) -> dict[str, Any]:
        return {
            "id": str(record.get("id") or ""),
            "type": str(record.get("type") or ""),
            "label": self._graph_label(record),
            "content": str(record.get("content") or ""),
            "status": str(record.get("status") or "active"),
            "scope": deepcopy(record.get("scope", {})),
            "strength": float(record.get("strength", 0.0) or 0.0),
            "importance": float(record.get("importance", 0.0) or 0.0),
            "confidence": float(record.get("confidence", 0.0) or 0.0),
            "created_at": str(record.get("created_at") or ""),
            "last_accessed_at": str(record.get("last_accessed_at") or ""),
            "last_updated_at": str(record.get("last_updated_at") or ""),
            "access_count": int(record.get("access_count", 0) or 0),
            "tags": list(record.get("tags", [])),
            "entity_keys": list(record.get("entity_keys", [])),
            "source_record_ids": list(record.get("source_record_ids", [])),
            "fact_key": record.get("fact_key"),
            "fact_value": record.get("fact_value"),
            "task_key": record.get("task_key"),
            "project": record.get("project"),
            "task_status": record.get("task_status"),
            "deadline": record.get("deadline"),
        }

    def get_memory_graph_view(
        self,
        source_id: str = "",
        session_id: str = "",
        include_invalidated: bool = False,
    ) -> dict[str, Any]:
        snapshot = self.get_memory_snapshot(
            source_id=source_id,
            session_id=session_id,
            include_invalidated=include_invalidated,
        )
        nodes = [self._graph_node(record) for record in snapshot["records"]]
        edges = [
            {
                "source": str(edge.get("from_id") or ""),
                "target": str(edge.get("to_id") or ""),
                "semantic_sim": float(edge.get("semantic_sim", 0.0) or 0.0),
                "same_entity": bool(edge.get("same_entity")),
                "same_project": bool(edge.get("same_project")),
                "derived_from": bool(edge.get("derived_from")),
                "contradicts": bool(edge.get("contradicts")),
                "updated_at": str(edge.get("updated_at") or ""),
            }
            for edge in snapshot["edges"]
        ]
        return {
            "metadata": snapshot["metadata"],
            "scope": snapshot["scope"],
            "working_summaries": snapshot["working_summaries"],
            "nodes": nodes,
            "edges": edges,
            "stats": self._memory_stats(nodes, edges),
        }

    async def search_records(self, query_text: str, session_id: str = "", source=None) -> list[dict[str, Any]]:
        user_id = self._resolve_user_id(source)
        eligible = self._eligible_records(user_id)
        now = _utcnow()
        query_embedding = await self._get_embedding(query_text)
        scored: list[dict[str, Any]] = []
        if query_embedding and eligible:
            for record in eligible:
                if record.get("embedding"):
                    semantic = self._calc_cosine(query_embedding, record["embedding"])
                else:
                    semantic = self._lexical_score(query_text, record)
                scored.append({"record": record, "semantic": semantic})
            scored.sort(key=lambda item: item["semantic"], reverse=True)
            scored = scored[:SEARCH_TOP_K]
        else:
            lexical = []
            for record in self._store["records"]:
                if record.get("status") != "active":
                    continue
                if record.get("type") not in {"profile_fact", "task", "episode"}:
                    continue
                if record.get("scope", {}).get("user_id") not in {user_id, "global"}:
                    continue
                if record.get("embedding_model") != self._embedding_model:
                    continue
                score = self._lexical_score(query_text, record)
                if score > 0:
                    lexical.append({"record": record, "semantic": score})
            lexical.sort(key=lambda item: item["semantic"], reverse=True)
            scored = lexical[:SEARCH_TOP_K]

        if not scored:
            return []

        anchors = [item for item in scored[:ANCHOR_TOP_K] if item["semantic"] >= ANCHOR_MIN_SIM]
        anchor_ids = {item["record"]["id"] for item in anchors}
        candidate_ids = {item["record"]["id"] for item in scored}
        for anchor_id in anchor_ids:
            candidate_ids.update(self._graph_neighbors(anchor_id))

        results = []
        for record_id in candidate_ids:
            record = self._record_by_id(record_id)
            if record is None or record.get("status") != "active":
                continue
            if record.get("scope", {}).get("user_id") not in {user_id, "global"}:
                continue
            if record.get("embedding_model") != self._embedding_model:
                continue
            semantic = 0.0
            for item in scored:
                if item["record"]["id"] == record_id:
                    semantic = item["semantic"]
                    break
            if semantic == 0.0 and query_embedding and record.get("embedding_model") == self._embedding_model and record.get("embedding"):
                semantic = self._calc_cosine(query_embedding, record["embedding"])
            if semantic == 0.0:
                semantic = self._lexical_score(query_text, record)
            recency = self._recency_score(record, now)
            effective_strength = self._effective_strength(record, now)
            graph = self._graph_score(record_id, anchor_ids)
            score = 0.50 * semantic + 0.20 * recency + 0.15 * float(record.get("importance", 0.0)) + 0.10 * effective_strength + 0.05 * graph
            results.append({
                "record": record,
                "semantic": semantic,
                "score": score,
                "recency": recency,
                "effective_strength": effective_strength,
                "graph": graph,
            })
        results.sort(key=lambda item: item["score"], reverse=True)
        return results

    def _format_profile_line(self, record: MemoryRecord) -> str:
        key = str(record.get("fact_key") or "").strip()
        value = str(record.get("fact_value") or "").strip()
        if key and value:
            return f"- {key}: {value}"
        return f"- {record.get('content', '')}"

    def _format_task_line(self, record: MemoryRecord) -> str:
        summary = str(record.get("content") or "").strip()
        extras = []
        project = str(record.get("project") or "").strip()
        status = str(record.get("task_status") or "").strip()
        deadline = str(record.get("deadline") or "").strip()
        if project:
            extras.append(f"项目:{project}")
        if status:
            extras.append(f"状态:{status}")
        if deadline:
            extras.append(f"截止:{deadline}")
        return f"- {summary} ({', '.join(extras)})" if extras else f"- {summary}"

    def _format_episode_line(self, record: MemoryRecord) -> str:
        return f"- {str(record.get('content') or '').strip()}"

    async def recall_memory(self, query_text: str, session_id: str = "", source=None) -> str:
        results = await self.search_records(query_text, session_id=session_id, source=source)
        if not results:
            return "未找到相关记忆"

        now = _utcnow()
        profile_lines: list[str] = []
        task_lines: list[str] = []
        event_lines: list[str] = []
        used_profile_keys: set[str] = set()
        used_task_keys: set[str] = set()
        touched = False

        for item in results:
            record = item["record"]
            if record.get("type") == "profile_fact":
                key = str(record.get("fact_key") or record.get("id"))
                if key in used_profile_keys or len(profile_lines) >= 3:
                    continue
                profile_lines.append(self._format_profile_line(record))
                used_profile_keys.add(key)
            elif record.get("type") == "task" and record.get("task_status") in {"open", "blocked"}:
                key = str(record.get("task_key") or record.get("id"))
                if key in used_task_keys or len(task_lines) >= 3:
                    continue
                task_lines.append(self._format_task_line(record))
                used_task_keys.add(key)
            else:
                if len(event_lines) >= 3:
                    continue
                event_lines.append(self._format_episode_line(record))

            strength = float(record.get("strength", 0.0))
            record["strength"] = min(1.0, strength + 0.08 * (1 - strength))
            record["last_accessed_at"] = _dt_to_iso(now)
            record["access_count"] = int(record.get("access_count", 0)) + 1
            touched = True

        while len(profile_lines) + len(task_lines) + len(event_lines) > 8:
            if event_lines:
                event_lines.pop()
            elif task_lines:
                task_lines.pop()
            else:
                profile_lines.pop()

        sections = []
        if profile_lines:
            sections.append("[用户画像]\n" + "\n".join(profile_lines))
        if task_lines:
            sections.append("[进行中任务/项目]\n" + "\n".join(task_lines))
        if event_lines:
            sections.append("[最近事件]\n" + "\n".join(event_lines))

        if touched:
            await self.save_memory_graph()
        return "\n\n".join(sections) if sections else "未找到相关记忆"

    def _recall_entry(self, item: dict[str, Any]) -> dict[str, Any]:
        record = item["record"]
        return {
            "id": str(record.get("id") or ""),
            "type": str(record.get("type") or ""),
            "content": str(record.get("content") or ""),
            "scope": deepcopy(record.get("scope", {})),
            "score": round(float(item.get("score", 0.0) or 0.0), 4),
            "semantic": round(float(item.get("semantic", 0.0) or 0.0), 4),
            "recency": round(float(item.get("recency", 0.0) or 0.0), 4),
            "effective_strength": round(float(item.get("effective_strength", 0.0) or 0.0), 4),
            "graph": round(float(item.get("graph", 0.0) or 0.0), 4),
            "strength": round(float(record.get("strength", 0.0) or 0.0), 4),
            "importance": round(float(record.get("importance", 0.0) or 0.0), 4),
            "confidence": round(float(record.get("confidence", 0.0) or 0.0), 4),
            "status": str(record.get("status") or "active"),
            "created_at": str(record.get("created_at") or ""),
            "last_updated_at": str(record.get("last_updated_at") or ""),
            "fact_key": record.get("fact_key"),
            "fact_value": record.get("fact_value"),
            "task_key": record.get("task_key"),
            "project": record.get("project"),
            "task_status": record.get("task_status"),
            "deadline": record.get("deadline"),
        }

    async def _build_recall_payload(
        self,
        query_text: str,
        session_id: str = "",
        source=None,
        reinforce: bool = True,
    ) -> dict[str, Any]:
        results = await self.search_records(query_text, session_id=session_id, source=source)
        payload = {
            "query_text": str(query_text or ""),
            "profile": [],
            "tasks": [],
            "recent_events": [],
        }
        if not results:
            return payload

        now = _utcnow()
        used_profile_keys: set[str] = set()
        used_task_keys: set[str] = set()
        touched = False

        for item in results:
            record = item["record"]
            if record.get("type") == "profile_fact":
                key = str(record.get("fact_key") or record.get("id"))
                if key in used_profile_keys or len(payload["profile"]) >= 3:
                    continue
                payload["profile"].append(self._recall_entry(item))
                used_profile_keys.add(key)
            elif record.get("type") == "task" and record.get("task_status") in {"open", "blocked"}:
                key = str(record.get("task_key") or record.get("id"))
                if key in used_task_keys or len(payload["tasks"]) >= 3:
                    continue
                payload["tasks"].append(self._recall_entry(item))
                used_task_keys.add(key)
            else:
                if len(payload["recent_events"]) >= 3:
                    continue
                payload["recent_events"].append(self._recall_entry(item))

            if reinforce:
                strength = float(record.get("strength", 0.0))
                record["strength"] = min(1.0, strength + 0.08 * (1 - strength))
                record["last_accessed_at"] = _dt_to_iso(now)
                record["access_count"] = int(record.get("access_count", 0)) + 1
                touched = True

        while len(payload["profile"]) + len(payload["tasks"]) + len(payload["recent_events"]) > 8:
            if payload["recent_events"]:
                payload["recent_events"].pop()
            elif payload["tasks"]:
                payload["tasks"].pop()
            else:
                payload["profile"].pop()

        if reinforce and touched:
            await self.save_memory_graph()
        return payload

    def _format_profile_entry(self, entry: dict[str, Any]) -> str:
        key = str(entry.get("fact_key") or "").strip()
        value = str(entry.get("fact_value") or "").strip()
        if key and value:
            return f"- {key}: {value}"
        return f"- {str(entry.get('content') or '').strip()}"

    def _format_task_entry(self, entry: dict[str, Any]) -> str:
        summary = str(entry.get("content") or "").strip()
        extras = []
        project = str(entry.get("project") or "").strip()
        status = str(entry.get("task_status") or "").strip()
        deadline = str(entry.get("deadline") or "").strip()
        if project:
            extras.append(f"椤圭洰:{project}")
        if status:
            extras.append(f"鐘舵€?{status}")
        if deadline:
            extras.append(f"鎴:{deadline}")
        return f"- {summary} ({', '.join(extras)})" if extras else f"- {summary}"

    def _format_event_entry(self, entry: dict[str, Any]) -> str:
        return f"- {str(entry.get('content') or '').strip()}"

    async def recall_memory(self, query_text: str, session_id: str = "", source=None, reinforce: bool = True) -> str:
        payload = await self._build_recall_payload(
            query_text,
            session_id=session_id,
            source=source,
            reinforce=reinforce,
        )
        if not any(payload[key] for key in ("profile", "tasks", "recent_events")):
            return "鏈壘鍒扮浉鍏宠蹇?"

        sections = []
        if payload["profile"]:
            sections.append("[鐢ㄦ埛鐢诲儚]\n" + "\n".join(self._format_profile_entry(item) for item in payload["profile"]))
        if payload["tasks"]:
            sections.append("[杩涜涓换鍔?椤圭洰]\n" + "\n".join(self._format_task_entry(item) for item in payload["tasks"]))
        if payload["recent_events"]:
            sections.append("[鏈€杩戜簨浠禲\n" + "\n".join(self._format_event_entry(item) for item in payload["recent_events"]))
        return "\n\n".join(sections) if sections else "鏈壘鍒扮浉鍏宠蹇?"

    async def recall_memory_structured(
        self,
        query_text: str,
        session_id: str = "",
        source=None,
        reinforce: bool = True,
    ) -> str:
        payload = await self._build_recall_payload(
            query_text,
            session_id=session_id,
            source=source,
            reinforce=reinforce,
        )
        return json.dumps(payload, ensure_ascii=False)

    def _pending_batches(self) -> list[list[MemoryRecord]]:
        grouped: dict[str, list[MemoryRecord]] = {}
        for record in self._store["records"]:
            if not self._episode_pending(record):
                continue
            user_id = record.get("scope", {}).get("user_id", "global")
            grouped.setdefault(user_id, []).append(record)

        now = _utcnow()
        batches = []
        for records in grouped.values():
            records.sort(key=lambda item: item.get("created_at", ""))
            oldest = _iso_to_dt(records[0].get("created_at"))
            if len(records) >= PENDING_TRIGGER_COUNT or now - oldest >= PENDING_TRIGGER_AGE:
                batches.append(records[:PENDING_BATCH_SIZE])
        return batches

    def _strip_json_payload(self, text: str) -> str:
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return raw[start:end + 1]
        return raw

    def _existing_profile_context(self, user_id: str, *, limit: int = 12) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        for record in self._store["records"]:
            if record.get("type") != "profile_fact":
                continue
            if record.get("status") != "active":
                continue
            if record.get("scope", {}).get("user_id") != user_id:
                continue
            facts.append({
                "fact_key": str(record.get("fact_key") or "").strip(),
                "fact_value": str(record.get("fact_value") or "").strip(),
                "content": str(record.get("content") or "").strip(),
                "confidence": float(record.get("confidence", 0.0) or 0.0),
                "last_updated_at": str(record.get("last_updated_at") or ""),
            })
        facts.sort(key=lambda item: item.get("last_updated_at", ""), reverse=True)
        return facts[:limit]

    def _existing_task_context(self, user_id: str, *, limit: int = 12) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for record in self._store["records"]:
            if record.get("type") != "task":
                continue
            if record.get("status") != "active":
                continue
            if record.get("scope", {}).get("user_id") != user_id:
                continue
            tasks.append({
                "task_key": str(record.get("task_key") or "").strip(),
                "summary": str(record.get("content") or "").strip(),
                "project": str(record.get("project") or "").strip(),
                "task_status": str(record.get("task_status") or "").strip(),
                "deadline": record.get("deadline"),
                "confidence": float(record.get("confidence", 0.0) or 0.0),
                "last_updated_at": str(record.get("last_updated_at") or ""),
            })
        tasks.sort(key=lambda item: item.get("last_updated_at", ""), reverse=True)
        return tasks[:limit]

    def _working_summary_context(self, batch: list[MemoryRecord]) -> dict[str, Any]:
        session_ids = sorted({
            str(record.get("scope", {}).get("session_id") or "").strip()
            for record in batch
            if str(record.get("scope", {}).get("session_id") or "").strip()
        })
        by_session = self._store.get("working_summaries", {}).get("by_session", {})
        session_summaries = {}
        for session_id in session_ids:
            summary = str(by_session.get(session_id, "") or "").strip()
            if summary:
                session_summaries[session_id] = summary
        return {
            "global_summary": str(self._store.get("working_summaries", {}).get("global", "") or "").strip(),
            "session_summaries": session_summaries,
        }

    def _episode_hint_payload(self, record: MemoryRecord) -> dict[str, Any]:
        remember_category = self._remember_category(record)
        return {
            "remember_requested": self._is_explicit_memory(record),
            "remember_category": remember_category,
            "tags": list(record.get("tags", [])),
        }

    def _explicit_memory_text(self, record: MemoryRecord) -> str:
        content = str(record.get("content") or "").strip()
        if ":" in content:
            prefix, suffix = content.split(":", 1)
            normalized_prefix = prefix.strip().lower()
            if normalized_prefix.startswith(("durable ", "ongoing ", "user commitment")):
                stripped = suffix.strip()
                if stripped:
                    return stripped
        return content

    def _fallback_key(self, prefix: str, text: str) -> str:
        tokens = TOKEN_RE.findall(_canonicalize(text))
        slug = "_".join(tokens[:6]).strip("_")
        slug = slug[:48]
        return f"{prefix}_{slug}" if slug else prefix

    async def _apply_explicit_memory_fallback(self, user_id: str, batch: list[MemoryRecord]) -> bool:
        changed = False
        for record in batch:
            if not self._is_explicit_memory(record):
                continue
            category = self._remember_category(record) or "fact"
            text = self._explicit_memory_text(record)
            if not text:
                continue
            confidence = 0.88
            if category in TASKLIKE_REMEMBER_CATEGORIES:
                payload = {
                    "task_key": self._fallback_key(category, text),
                    "summary": text,
                    "task_status": "open",
                    "project": category,
                    "deadline": "",
                    "confidence": confidence,
                    "source_record_ids": [record["id"]],
                }
                applied = await self._apply_task_upsert(user_id, payload)
            else:
                payload = {
                    "fact_key": self._fallback_key(category, text),
                    "fact_value": text,
                    "confidence": confidence,
                    "source_record_ids": [record["id"]],
                }
                applied = await self._apply_profile_upsert(user_id, payload)
            changed = applied or changed
        return changed

    def _build_consolidation_prompt(self) -> str:
        return (
            "You are a long-term memory consolidation engine for an assistant. "
            "Convert raw conversation episodes into durable profile facts, durable task state, and lightweight links "
            "that improve future retrieval. Return JSON only, with no markdown and no extra prose.\n"
            "Output schema must be exactly: {\"profile_upserts\": [], \"task_upserts\": [], \"links\": []}.\n"
            "Episode hints:\n"
            "- Each episode may include remember_requested and remember_category from an explicit remember_knowledge call.\n"
            "- If remember_category is profile, preference, or relationship, prefer profile_upserts and avoid task_upserts unless the text is clearly actionable work.\n"
            "- If remember_category is project or commitment, prefer task_upserts unless the text is clearly not actionable.\n"
            "- If remember_requested is true, prefer emitting a coarse but useful durable memory over returning an empty patch.\n"
            "- A single episode can yield multiple profile_upserts when multiple durable facts are explicit.\n"
            "Profile rules:\n"
            "- Store only durable user facts such as identity, stable preferences, background, recurring habits, or durable relationships.\n"
            "- Do not store temporary chit-chat, one-off events, vague feelings, jokes, speculation, or politeness.\n"
            "- fact_key must be stable snake_case and fact_value must be concise and literal.\n"
            "Task rules:\n"
            "- Store only actionable ongoing work, project status, blockers, deadlines, or completed outcomes.\n"
            "- task_key must be stable snake_case for the same task across updates.\n"
            "- summary must capture the current task state, and task_status must be open, blocked, or done.\n"
            "Confidence rules:\n"
            "- 0.90-1.00: explicit and repeated or very clear.\n"
            "- 0.75-0.89: explicit once and clear.\n"
            "- 0.60-0.74: plausible but incomplete.\n"
            "- Below 0.60: do not emit the item.\n"
            "Dedupe and conflict rules:\n"
            "- Use existing_profile_facts and existing_tasks to avoid duplicate outputs.\n"
            "- Only emit an upsert when the batch adds a new durable fact, a changed value, or a meaningful task state update.\n"
            "- Prefer the newest explicit user statement when it conflicts with older memory.\n"
            "Link rules:\n"
            "- links may reference only ids from the current episodes batch.\n"
            "- relation must be same_entity or same_project.\n"
            "- Emit links only when the relationship is explicit from evidence.\n"
            "Few-shot examples:\n"
            "- Example A input: remember_category=relationship, content='Durable relationship fact: 用户叫马生，昵称小马。用户是我的开发者，也是朋友。'\n"
            "  Example A output: {\"profile_upserts\":[{\"fact_key\":\"name\",\"fact_value\":\"马生（小马）\",\"confidence\":0.95,\"source_record_ids\":[\"ep_x\"]},{\"fact_key\":\"relationship_to_assistant\",\"fact_value\":\"developer and friend\",\"confidence\":0.91,\"source_record_ids\":[\"ep_x\"]}],\"task_upserts\":[],\"links\":[]}\n"
            "- Example B input: remember_category=project, content='Ongoing project state: I am still working on the payment callback bug and it is blocking release.'\n"
            "  Example B output: {\"profile_upserts\":[],\"task_upserts\":[{\"task_key\":\"payment_callback_bug\",\"summary\":\"Fix the payment callback bug that is blocking release\",\"task_status\":\"blocked\",\"project\":\"payment\",\"deadline\":\"\",\"confidence\":0.93,\"source_record_ids\":[\"ep_y\"]}],\"links\":[]}\n"
            "- Example C input: content='I feel sleepy today.'\n"
            "  Example C output: {\"profile_upserts\":[],\"task_upserts\":[],\"links\":[]}\n"
            "Be conservative: if uncertain, emit fewer items, not more."
        )

    def _build_consolidation_payload(self, user_id: str, batch: list[MemoryRecord]) -> dict[str, Any]:
        return {
            "current_time": _dt_to_iso(_utcnow()),
            "user_id": user_id,
            "working_summary": self._working_summary_context(batch),
            "existing_profile_facts": self._existing_profile_context(user_id),
            "existing_tasks": self._existing_task_context(user_id),
            "episodes": [
                {
                    "id": record["id"],
                    "content": str(record.get("content") or ""),
                    "created_at": str(record.get("created_at") or ""),
                    "session_id": str(record.get("scope", {}).get("session_id", "") or ""),
                    "importance": float(record.get("importance", 0.0) or 0.0),
                    "hints": self._episode_hint_payload(record),
                }
                for record in batch
            ],
        }

    async def _request_consolidation_patch(self, session, api_url: str, api_key: str, model: str, batch: list[MemoryRecord]) -> ConsolidationPatch | None:
        if self._housekeeping_adapter is None:
            return None
        user_id = str(batch[0].get("scope", {}).get("user_id", "global") or "global")
        payload = self._build_consolidation_payload(user_id, batch)
        messages = [
            {"role": "system", "content": self._build_consolidation_prompt()},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        try:
            result = await self._housekeeping_adapter.chat(session, api_url, api_key, model, messages)
            patch = json.loads(self._strip_json_payload(result.get("content", "")))
            logger.info(
                "Memory consolidation patch user=%s batch=%s profile=%s task=%s links=%s",
                user_id,
                len(batch),
                len(patch.get("profile_upserts", [])),
                len(patch.get("task_upserts", [])),
                len(patch.get("links", [])),
            )
            logger.debug("Memory consolidation patch detail: %s", json.dumps(patch, ensure_ascii=False))
            return patch
        except Exception as e:
            logger.error("Memory consolidation failed: %s", e)
            return None

    def _source_records(self, source_ids: list[str]) -> list[MemoryRecord]:
        records = []
        for source_id in source_ids:
            record = self._record_by_id(source_id)
            if record is not None:
                records.append(record)
        return records

    def _average_importance(self, records: list[MemoryRecord]) -> float:
        if not records:
            return 0.6
        return sum(float(record.get("importance", 0.6)) for record in records) / len(records)

    async def _apply_profile_upsert(self, user_id: str, payload: dict[str, Any]) -> bool:
        fact_key = str(payload.get("fact_key") or "").strip()
        fact_value = str(payload.get("fact_value") or "").strip()
        confidence = float(payload.get("confidence") or 0.0)
        source_ids = [str(item) for item in payload.get("source_record_ids", []) if self._record_by_id(str(item))]
        if not fact_key or not fact_value or not source_ids:
            logger.warning(
                "Rejecting profile upsert for user=%s due to missing fields: fact_key=%s fact_value=%s source_ids=%s",
                user_id,
                bool(fact_key),
                bool(fact_value),
                bool(source_ids),
            )
            return False

        content = f"{fact_key}: {fact_value}"
        embedding = await self._get_embedding(content)
        if not embedding:
            logger.warning("Rejecting profile upsert for user=%s fact_key=%s because embedding failed", user_id, fact_key)
            return False

        source_records = self._source_records(source_ids)
        importance = _clamp(self._average_importance(source_records), 0.2, 1.0)
        now = _dt_to_iso(_utcnow())
        existing = None
        for record in self._store["records"]:
            if record.get("type") == "profile_fact" and record.get("status") == "active" and record.get("scope", {}).get("user_id") == user_id and record.get("fact_key") == fact_key:
                existing = record
                break

        if existing is not None:
            existing_value = _canonicalize(existing.get("fact_value", ""))
            new_value = _canonicalize(fact_value)
            if existing_value == new_value:
                existing["content"] = content
                existing["canonical_text"] = _canonicalize(content)
                existing["embedding"] = embedding
                existing["embedding_model"] = self._embedding_model
                existing["importance"] = max(float(existing.get("importance", 0.0)), importance)
                existing["confidence"] = max(float(existing.get("confidence", 0.0)), confidence)
                existing["last_updated_at"] = now
                existing["source_record_ids"] = sorted(set(existing.get("source_record_ids", [])) | set(source_ids))
                self._link_semantic_edges(existing)
                for source_id in source_ids:
                    self._upsert_edge(existing["id"], source_id, derived_from=True)
                return True
            if confidence >= CONFLICT_CONFIDENCE_THRESHOLD:
                existing["status"] = "invalidated"
                existing["last_updated_at"] = now
                new_record: MemoryRecord = {
                    "id": _make_id("pf"),
                    "type": "profile_fact",
                    "scope": self._record_scope(user_id, "", "profile_fact"),
                    "content": content,
                    "canonical_text": _canonicalize(content),
                    "embedding": embedding,
                    "embedding_model": self._embedding_model,
                    "strength": 0.72,
                    "importance": importance,
                    "confidence": confidence,
                    "created_at": now,
                    "last_accessed_at": now,
                    "last_updated_at": now,
                    "access_count": 0,
                    "status": "active",
                    "tags": [],
                    "entity_keys": [],
                    "source_record_ids": source_ids,
                    "fact_key": fact_key,
                    "fact_value": fact_value,
                }
                self._store["records"].append(new_record)
                self._link_semantic_edges(new_record)
                self._upsert_edge(existing["id"], new_record["id"], contradicts=True)
                for source_id in source_ids:
                    self._upsert_edge(new_record["id"], source_id, derived_from=True)
                return True
            logger.info(
                "Skipping profile upsert for user=%s fact_key=%s because new value conflicts but confidence %.2f is below threshold",
                user_id,
                fact_key,
                confidence,
            )
            return False

        record = {
            "id": _make_id("pf"),
            "type": "profile_fact",
            "scope": self._record_scope(user_id, "", "profile_fact"),
            "content": content,
            "canonical_text": _canonicalize(content),
            "embedding": embedding,
            "embedding_model": self._embedding_model,
            "strength": 0.72,
            "importance": importance,
            "confidence": confidence,
            "created_at": now,
            "last_accessed_at": now,
            "last_updated_at": now,
            "access_count": 0,
            "status": "active",
            "tags": [],
            "entity_keys": [],
            "source_record_ids": source_ids,
            "fact_key": fact_key,
            "fact_value": fact_value,
        }
        self._store["records"].append(record)
        self._link_semantic_edges(record)
        for source_id in source_ids:
            self._upsert_edge(record["id"], source_id, derived_from=True)
        return True

    async def _apply_task_upsert(self, user_id: str, payload: dict[str, Any]) -> bool:
        task_key = str(payload.get("task_key") or "").strip()
        summary = str(payload.get("summary") or "").strip()
        task_status = str(payload.get("task_status") or "open").strip() or "open"
        project = str(payload.get("project") or "").strip()
        deadline = payload.get("deadline")
        confidence = float(payload.get("confidence") or 0.0)
        source_ids = [str(item) for item in payload.get("source_record_ids", []) if self._record_by_id(str(item))]
        if not task_key or not summary or not source_ids:
            logger.warning(
                "Rejecting task upsert for user=%s due to missing fields: task_key=%s summary=%s source_ids=%s",
                user_id,
                bool(task_key),
                bool(summary),
                bool(source_ids),
            )
            return False

        source_records = self._source_records(source_ids)
        remember_categories = self._source_remember_categories(source_records)
        if remember_categories.intersection(NON_TASK_REMEMBER_CATEGORIES) and not remember_categories.intersection(TASKLIKE_REMEMBER_CATEGORIES):
            if not self._looks_like_actionable_task(summary):
                logger.warning(
                    "Rejecting task upsert for user=%s task_key=%s because source remember categories=%s indicate non-task memory",
                    user_id,
                    task_key,
                    sorted(remember_categories),
                )
                return False

        embedding = await self._get_embedding(summary)
        if not embedding:
            logger.warning("Rejecting task upsert for user=%s task_key=%s because embedding failed", user_id, task_key)
            return False

        importance = _clamp(self._average_importance(source_records), 0.2, 1.0)
        now = _dt_to_iso(_utcnow())
        existing = None
        for record in self._store["records"]:
            if record.get("type") == "task" and record.get("status") == "active" and record.get("scope", {}).get("user_id") == user_id and record.get("task_key") == task_key:
                existing = record
                break

        if existing is not None:
            sim = self._calc_cosine(existing.get("embedding", []), embedding) if existing.get("embedding") else 0.0
            if _canonicalize(existing.get("content", "")) == _canonicalize(summary) or sim >= MERGE_SIM_THRESHOLD:
                existing["content"] = summary
                existing["canonical_text"] = _canonicalize(summary)
                existing["embedding"] = embedding
                existing["embedding_model"] = self._embedding_model
                existing["task_status"] = task_status
                existing["project"] = project
                existing["deadline"] = deadline
                existing["importance"] = max(float(existing.get("importance", 0.0)), importance)
                existing["confidence"] = max(float(existing.get("confidence", 0.0)), confidence)
                existing["last_updated_at"] = now
                existing["source_record_ids"] = sorted(set(existing.get("source_record_ids", [])) | set(source_ids))
                self._link_semantic_edges(existing)
                for source_id in source_ids:
                    self._upsert_edge(existing["id"], source_id, derived_from=True)
                return True
            if confidence >= CONFLICT_CONFIDENCE_THRESHOLD:
                existing["status"] = "invalidated"
                existing["last_updated_at"] = now
                new_record: MemoryRecord = {
                    "id": _make_id("task"),
                    "type": "task",
                    "scope": self._record_scope(user_id, "", "task"),
                    "content": summary,
                    "canonical_text": _canonicalize(summary),
                    "embedding": embedding,
                    "embedding_model": self._embedding_model,
                    "strength": 0.68,
                    "importance": importance,
                    "confidence": confidence,
                    "created_at": now,
                    "last_accessed_at": now,
                    "last_updated_at": now,
                    "access_count": 0,
                    "status": "active",
                    "tags": [],
                    "entity_keys": [],
                    "source_record_ids": source_ids,
                    "task_key": task_key,
                    "project": project,
                    "task_status": task_status,
                    "deadline": deadline,
                }
                self._store["records"].append(new_record)
                self._link_semantic_edges(new_record)
                self._upsert_edge(existing["id"], new_record["id"], contradicts=True)
                for source_id in source_ids:
                    self._upsert_edge(new_record["id"], source_id, derived_from=True)
                return True
            logger.info(
                "Skipping task upsert for user=%s task_key=%s because new value conflicts but confidence %.2f is below threshold",
                user_id,
                task_key,
                confidence,
            )
            return False

        record = {
            "id": _make_id("task"),
            "type": "task",
            "scope": self._record_scope(user_id, "", "task"),
            "content": summary,
            "canonical_text": _canonicalize(summary),
            "embedding": embedding,
            "embedding_model": self._embedding_model,
            "strength": 0.68,
            "importance": importance,
            "confidence": confidence,
            "created_at": now,
            "last_accessed_at": now,
            "last_updated_at": now,
            "access_count": 0,
            "status": "active",
            "tags": [],
            "entity_keys": [],
            "source_record_ids": source_ids,
            "task_key": task_key,
            "project": project,
            "task_status": task_status,
            "deadline": deadline,
        }
        self._store["records"].append(record)
        self._link_semantic_edges(record)
        for source_id in source_ids:
            self._upsert_edge(record["id"], source_id, derived_from=True)
        return True

    def _apply_links(self, links: list[dict[str, Any]], batch_ids: set[str]) -> bool:
        changed = False
        for payload in links:
            relation = str(payload.get("relation") or "").strip()
            from_id = str(payload.get("from_id") or "").strip()
            to_id = str(payload.get("to_id") or "").strip()
            if from_id not in batch_ids or to_id not in batch_ids:
                continue
            if relation == "same_entity":
                changed = self._upsert_edge(from_id, to_id, same_entity=True) or changed
            elif relation == "same_project":
                changed = self._upsert_edge(from_id, to_id, same_project=True) or changed
        return changed

    async def consolidate_pending_records(self, session, api_url: str, api_key: str, model: str) -> bool:
        batches = self._pending_batches()
        if not batches or not self._housekeeping_adapter or not api_url or not model:
            return False
        changed = False
        for batch in batches:
            explicit_requested = any(self._is_explicit_memory(record) for record in batch)
            patch = await self._request_consolidation_patch(session, api_url, api_key, model, batch)
            if patch is None:
                continue
            user_id = batch[0].get("scope", {}).get("user_id", "global")
            batch_ids = {record["id"] for record in batch}
            batch_changed = False
            applied_any = False
            for payload in patch.get("profile_upserts", []):
                applied = await self._apply_profile_upsert(user_id, payload)
                applied_any = applied or applied_any
                batch_changed = applied or batch_changed
            for payload in patch.get("task_upserts", []):
                applied = await self._apply_task_upsert(user_id, payload)
                applied_any = applied or applied_any
                batch_changed = applied or batch_changed
            batch_changed = self._apply_links(patch.get("links", []), batch_ids) or batch_changed

            if explicit_requested and not applied_any:
                fallback_changed = await self._apply_explicit_memory_fallback(user_id, batch)
                if fallback_changed:
                    logger.warning(
                        "Applied deterministic fallback for explicit memory batch user=%s categories=%s batch_ids=%s",
                        user_id,
                        sorted(self._source_remember_categories(batch)),
                        sorted(batch_ids),
                    )
                applied_any = fallback_changed or applied_any
                batch_changed = fallback_changed or batch_changed

            if applied_any or not explicit_requested:
                for record in batch:
                    original_tags = list(record.get("tags", []))
                    record["tags"] = [tag for tag in original_tags if tag != "pending_consolidation"]
                    if record["tags"] != original_tags:
                        batch_changed = True
                    record["last_updated_at"] = _dt_to_iso(_utcnow())
                    batch_changed = True
            else:
                logger.warning(
                    "Explicit memory batch produced no durable records; keeping pending_consolidation user=%s categories=%s batch_ids=%s",
                    user_id,
                    sorted(self._source_remember_categories(batch)),
                    sorted(batch_ids),
                )
            changed = batch_changed or changed
        return changed

    def _prune_records(self) -> bool:
        now = _utcnow()
        keep_records: list[MemoryRecord] = []
        removed_ids: set[str] = set()
        changed = False
        for record in self._store["records"]:
            if record.get("status") == "invalidated":
                age_days = max((now - _iso_to_dt(record.get("last_updated_at"))).total_seconds() / 86400.0, 0.0)
                if age_days >= INVALIDATED_RETENTION_DAYS:
                    removed_ids.add(record["id"])
                    changed = True
                    continue
                keep_records.append(record)
                continue
            if record.get("type") == "profile_fact":
                keep_records.append(record)
                continue
            if self._effective_strength(record, now) < MIN_EFFECTIVE_STRENGTH:
                if record.get("type") == "episode" or (record.get("type") == "task" and record.get("task_status") == "done"):
                    removed_ids.add(record["id"])
                    changed = True
                    continue
            keep_records.append(record)
        if changed:
            self._store["records"] = keep_records
            self._store["edges"] = [
                edge
                for edge in self._store["edges"]
                if edge.get("from_id") not in removed_ids and edge.get("to_id") not in removed_ids
            ]
        return changed

    async def run_housekeeping(self, session, api_url: str, api_key: str, model: str) -> None:
        changed = self._prune_records()
        changed = await self.consolidate_pending_records(session, api_url, api_key, model) or changed
        if changed:
            await self.save_memory_graph()
