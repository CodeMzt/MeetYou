from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from core.persistence import atomic_write_json, load_json_with_recovery

logger = logging.getLogger("meetyou.memory")

_MEMORY_SCHEMA_VERSION = "2"
IDEMPOTENCY_WINDOW = timedelta(minutes=30)
PENDING_TRIGGER_COUNT = 20
PENDING_TRIGGER_AGE = timedelta(minutes=30)
PENDING_BATCH_SIZE = 20
SEARCH_TOP_K = 12
ANCHOR_TOP_K = 4
ANCHOR_MIN_SIM = 0.45
LONG_TERM_EDGE_SIM_THRESHOLD = 0.78
LONG_TERM_MERGE_SIM_THRESHOLD = 0.92
CONFLICT_CONFIDENCE_THRESHOLD = 0.7
INVALIDATED_RETENTION_DAYS = 30
MIN_EFFECTIVE_STRENGTH = 0.05
HALF_LIFE_DAYS = {"profile": 180.0, "fact": 90.0, "episode": 14.0}
PROFILE_CATEGORIES = {"profile", "preference", "relationship"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def dt_to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso_to_dt(value: str | None) -> datetime:
    if not value:
        return utcnow()
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return utcnow()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class MemoryStoreLayer:
    def __init__(self, owner):
        self._owner = owner

    def empty_store(self) -> dict[str, Any]:
        now = dt_to_iso(utcnow())
        summary_layer = {"global": "", "by_session": {}}
        return {
            "metadata": {
                "schema_version": _MEMORY_SCHEMA_VERSION,
                "revision": 0,
                "embedding_model": "",
                "embedding_api_url": "",
                "updated_at": now,
            },
            "records": [],
            "edges": [],
            "working_summaries": summary_layer,
            "conversation_summaries": deepcopy(summary_layer),
        }

    def is_valid_store(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        if not isinstance(data.get("metadata"), dict):
            return False
        if not isinstance(data.get("records"), list):
            return False
        if not isinstance(data.get("edges"), list):
            return False
        working = data.get("working_summaries")
        conversation = data.get("conversation_summaries")
        summary_layer = conversation if isinstance(conversation, dict) else working
        if not isinstance(summary_layer, dict):
            return False
        if not isinstance(summary_layer.get("global", ""), str):
            return False
        return isinstance(summary_layer.get("by_session", {}), dict)

    def normalize_store(self) -> None:
        metadata = self._owner._store.setdefault("metadata", {})
        self.ensure_repository_metadata()
        metadata["embedding_model"] = metadata.get("embedding_model") or self._owner._embedding_model
        metadata["embedding_api_url"] = metadata.get("embedding_api_url") or self._owner._embedding_api_url
        metadata["updated_at"] = metadata.get("updated_at") or dt_to_iso(utcnow())
        conversation = self._owner._store.get("conversation_summaries")
        working = conversation if isinstance(conversation, dict) else self._owner._store.get("working_summaries")
        if not isinstance(working, dict):
            working = {"global": "", "by_session": {}}
        working["global"] = str(working.get("global", "") or "")
        by_session = working.get("by_session")
        working["by_session"] = by_session if isinstance(by_session, dict) else {}
        self._owner._store["working_summaries"] = working
        self._owner._store["conversation_summaries"] = working

        normalized_records: list[dict[str, Any]] = []
        removed_ids: set[str] = set()
        for record in self._owner._store.get("records", []):
            if not isinstance(record, dict):
                continue
            record_type = str(record.get("type") or "").strip()
            if record_type == "profile_fact":
                record_type = "profile"
            record["type"] = record_type
            record.setdefault("tags", [])
            record.setdefault("entity_keys", [])
            record.setdefault("source_record_ids", [])
            record.setdefault("status", "active")
            record.setdefault("access_count", 0)
            if record_type not in {"episode", "fact", "profile"}:
                removed_ids.add(str(record.get("id") or ""))
                continue
            normalized_records.append(record)
        self._owner._store["records"] = normalized_records

        normalized_edges: list[dict[str, Any]] = []
        for edge in self._owner._store.get("edges", []):
            if not isinstance(edge, dict):
                continue
            from_id = str(edge.get("from_id") or "")
            to_id = str(edge.get("to_id") or "")
            if not from_id or not to_id or from_id in removed_ids or to_id in removed_ids:
                continue
            normalized_edges.append(edge)
        self._owner._store["edges"] = normalized_edges

    def ensure_repository_metadata(self) -> None:
        metadata = self._owner._store.setdefault("metadata", {})
        metadata["schema_version"] = str(metadata.get("schema_version") or _MEMORY_SCHEMA_VERSION)
        try:
            metadata["revision"] = max(int(metadata.get("revision", 0) or 0), 0)
        except (TypeError, ValueError):
            metadata["revision"] = 0
        metadata["updated_at"] = str(metadata.get("updated_at") or dt_to_iso(utcnow()))

    def touch_updated(self) -> None:
        self.ensure_repository_metadata()
        self._owner._store["metadata"]["updated_at"] = dt_to_iso(utcnow())

    def load_store(self) -> dict[str, Any]:
        store = load_json_with_recovery(
            self._owner._memory_file_path,
            validator=self.is_valid_store,
            default_factory=self.empty_store,
        )
        self._owner._store = store
        self.normalize_store()
        return self._owner._store

    async def save(self) -> None:
        self.touch_updated()
        self._owner._store["metadata"]["revision"] = int(self._owner._store["metadata"].get("revision", 0) or 0) + 1
        atomic_write_json(self._owner._memory_file_path, self._owner._store)

    def record_by_id(self, record_id: str) -> dict[str, Any] | None:
        for record in self._owner._store.get("records", []):
            if record.get("id") == record_id:
                return record
        return None

    def edge_endpoints(self, left: str, right: str) -> tuple[str, str]:
        return tuple(sorted((left, right)))

    def edge_by_pair(self, left: str, right: str) -> dict[str, Any] | None:
        a, b = self.edge_endpoints(left, right)
        for edge in self._owner._store.get("edges", []):
            if edge.get("from_id") == a and edge.get("to_id") == b:
                return edge
        return None

    def upsert_edge(
        self,
        left: str,
        right: str,
        *,
        semantic_sim: float = 0.0,
        same_entity: bool = False,
        same_project: bool = False,
        derived_from: bool = False,
        contradicts: bool = False,
    ) -> bool:
        if not left or not right or left == right:
            return False
        a, b = self.edge_endpoints(left, right)
        edge = self.edge_by_pair(a, b)
        now = dt_to_iso(utcnow())
        if edge is None:
            self._owner._store["edges"].append(
                {
                    "from_id": a,
                    "to_id": b,
                    "semantic_sim": float(semantic_sim),
                    "same_entity": bool(same_entity),
                    "same_project": bool(same_project),
                    "derived_from": bool(derived_from),
                    "contradicts": bool(contradicts),
                    "updated_at": now,
                }
            )
            return True
        before = (
            float(edge.get("semantic_sim", 0.0) or 0.0),
            bool(edge.get("same_entity")),
            bool(edge.get("same_project")),
            bool(edge.get("derived_from")),
            bool(edge.get("contradicts")),
        )
        edge["semantic_sim"] = max(float(edge.get("semantic_sim", 0.0) or 0.0), float(semantic_sim))
        edge["same_entity"] = bool(edge.get("same_entity")) or bool(same_entity)
        edge["same_project"] = bool(edge.get("same_project")) or bool(same_project)
        edge["derived_from"] = bool(edge.get("derived_from")) or bool(derived_from)
        edge["contradicts"] = bool(edge.get("contradicts")) or bool(contradicts)
        edge["updated_at"] = now
        after = (
            float(edge.get("semantic_sim", 0.0) or 0.0),
            bool(edge.get("same_entity")),
            bool(edge.get("same_project")),
            bool(edge.get("derived_from")),
            bool(edge.get("contradicts")),
        )
        return after != before

    def semantic_edge_candidates(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        user_id = record.get("scope", {}).get("user_id")
        results: list[dict[str, Any]] = []
        for other in self._owner._store.get("records", []):
            if other.get("id") == record.get("id"):
                continue
            if other.get("status") != "active":
                continue
            if other.get("type") not in {"episode", "fact", "profile"}:
                continue
            if other.get("embedding_model") != record.get("embedding_model"):
                continue
            if not other.get("embedding"):
                continue
            if other.get("scope", {}).get("user_id") not in {user_id, "global"}:
                continue
            results.append(other)
        return results

    def link_semantic_edges(self, record: dict[str, Any]) -> None:
        embedding = record.get("embedding")
        if not embedding:
            return
        for other in self.semantic_edge_candidates(record):
            sim = self._owner._calc_cosine(embedding, other.get("embedding", []))
            threshold = LONG_TERM_EDGE_SIM_THRESHOLD if record.get("type") in {"fact", "profile"} else 0.75
            if sim >= threshold:
                self.upsert_edge(record["id"], other["id"], semantic_sim=sim)

    def delete_records(self, record_ids: set[str]) -> bool:
        if not record_ids:
            return False
        original_record_count = len(self._owner._store.get("records", []))
        self._owner._store["records"] = [
            record for record in self._owner._store.get("records", []) if record.get("id") not in record_ids
        ]
        self._owner._store["edges"] = [
            edge
            for edge in self._owner._store.get("edges", [])
            if edge.get("from_id") not in record_ids and edge.get("to_id") not in record_ids
        ]
        return len(self._owner._store["records"]) != original_record_count

    def episode_pending(self, record: dict[str, Any]) -> bool:
        return record.get("type") == "episode" and "pending_consolidation" in record.get("tags", [])

    def half_life_days(self, record: dict[str, Any]) -> float:
        return HALF_LIFE_DAYS.get(str(record.get("type") or ""), 30.0)

    def age_days(self, record: dict[str, Any], now: datetime) -> float:
        return max((now - iso_to_dt(record.get("created_at"))).total_seconds() / 86400.0, 0.0)

    def recency_score(self, record: dict[str, Any], now: datetime) -> float:
        return 0.5 ** (self.age_days(record, now) / self.half_life_days(record))

    def effective_strength(self, record: dict[str, Any], now: datetime) -> float:
        return float(record.get("strength", 0.0) or 0.0) * self.recency_score(record, now)

    def prune_records(self) -> bool:
        now = utcnow()
        keep: list[dict[str, Any]] = []
        removed_ids: set[str] = set()
        changed = False
        for record in self._owner._store.get("records", []):
            status = str(record.get("status") or "active")
            if status == "invalidated":
                age_days = max((now - iso_to_dt(record.get("last_updated_at"))).total_seconds() / 86400.0, 0.0)
                if age_days >= INVALIDATED_RETENTION_DAYS:
                    removed_ids.add(str(record.get("id") or ""))
                    changed = True
                    continue
                keep.append(record)
                continue
            if record.get("type") == "profile":
                keep.append(record)
                continue
            if self.effective_strength(record, now) < MIN_EFFECTIVE_STRENGTH:
                removed_ids.add(str(record.get("id") or ""))
                changed = True
                continue
            keep.append(record)
        if changed:
            self._owner._store["records"] = keep
            self._owner._store["edges"] = [
                edge
                for edge in self._owner._store.get("edges", [])
                if edge.get("from_id") not in removed_ids and edge.get("to_id") not in removed_ids
            ]
        return changed


class MemoryViewLayer:
    def __init__(self, owner):
        self._owner = owner

    def _project_record(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": str(record.get("id") or ""),
            "type": str(record.get("type") or ""),
            "scope": deepcopy(record.get("scope", {})),
            "content": str(record.get("content") or ""),
            "strength": float(record.get("strength", 0.0) or 0.0),
            "importance": float(record.get("importance", 0.0) or 0.0),
            "confidence": float(record.get("confidence", 0.0) or 0.0),
            "created_at": str(record.get("created_at") or ""),
            "last_accessed_at": str(record.get("last_accessed_at") or ""),
            "last_updated_at": str(record.get("last_updated_at") or ""),
            "access_count": int(record.get("access_count", 0) or 0),
            "status": str(record.get("status") or "active"),
            "tags": list(record.get("tags", [])),
            "entity_keys": list(record.get("entity_keys", [])),
            "source_record_ids": list(record.get("source_record_ids", [])),
            "fact_key": record.get("fact_key"),
            "fact_value": record.get("fact_value"),
        }
        return payload

    def _project_edge(self, edge: dict[str, Any]) -> dict[str, Any]:
        return {
            "from_id": str(edge.get("from_id") or ""),
            "to_id": str(edge.get("to_id") or ""),
            "semantic_sim": float(edge.get("semantic_sim", 0.0) or 0.0),
            "same_entity": bool(edge.get("same_entity")),
            "same_project": bool(edge.get("same_project")),
            "derived_from": bool(edge.get("derived_from")),
            "contradicts": bool(edge.get("contradicts")),
            "updated_at": str(edge.get("updated_at") or ""),
        }

    def _graph_label(self, record: dict[str, Any]) -> str:
        fact_value = str(record.get("fact_value") or "").strip()
        fact_key = str(record.get("fact_key") or "").strip()
        content = str(record.get("content") or "").strip()
        text = fact_value or fact_key or content
        return text[:18] + "..." if len(text) > 18 else text

    def _graph_node(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = self._project_record(record)
        payload["label"] = self._graph_label(record)
        return payload

    def _working_summary_view(self, session_id: str = "") -> dict[str, Any]:
        working = self._owner._store.get("conversation_summaries") or self._owner._store.get("working_summaries", {})
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
        by_type = {"profile": 0, "fact": 0, "episode": 0}
        for record in records:
            record_type = str(record.get("type") or "")
            if record_type in by_type:
                by_type[record_type] += 1
        return {
            "record_count": len(records),
            "edge_count": len(edges),
            "by_type": by_type,
        }

    def _viewable_records(self, source_id: str = "", include_invalidated: bool = False) -> list[dict[str, Any]]:
        requested_user_id = str(source_id or "").strip()
        allowed_status = {"active", "invalidated"} if include_invalidated else {"active"}
        records: list[dict[str, Any]] = []
        for record in self._owner._store.get("records", []):
            if record.get("type") not in {"episode", "fact", "profile"}:
                continue
            if record.get("status") not in allowed_status:
                continue
            if requested_user_id and record.get("scope", {}).get("user_id") not in {requested_user_id, "global"}:
                continue
            records.append(self._project_record(record))
        return records

    def _viewable_edges(self, record_ids: set[str]) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        for edge in self._owner._store.get("edges", []):
            if edge.get("from_id") in record_ids and edge.get("to_id") in record_ids:
                edges.append(self._project_edge(edge))
        return edges

    def get_memory_snapshot(
        self,
        source_id: str = "",
        session_id: str = "",
        include_invalidated: bool = False,
    ) -> dict[str, Any]:
        records = self._viewable_records(source_id=source_id, include_invalidated=include_invalidated)
        record_ids = {str(record.get("id") or "") for record in records}
        edges = self._viewable_edges(record_ids)
        summary_view = self._working_summary_view(session_id)
        episode_records = [record for record in records if record.get("type") == "episode"]
        profile_records = [record for record in records if record.get("type") == "profile"]
        fact_records = [record for record in records if record.get("type") == "fact"]
        return {
            "metadata": deepcopy(self._owner._store.get("metadata", {})),
            "scope": {
                "source_id": str(source_id or ""),
                "session_id": str(session_id or ""),
            },
            "working_summaries": summary_view,
            "records": records,
            "edges": edges,
            "stats": self._memory_stats(records, edges),
            "layers": {
                "episodes": episode_records,
                "durable_memory": {
                    "profile": profile_records,
                    "facts": fact_records,
                },
                "conversation_summary": summary_view,
                "memory_graph": {
                    "node_count": len(records),
                    "edge_count": len(edges),
                },
            },
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


class MemoryRetrieverLayer:
    def __init__(self, owner):
        self._owner = owner

    def eligible_records(self, user_id: str, session_id: str = "") -> list[dict[str, Any]]:
        current_model = self._owner._embedding_model
        results: list[dict[str, Any]] = []
        normalized_session_id = str(session_id or "").strip()
        for record in self._owner._store.get("records", []):
            if record.get("type") not in {"episode", "fact", "profile"}:
                continue
            if record.get("status") != "active":
                continue
            if record.get("scope", {}).get("user_id") not in {user_id, "global"}:
                continue
            if record.get("embedding_model") != current_model:
                continue
            if record.get("type") == "episode" and normalized_session_id:
                if str(record.get("scope", {}).get("session_id") or "").strip() != normalized_session_id:
                    continue
            results.append(record)
        return results

    def lexical_score(self, query_text: str, record: dict[str, Any]) -> float:
        query = self._owner._canonicalize(query_text)
        haystacks = [self._owner._canonicalize(record.get("content", ""))]
        fact_key = str(record.get("fact_key") or "").strip()
        fact_value = str(record.get("fact_value") or "").strip()
        if fact_key or fact_value:
            haystacks.append(self._owner._canonicalize(f"{fact_key} {fact_value}"))
        joined = " ".join(part for part in haystacks if part)
        if not query or not joined:
            return 0.0
        if query in joined:
            return 1.0
        query_tokens = self._owner._tokens(query)
        record_tokens = set(self._owner._tokens(joined))
        if not query_tokens or not record_tokens:
            return 0.0
        overlap = sum(1 for token in query_tokens if token in record_tokens)
        return overlap / max(len(query_tokens), 1)

    def graph_neighbors(self, record_id: str) -> list[str]:
        neighbors: list[str] = []
        for edge in self._owner._store.get("edges", []):
            if edge.get("contradicts"):
                continue
            sim_ok = float(edge.get("semantic_sim", 0.0) or 0.0) >= LONG_TERM_EDGE_SIM_THRESHOLD
            relation_ok = bool(edge.get("same_entity")) or bool(edge.get("same_project")) or bool(edge.get("derived_from"))
            if not sim_ok and not relation_ok:
                continue
            if edge.get("from_id") == record_id:
                neighbors.append(str(edge.get("to_id") or ""))
            elif edge.get("to_id") == record_id:
                neighbors.append(str(edge.get("from_id") or ""))
        return [item for item in neighbors if item]

    def graph_score(self, record_id: str, anchor_ids: set[str]) -> float:
        if record_id in anchor_ids:
            return 1.0
        best = 0.0
        for anchor_id in anchor_ids:
            edge = self._owner._store_layer.edge_by_pair(record_id, anchor_id)
            if edge is None or edge.get("contradicts"):
                continue
            score = float(edge.get("semantic_sim", 0.0) or 0.0)
            if edge.get("derived_from"):
                score = max(score, 0.7)
            if edge.get("same_project"):
                score = max(score, 0.85)
            if edge.get("same_entity"):
                score = max(score, 1.0)
            best = max(best, score)
        return best

    async def search_records(self, query_text: str, session_id: str = "", source=None) -> list[dict[str, Any]]:
        user_id = self._owner._resolve_user_id(source)
        normalized_session_id = str(session_id or "").strip()
        eligible = self.eligible_records(user_id, session_id=normalized_session_id)
        now = utcnow()
        query_embedding = await self._owner._get_embedding(query_text)
        scored: list[dict[str, Any]] = []
        if query_embedding and eligible:
            for record in eligible:
                semantic = (
                    self._owner._calc_cosine(query_embedding, record.get("embedding", []))
                    if record.get("embedding")
                    else self.lexical_score(query_text, record)
                )
                scored.append({"record": record, "semantic": semantic})
            scored.sort(key=lambda item: item["semantic"], reverse=True)
            scored = scored[:SEARCH_TOP_K]
        else:
            lexical: list[dict[str, Any]] = []
            for record in eligible:
                score = self.lexical_score(query_text, record)
                if score > 0:
                    lexical.append({"record": record, "semantic": score})
            lexical.sort(key=lambda item: item["semantic"], reverse=True)
            scored = lexical[:SEARCH_TOP_K]

        if not scored:
            return []

        anchors = [item for item in scored[:ANCHOR_TOP_K] if item["semantic"] >= ANCHOR_MIN_SIM]
        anchor_ids = {str(item["record"]["id"]) for item in anchors}
        candidate_ids = {str(item["record"]["id"]) for item in scored}
        for anchor_id in anchor_ids:
            candidate_ids.update(self.graph_neighbors(anchor_id))

        results: list[dict[str, Any]] = []
        for record_id in candidate_ids:
            record = self._owner._store_layer.record_by_id(record_id)
            if record is None or record.get("status") != "active":
                continue
            if record.get("type") not in {"episode", "fact", "profile"}:
                continue
            if record.get("scope", {}).get("user_id") not in {user_id, "global"}:
                continue
            if record.get("embedding_model") != self._owner._embedding_model:
                continue
            semantic = 0.0
            for item in scored:
                if item["record"]["id"] == record_id:
                    semantic = float(item["semantic"] or 0.0)
                    break
            if semantic == 0.0 and query_embedding and record.get("embedding"):
                semantic = self._owner._calc_cosine(query_embedding, record["embedding"])
            if semantic == 0.0:
                semantic = self.lexical_score(query_text, record)
            recency = self._owner._store_layer.recency_score(record, now)
            effective_strength = self._owner._store_layer.effective_strength(record, now)
            graph = self.graph_score(record_id, anchor_ids)
            session_bonus = 0.0
            if (
                normalized_session_id
                and record.get("type") == "episode"
                and str(record.get("scope", {}).get("session_id") or "").strip() == normalized_session_id
            ):
                session_bonus = 0.08
            score = (
                0.5 * semantic
                + 0.2 * recency
                + 0.15 * float(record.get("importance", 0.0) or 0.0)
                + 0.1 * effective_strength
                + 0.05 * graph
                + session_bonus
            )
            results.append(
                {
                    "record": record,
                    "semantic": semantic,
                    "score": score,
                    "recency": recency,
                    "effective_strength": effective_strength,
                    "graph": graph,
                    "session_bonus": session_bonus,
                }
            )
        results.sort(key=lambda item: item["score"], reverse=True)
        return results

    def recall_entry(self, item: dict[str, Any]) -> dict[str, Any]:
        record = item["record"]
        payload = self._owner._view_layer._project_record(record)
        payload.update(
            {
                "score": round(float(item.get("score", 0.0) or 0.0), 4),
                "semantic": round(float(item.get("semantic", 0.0) or 0.0), 4),
                "recency": round(float(item.get("recency", 0.0) or 0.0), 4),
                "effective_strength": round(float(item.get("effective_strength", 0.0) or 0.0), 4),
                "graph": round(float(item.get("graph", 0.0) or 0.0), 4),
                "session_bonus": round(float(item.get("session_bonus", 0.0) or 0.0), 4),
            }
        )
        return payload

    async def build_recall_payload(
        self,
        query_text: str,
        session_id: str = "",
        source=None,
        reinforce: bool = True,
    ) -> dict[str, Any]:
        results = await self.search_records(query_text, session_id=session_id, source=source)
        payload = {
            "query_text": str(query_text or ""),
            "scope": {
                "user_id": self._owner._resolve_user_id(source),
                "session_id": str(session_id or ""),
                "session_aware": bool(str(session_id or "").strip()),
            },
            "profile": [],
            "facts": [],
            "recent_events": [],
        }
        if not results:
            return payload

        now = utcnow()
        used_profile_keys: set[str] = set()
        used_fact_keys: set[str] = set()
        touched = False

        for item in results:
            record = item["record"]
            record_type = str(record.get("type") or "")
            if record_type == "profile":
                key = str(record.get("fact_key") or record.get("id"))
                if key in used_profile_keys or len(payload["profile"]) >= 3:
                    continue
                payload["profile"].append(self.recall_entry(item))
                used_profile_keys.add(key)
            elif record_type == "fact":
                key = str(record.get("fact_key") or record.get("content") or record.get("id"))
                if key in used_fact_keys or len(payload["facts"]) >= 3:
                    continue
                payload["facts"].append(self.recall_entry(item))
                used_fact_keys.add(key)
            else:
                if len(payload["recent_events"]) >= 3:
                    continue
                payload["recent_events"].append(self.recall_entry(item))

            if reinforce:
                strength = float(record.get("strength", 0.0) or 0.0)
                record["strength"] = min(1.0, strength + 0.08 * (1 - strength))
                record["last_accessed_at"] = dt_to_iso(now)
                record["access_count"] = int(record.get("access_count", 0) or 0) + 1
                touched = True

        while len(payload["profile"]) + len(payload["facts"]) + len(payload["recent_events"]) > 8:
            if payload["recent_events"]:
                payload["recent_events"].pop()
            elif payload["facts"]:
                payload["facts"].pop()
            else:
                payload["profile"].pop()

        if reinforce and touched:
            await self._owner.save_memory_graph()
        return payload


class MemoryConsolidatorLayer:
    def __init__(self, owner):
        self._owner = owner

    def pending_batches(self) -> list[list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in self._owner._store.get("records", []):
            if not self._owner._store_layer.episode_pending(record):
                continue
            user_id = str(record.get("scope", {}).get("user_id") or "global")
            grouped.setdefault(user_id, []).append(record)
        now = utcnow()
        batches: list[list[dict[str, Any]]] = []
        for records in grouped.values():
            records.sort(key=lambda item: item.get("created_at", ""))
            oldest = iso_to_dt(records[0].get("created_at"))
            if len(records) >= PENDING_TRIGGER_COUNT or now - oldest >= PENDING_TRIGGER_AGE:
                batches.append(records[:PENDING_BATCH_SIZE])
        return batches

    def strip_json_payload(self, text: str) -> str:
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return raw[start : end + 1]
        return raw

    def existing_profile_context(self, user_id: str, *, limit: int = 12) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for record in self._owner._store.get("records", []):
            if record.get("type") != "profile" or record.get("status") != "active":
                continue
            if record.get("scope", {}).get("user_id") != user_id:
                continue
            items.append(
                {
                    "fact_key": str(record.get("fact_key") or "").strip(),
                    "fact_value": str(record.get("fact_value") or "").strip(),
                    "content": str(record.get("content") or "").strip(),
                    "confidence": float(record.get("confidence", 0.0) or 0.0),
                    "last_updated_at": str(record.get("last_updated_at") or ""),
                }
            )
        items.sort(key=lambda item: item.get("last_updated_at", ""), reverse=True)
        return items[:limit]

    def existing_fact_context(self, user_id: str, *, limit: int = 12) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for record in self._owner._store.get("records", []):
            if record.get("type") != "fact" or record.get("status") != "active":
                continue
            if record.get("scope", {}).get("user_id") != user_id:
                continue
            items.append(
                {
                    "fact_key": str(record.get("fact_key") or "").strip(),
                    "fact_value": str(record.get("fact_value") or "").strip(),
                    "content": str(record.get("content") or "").strip(),
                    "confidence": float(record.get("confidence", 0.0) or 0.0),
                    "last_updated_at": str(record.get("last_updated_at") or ""),
                }
            )
        items.sort(key=lambda item: item.get("last_updated_at", ""), reverse=True)
        return items[:limit]

    def working_summary_context(self, batch: list[dict[str, Any]]) -> dict[str, Any]:
        session_ids = sorted(
            {
                str(record.get("scope", {}).get("session_id") or "").strip()
                for record in batch
                if str(record.get("scope", {}).get("session_id") or "").strip()
            }
        )
        by_session = self._owner._store.get("working_summaries", {}).get("by_session", {})
        session_summaries = {}
        for session_id in session_ids:
            summary = str(by_session.get(session_id, "") or "").strip()
            if summary:
                session_summaries[session_id] = summary
        return {
            "global_summary": str(self._owner._store.get("working_summaries", {}).get("global", "") or "").strip(),
            "session_summaries": session_summaries,
        }

    def episode_hint_payload(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "remember_requested": self._owner._is_explicit_memory(record),
            "remember_category": self._owner._remember_category(record),
            "tags": list(record.get("tags", [])),
        }

    def build_consolidation_prompt(self) -> str:
        return (
            "You are a long-term memory consolidation engine for an assistant. "
            "Convert raw conversation episodes into durable profile memory, durable general facts, and lightweight links. "
            "Return JSON only.\n"
            'Output schema must be exactly: {"profile_upserts": [], "fact_upserts": [], "links": []}.\n'
            "Profile rules:\n"
            "- Use profile_upserts for stable identity, preferences, recurring habits, relationships, long-term role/background.\n"
            "- fact_key should be stable snake_case and fact_value concise.\n"
            "Fact rules:\n"
            "- Use fact_upserts for durable project state, ongoing background facts, or other reusable long-term knowledge.\n"
            "- Each fact_upsert should include content, optional fact_key/fact_value, confidence, and source_record_ids.\n"
            "- Do not create tasks or reminders.\n"
            "Memory rules:\n"
            "- Ignore transient chit-chat, fleeting emotions, and one-off niceties.\n"
            "- Prefer the newest explicit user statement when conflicts exist.\n"
            "- Use existing_profiles and existing_facts to avoid duplicates.\n"
            "Link rules:\n"
            "- links may reference only ids from the current episodes batch.\n"
            "- relation must be same_entity or same_project.\n"
            "- Emit links only when the relationship is explicit.\n"
            "If uncertain, emit fewer items."
        )

    def build_consolidation_payload(self, user_id: str, batch: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "current_time": dt_to_iso(utcnow()),
            "user_id": user_id,
            "working_summary": self.working_summary_context(batch),
            "existing_profiles": self.existing_profile_context(user_id),
            "existing_facts": self.existing_fact_context(user_id),
            "episodes": [
                {
                    "id": record["id"],
                    "content": str(record.get("content") or ""),
                    "created_at": str(record.get("created_at") or ""),
                    "session_id": str(record.get("scope", {}).get("session_id") or ""),
                    "importance": float(record.get("importance", 0.0) or 0.0),
                    "hints": self.episode_hint_payload(record),
                }
                for record in batch
            ],
        }

    async def request_consolidation_patch(
        self,
        session,
        api_url: str,
        api_key: str,
        model: str,
        batch: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if self._owner._housekeeping_adapter is None:
            return None
        user_id = str(batch[0].get("scope", {}).get("user_id") or "global")
        payload = self.build_consolidation_payload(user_id, batch)
        messages = [
            {"role": "system", "content": self.build_consolidation_prompt()},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        try:
            result = await self._owner._housekeeping_adapter.chat(session, api_url, api_key, model, messages)
            patch = json.loads(self.strip_json_payload(result.get("content", "")))
            logger.info(
                "Memory consolidation patch user=%s batch=%s profile=%s facts=%s links=%s",
                user_id,
                len(batch),
                len(patch.get("profile_upserts", [])),
                len(patch.get("fact_upserts", [])),
                len(patch.get("links", [])),
            )
            return patch
        except Exception as exc:
            logger.error("Memory consolidation failed: %s", exc)
            return None

    def source_records(self, source_ids: list[str]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for source_id in source_ids:
            record = self._owner._store_layer.record_by_id(source_id)
            if record is not None:
                records.append(record)
        return records

    def average_importance(self, records: list[dict[str, Any]]) -> float:
        if not records:
            return 0.6
        return sum(float(record.get("importance", 0.6) or 0.6) for record in records) / len(records)

    async def apply_profile_upsert(self, user_id: str, payload: dict[str, Any]) -> bool:
        fact_key = str(payload.get("fact_key") or "").strip()
        fact_value = str(payload.get("fact_value") or "").strip()
        confidence = float(payload.get("confidence") or 0.0)
        source_ids = [str(item) for item in payload.get("source_record_ids", []) if self._owner._store_layer.record_by_id(str(item))]
        if not fact_key or not fact_value or not source_ids:
            return False

        content = f"{fact_key}: {fact_value}"
        embedding = await self._owner._get_embedding(content)
        if not embedding:
            return False
        now = dt_to_iso(utcnow())
        source_records = self.source_records(source_ids)
        importance = self._owner._clamp(self.average_importance(source_records), 0.2, 1.0)

        existing = None
        for record in self._owner._store.get("records", []):
            if (
                record.get("type") == "profile"
                and record.get("status") == "active"
                and record.get("scope", {}).get("user_id") == user_id
                and record.get("fact_key") == fact_key
            ):
                existing = record
                break

        if existing is not None:
            existing_value = self._owner._canonicalize(existing.get("fact_value", ""))
            new_value = self._owner._canonicalize(fact_value)
            if existing_value == new_value:
                existing["content"] = content
                existing["canonical_text"] = self._owner._canonicalize(content)
                existing["embedding"] = embedding
                existing["embedding_model"] = self._owner._embedding_model
                existing["importance"] = max(float(existing.get("importance", 0.0) or 0.0), importance)
                existing["confidence"] = max(float(existing.get("confidence", 0.0) or 0.0), confidence)
                existing["last_updated_at"] = now
                existing["source_record_ids"] = sorted(set(existing.get("source_record_ids", [])) | set(source_ids))
                self._owner._store_layer.link_semantic_edges(existing)
                for source_id in source_ids:
                    self._owner._store_layer.upsert_edge(existing["id"], source_id, derived_from=True)
                return True
            if confidence < CONFLICT_CONFIDENCE_THRESHOLD:
                return False
            existing["status"] = "invalidated"
            existing["last_updated_at"] = now

        record = {
            "id": self._owner._make_id("pf"),
            "type": "profile",
            "scope": self._owner._record_scope(user_id, "", "profile"),
            "content": content,
            "canonical_text": self._owner._canonicalize(content),
            "embedding": embedding,
            "embedding_model": self._owner._embedding_model,
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
        self._owner._store["records"].append(record)
        self._owner._store_layer.link_semantic_edges(record)
        if existing is not None:
            self._owner._store_layer.upsert_edge(existing["id"], record["id"], contradicts=True)
        for source_id in source_ids:
            self._owner._store_layer.upsert_edge(record["id"], source_id, derived_from=True)
        return True

    async def apply_fact_upsert(self, user_id: str, payload: dict[str, Any]) -> bool:
        content = str(payload.get("content") or "").strip()
        fact_key = str(payload.get("fact_key") or "").strip()
        fact_value = str(payload.get("fact_value") or "").strip()
        if not content and (fact_key or fact_value):
            content = f"{fact_key}: {fact_value}".strip(": ")
        confidence = float(payload.get("confidence") or 0.0)
        source_ids = [str(item) for item in payload.get("source_record_ids", []) if self._owner._store_layer.record_by_id(str(item))]
        if not content or not source_ids:
            return False

        embedding = await self._owner._get_embedding(content)
        if not embedding:
            return False
        source_records = self.source_records(source_ids)
        importance = self._owner._clamp(self.average_importance(source_records), 0.2, 1.0)
        now = dt_to_iso(utcnow())
        canonical = self._owner._canonicalize(content)

        best_match = None
        best_similarity = 0.0
        for record in self._owner._store.get("records", []):
            if record.get("type") != "fact" or record.get("status") != "active":
                continue
            if record.get("scope", {}).get("user_id") != user_id:
                continue
            similarity = 0.0
            if record.get("embedding") and embedding:
                similarity = self._owner._calc_cosine(record.get("embedding", []), embedding)
            if record.get("fact_key") and fact_key and record.get("fact_key") == fact_key:
                similarity = max(similarity, 0.98)
            if self._owner._canonicalize(record.get("content", "")) == canonical:
                similarity = max(similarity, 1.0)
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = record

        if best_match is not None and best_similarity >= LONG_TERM_MERGE_SIM_THRESHOLD:
            best_match["content"] = content
            best_match["canonical_text"] = canonical
            best_match["embedding"] = embedding
            best_match["embedding_model"] = self._owner._embedding_model
            if fact_key:
                best_match["fact_key"] = fact_key
            if fact_value:
                best_match["fact_value"] = fact_value
            best_match["importance"] = max(float(best_match.get("importance", 0.0) or 0.0), importance)
            best_match["confidence"] = max(float(best_match.get("confidence", 0.0) or 0.0), confidence)
            best_match["last_updated_at"] = now
            best_match["source_record_ids"] = sorted(set(best_match.get("source_record_ids", [])) | set(source_ids))
            self._owner._store_layer.link_semantic_edges(best_match)
            for source_id in source_ids:
                self._owner._store_layer.upsert_edge(best_match["id"], source_id, derived_from=True)
            return True

        record = {
            "id": self._owner._make_id("fact"),
            "type": "fact",
            "scope": self._owner._record_scope(user_id, "", "fact"),
            "content": content,
            "canonical_text": canonical,
            "embedding": embedding,
            "embedding_model": self._owner._embedding_model,
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
            "fact_key": fact_key or None,
            "fact_value": fact_value or None,
        }
        self._owner._store["records"].append(record)
        self._owner._store_layer.link_semantic_edges(record)
        if best_match is not None and best_similarity >= LONG_TERM_EDGE_SIM_THRESHOLD:
            self._owner._store_layer.upsert_edge(best_match["id"], record["id"], semantic_sim=best_similarity)
        for source_id in source_ids:
            self._owner._store_layer.upsert_edge(record["id"], source_id, derived_from=True)
        return True

    def apply_links(self, links: list[dict[str, Any]], batch_ids: set[str]) -> bool:
        changed = False
        for payload in links:
            relation = str(payload.get("relation") or "").strip()
            from_id = str(payload.get("from_id") or "").strip()
            to_id = str(payload.get("to_id") or "").strip()
            if from_id not in batch_ids or to_id not in batch_ids:
                continue
            if relation == "same_entity":
                changed = self._owner._store_layer.upsert_edge(from_id, to_id, same_entity=True) or changed
            elif relation == "same_project":
                changed = self._owner._store_layer.upsert_edge(from_id, to_id, same_project=True) or changed
        return changed

    def explicit_memory_text(self, record: dict[str, Any]) -> str:
        content = str(record.get("content") or "").strip()
        if ":" in content:
            prefix, suffix = content.split(":", 1)
            normalized_prefix = prefix.strip().lower()
            if normalized_prefix.startswith(("durable ", "ongoing ", "user commitment")):
                stripped = suffix.strip()
                if stripped:
                    return stripped
        return content

    def fallback_key(self, prefix: str, text: str) -> str:
        tokens = self._owner._tokens(self._owner._canonicalize(text))
        slug = "_".join(tokens[:6]).strip("_")
        slug = slug[:48]
        return f"{prefix}_{slug}" if slug else prefix

    async def apply_explicit_memory_fallback(self, user_id: str, batch: list[dict[str, Any]]) -> bool:
        changed = False
        for record in batch:
            if not self._owner._is_explicit_memory(record):
                continue
            applied = await self.apply_explicit_memory_record(user_id, record)
            changed = applied or changed
        return changed

    async def apply_explicit_memory_record(self, user_id: str, record: dict[str, Any]) -> bool:
        category = self._owner._remember_category(record) or "fact"
        text = self.explicit_memory_text(record)
        if not text:
            return False
        confidence = 0.88
        if category in PROFILE_CATEGORIES:
            payload = {
                "fact_key": self.fallback_key(category, text),
                "fact_value": text,
                "confidence": confidence,
                "source_record_ids": [record["id"]],
            }
            return await self.apply_profile_upsert(user_id, payload)
        payload = {
            "content": text,
            "fact_key": self.fallback_key(category, text),
            "confidence": confidence,
            "source_record_ids": [record["id"]],
        }
        return await self.apply_fact_upsert(user_id, payload)

    def _merge_target_for_pair(self, left: dict[str, Any], right: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        left_score = (
            float(left.get("confidence", 0.0) or 0.0),
            float(left.get("importance", 0.0) or 0.0),
            str(left.get("last_updated_at") or ""),
            len(str(left.get("content") or "")),
        )
        right_score = (
            float(right.get("confidence", 0.0) or 0.0),
            float(right.get("importance", 0.0) or 0.0),
            str(right.get("last_updated_at") or ""),
            len(str(right.get("content") or "")),
        )
        return (left, right) if left_score >= right_score else (right, left)

    def _merge_long_term_records(self, primary: dict[str, Any], absorbed: dict[str, Any], similarity: float) -> bool:
        changed = False
        if not primary or not absorbed or primary.get("id") == absorbed.get("id"):
            return False
        source_ids = sorted(set(primary.get("source_record_ids", [])) | set(absorbed.get("source_record_ids", [])))
        if primary.get("source_record_ids") != source_ids:
            primary["source_record_ids"] = source_ids
            changed = True
        primary["strength"] = max(float(primary.get("strength", 0.0) or 0.0), float(absorbed.get("strength", 0.0) or 0.0))
        primary["importance"] = max(float(primary.get("importance", 0.0) or 0.0), float(absorbed.get("importance", 0.0) or 0.0))
        primary["confidence"] = max(float(primary.get("confidence", 0.0) or 0.0), float(absorbed.get("confidence", 0.0) or 0.0))
        primary["last_updated_at"] = dt_to_iso(utcnow())
        if absorbed.get("fact_key") and not primary.get("fact_key"):
            primary["fact_key"] = absorbed.get("fact_key")
            changed = True
        if absorbed.get("fact_value") and not primary.get("fact_value"):
            primary["fact_value"] = absorbed.get("fact_value")
            changed = True
        if len(str(absorbed.get("content") or "")) > len(str(primary.get("content") or "")) and float(absorbed.get("confidence", 0.0) or 0.0) >= float(primary.get("confidence", 0.0) or 0.0):
            primary["content"] = absorbed.get("content")
            primary["canonical_text"] = absorbed.get("canonical_text")
            primary["embedding"] = absorbed.get("embedding")
            primary["embedding_model"] = absorbed.get("embedding_model")
            changed = True
        absorbed["status"] = "invalidated"
        absorbed["last_updated_at"] = primary["last_updated_at"]
        self._owner._store_layer.upsert_edge(primary["id"], absorbed["id"], semantic_sim=similarity, derived_from=True)
        return True or changed

    async def consolidate_long_term_memory(self, user_id: str) -> bool:
        records = [
            record
            for record in self._owner._store.get("records", [])
            if record.get("type") in {"fact", "profile"}
            and record.get("status") == "active"
            and record.get("scope", {}).get("user_id") == user_id
            and record.get("embedding_model") == self._owner._embedding_model
            and record.get("embedding")
        ]
        changed = False
        for index, left in enumerate(records):
            if left.get("status") != "active":
                continue
            for right in records[index + 1 :]:
                if right.get("status") != "active":
                    continue
                if left.get("type") != right.get("type"):
                    continue
                if left.get("type") == "profile" and left.get("fact_key") and right.get("fact_key") and left.get("fact_key") != right.get("fact_key"):
                    continue
                similarity = self._owner._calc_cosine(left.get("embedding", []), right.get("embedding", []))
                if similarity >= LONG_TERM_MERGE_SIM_THRESHOLD:
                    primary, absorbed = self._merge_target_for_pair(left, right)
                    changed = self._merge_long_term_records(primary, absorbed, similarity) or changed
                elif similarity >= LONG_TERM_EDGE_SIM_THRESHOLD:
                    changed = self._owner._store_layer.upsert_edge(left["id"], right["id"], semantic_sim=similarity) or changed
        return changed

    async def consolidate_pending_records(self, session, api_url: str, api_key: str, model: str) -> bool:
        batches = self.pending_batches()
        if not batches or not self._owner._housekeeping_adapter or not api_url or not model:
            return False
        changed = False
        for batch in batches:
            patch = await self.request_consolidation_patch(session, api_url, api_key, model, batch)
            if patch is None:
                continue
            user_id = str(batch[0].get("scope", {}).get("user_id") or "global")
            batch_ids = {record["id"] for record in batch}
            applied_any = False
            batch_changed = False
            for payload in patch.get("profile_upserts", []):
                applied = await self.apply_profile_upsert(user_id, payload)
                applied_any = applied or applied_any
                batch_changed = applied or batch_changed
            for payload in patch.get("fact_upserts", []):
                applied = await self.apply_fact_upsert(user_id, payload)
                applied_any = applied or applied_any
                batch_changed = applied or batch_changed
            batch_changed = self.apply_links(patch.get("links", []), batch_ids) or batch_changed
            if not applied_any and any(self._owner._is_explicit_memory(record) for record in batch):
                fallback_changed = await self.apply_explicit_memory_fallback(user_id, batch)
                applied_any = fallback_changed or applied_any
                batch_changed = fallback_changed or batch_changed
            if applied_any or not any(self._owner._is_explicit_memory(record) for record in batch):
                batch_changed = self._owner._store_layer.delete_records(batch_ids) or batch_changed
            else:
                for record in batch:
                    if "pending_consolidation" not in record.get("tags", []):
                        record.setdefault("tags", []).append("pending_consolidation")
            long_term_changed = await self.consolidate_long_term_memory(user_id)
            changed = batch_changed or long_term_changed or changed
        return changed
