from __future__ import annotations

import re
from typing import Any
from datetime import datetime, timezone

from core.db.repositories import ProcedureRepository
from core.services.base import ServiceBase


_PROCEDURE_ID_RE = re.compile(r"[^a-z0-9]+")
_PROCEDURE_TOKEN_RE = re.compile(r"[a-z0-9]+")


class ProcedureService(ServiceBase):
    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized = str(item or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    @staticmethod
    def _normalize_routing_policy(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"balanced", "prefer_owner_client", "strict_preferred"}:
            return "balanced"
        return normalized

    @staticmethod
    def _normalize_status(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"active", "archived", "deleted"}:
            return "active"
        return normalized

    @staticmethod
    def _utcnow_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @classmethod
    def _normalize_infer_keywords(cls, value: Any) -> list[str]:
        keywords = cls._normalize_string_list(value)
        return [item.lower() for item in keywords]

    @classmethod
    def _slugify_procedure_id(cls, value: Any) -> str:
        normalized = _PROCEDURE_ID_RE.sub("_", str(value or "").strip().lower()).strip("_")
        return normalized[:128]

    @classmethod
    def _tokenize_for_inference(cls, value: Any) -> list[str]:
        return [token for token in _PROCEDURE_TOKEN_RE.findall(str(value or "").lower()) if len(token) >= 3]

    @classmethod
    def normalize_meta(cls, meta: dict | None = None) -> dict:
        raw = dict(meta or {})
        preferred_tool_key = str(raw.get("preferred_tool_key") or "").strip()
        preferred_target_endpoint_ids = cls._normalize_string_list(raw.get("preferred_target_endpoint_ids"))
        preferred_endpoint_provider_types = cls._normalize_string_list(raw.get("preferred_endpoint_provider_types"))
        tool_target_routing_policy = cls._normalize_routing_policy(raw.get("tool_target_routing_policy"))
        infer_keywords = cls._normalize_infer_keywords(raw.get("infer_keywords"))
        return {
            **{
                key: value
                for key, value in raw.items()
                if key
                not in {
                    "preferred_tool_key",
                    "preferred_target_endpoint_ids",
                    "preferred_endpoint_provider_types",
                    "tool_target_routing_policy",
                    "infer_keywords",
                }
            },
            "preferred_tool_key": preferred_tool_key,
            "preferred_target_endpoint_ids": preferred_target_endpoint_ids,
            "preferred_endpoint_provider_types": preferred_endpoint_provider_types,
            "tool_target_routing_policy": tool_target_routing_policy,
            "infer_keywords": infer_keywords,
        }

    @classmethod
    def get_routing_view(cls, procedure) -> dict[str, Any]:
        meta = cls.normalize_meta(getattr(procedure, "meta", {}) or {})
        recommended_tools = cls._normalize_string_list(getattr(procedure, "recommended_capabilities", []) or [])
        preferred_tool_key = str(meta.get("preferred_tool_key") or "").strip() or (recommended_tools[0] if recommended_tools else "")
        return {
            "recommended_tools": recommended_tools,
            "preferred_tool_key": preferred_tool_key,
            "preferred_target_endpoint_ids": list(meta.get("preferred_target_endpoint_ids") or []),
            "preferred_endpoint_provider_types": list(meta.get("preferred_endpoint_provider_types") or []),
            "tool_target_routing_policy": str(meta.get("tool_target_routing_policy") or "balanced"),
        }

    @classmethod
    def get_detail_view(cls, procedure) -> dict[str, Any]:
        meta = cls.normalize_meta(getattr(procedure, "meta", {}) or {})
        routing = cls.get_routing_view(procedure)
        return {
            "procedure_id": str(getattr(procedure, "procedure_id", "") or ""),
            "title": str(getattr(procedure, "title", "") or ""),
            "description": str(getattr(procedure, "description", "") or ""),
            "prompt_overlay": str(getattr(procedure, "prompt_overlay", "") or ""),
            "applicable_modes": cls._normalize_string_list(getattr(procedure, "applicable_modes", []) or []),
            "recommended_tools": routing["recommended_tools"],
            "recommended_source_profiles": cls._normalize_string_list(
                getattr(procedure, "recommended_source_profiles", []) or []
            ),
            "preferred_tool_key": routing["preferred_tool_key"],
            "preferred_target_endpoint_ids": routing["preferred_target_endpoint_ids"],
            "preferred_endpoint_provider_types": routing["preferred_endpoint_provider_types"],
            "tool_target_routing_policy": routing["tool_target_routing_policy"],
            "default_execution_target": str(getattr(procedure, "default_execution_target", "") or ""),
            "risk_profile": str(getattr(procedure, "risk_profile", "") or ""),
            "status": cls._normalize_status(getattr(procedure, "status", "active")),
            "infer_keywords": list(meta.get("infer_keywords") or []),
        }

    @classmethod
    def _inference_keywords_for_procedure(cls, procedure) -> list[str]:
        meta = cls.normalize_meta(getattr(procedure, "meta", {}) or {})
        keywords = cls._normalize_infer_keywords(meta.get("infer_keywords"))
        if keywords:
            return keywords
        derived = []
        derived.extend(cls._tokenize_for_inference(getattr(procedure, "procedure_id", "")))
        derived.extend(cls._tokenize_for_inference(getattr(procedure, "title", "")))
        derived.extend(cls._tokenize_for_inference(getattr(procedure, "description", "")))
        return cls._normalize_infer_keywords(derived)

    @classmethod
    def _score_inference(
        cls,
        procedure,
        *,
        content: str,
        preferred_mode: str = "",
        workspace_id: str = "",
    ) -> tuple[int, list[str]]:
        normalized_content = str(content or "").strip().lower()
        normalized_mode = str(preferred_mode or "").strip().lower()
        normalized_workspace_id = str(workspace_id or "").strip().lower()
        if not normalized_content and not normalized_mode and not normalized_workspace_id:
            return 0, []
        score = 0
        reasons: list[str] = []
        applicable_modes = {
            item.lower() for item in cls._normalize_string_list(getattr(procedure, "applicable_modes", []) or [])
        }
        if normalized_mode and normalized_mode in applicable_modes:
            score += 5
            reasons.append(f"mode:{normalized_mode}")
        if normalized_workspace_id.startswith("desktop") and "desktop" in cls.normalize_meta(getattr(procedure, "meta", {}) or {}).get("preferred_endpoint_provider_types", []):
            score += 2
            reasons.append("workspace:desktop")
        if normalized_workspace_id.startswith("study") and "study" in applicable_modes:
            score += 2
            reasons.append("workspace:study")
        if normalized_workspace_id.startswith("home") and str(getattr(procedure, "default_execution_target", "") or "") == "workspace_any_client":
            score += 1
            reasons.append("workspace:client_scope")
        matched_keywords = []
        for keyword in cls._inference_keywords_for_procedure(procedure):
            if keyword and keyword in normalized_content:
                matched_keywords.append(keyword)
        if matched_keywords:
            unique_keywords = []
            seen: set[str] = set()
            for item in matched_keywords:
                if item in seen:
                    continue
                seen.add(item)
                unique_keywords.append(item)
            score += min(len(unique_keywords), 4) * 2
            reasons.append("keywords:" + ",".join(unique_keywords[:4]))
        return score, reasons

    def ensure_procedure(
        self,
        *,
        procedure_id: str,
        principal_id,
        title: str = "",
        description: str = "",
        prompt_overlay: str = "",
        default_execution_target: str = "",
        risk_profile: str = "standard",
        status: str = "active",
        applicable_modes: list[str] | None = None,
        recommended_capabilities: list[str] | None = None,
        recommended_source_profiles: list[str] | None = None,
        meta: dict | None = None,
    ):
        with self.session_scope() as session:
            repo = ProcedureRepository(session)
            existing = repo.get_by_procedure_id(procedure_id)
            if existing is not None:
                updated = False
                normalized_meta = self.normalize_meta(meta)
                if title and existing.title != title:
                    existing.title = title
                    updated = True
                if description and existing.description != description:
                    existing.description = description
                    updated = True
                if prompt_overlay and existing.prompt_overlay != prompt_overlay:
                    existing.prompt_overlay = prompt_overlay
                    updated = True
                if default_execution_target and existing.default_execution_target != default_execution_target:
                    existing.default_execution_target = default_execution_target
                    updated = True
                if risk_profile and existing.risk_profile != risk_profile:
                    existing.risk_profile = risk_profile
                    updated = True
                normalized_status = self._normalize_status(status)
                if status and existing.status != normalized_status:
                    existing.status = normalized_status
                    updated = True
                if applicable_modes and list(existing.applicable_modes or []) != list(applicable_modes):
                    existing.applicable_modes = list(applicable_modes)
                    updated = True
                if recommended_capabilities and list(existing.recommended_capabilities or []) != list(recommended_capabilities):
                    existing.recommended_capabilities = list(recommended_capabilities)
                    updated = True
                if recommended_source_profiles and list(existing.recommended_source_profiles or []) != list(recommended_source_profiles):
                    existing.recommended_source_profiles = list(recommended_source_profiles)
                    updated = True
                if normalized_meta and dict(existing.meta or {}) != normalized_meta:
                    existing.meta = normalized_meta
                    updated = True
                if updated:
                    session.flush()
                return existing
            return repo.create(
                procedure_id=procedure_id,
                principal_id=principal_id,
                title=title,
                description=description,
                prompt_overlay=prompt_overlay,
                default_execution_target=default_execution_target,
                risk_profile=risk_profile,
                status=self._normalize_status(status),
                applicable_modes=applicable_modes,
                recommended_capabilities=recommended_capabilities,
                recommended_source_profiles=recommended_source_profiles,
                meta=self.normalize_meta(meta),
            )

    def create_procedure(
        self,
        *,
        principal_id,
        procedure_id: str = "",
        title: str,
        description: str = "",
        prompt_overlay: str = "",
        default_execution_target: str = "",
        risk_profile: str = "standard",
        applicable_modes: list[str] | None = None,
        recommended_capabilities: list[str] | None = None,
        recommended_source_profiles: list[str] | None = None,
        meta: dict | None = None,
    ):
        normalized_title = str(title or "").strip()
        if not normalized_title:
            raise ValueError("procedure_title_required")
        normalized_procedure_id = self._slugify_procedure_id(procedure_id or normalized_title)
        if not normalized_procedure_id:
            raise ValueError("procedure_id_required")
        with self.session_scope() as session:
            repo = ProcedureRepository(session)
            if repo.get_by_procedure_id(normalized_procedure_id) is not None:
                raise ValueError("procedure_already_exists")
            return repo.create(
                procedure_id=normalized_procedure_id,
                principal_id=principal_id,
                title=normalized_title,
                description=str(description or "").strip(),
                prompt_overlay=str(prompt_overlay or "").strip(),
                default_execution_target=str(default_execution_target or "").strip(),
                risk_profile=str(risk_profile or "standard").strip() or "standard",
                status="active",
                applicable_modes=self._normalize_string_list(applicable_modes),
                recommended_capabilities=self._normalize_string_list(recommended_capabilities),
                recommended_source_profiles=self._normalize_string_list(recommended_source_profiles),
                meta=self.normalize_meta(meta),
            )

    def update_procedure(
        self,
        *,
        procedure_id: str,
        title: str | None = None,
        description: str | None = None,
        prompt_overlay: str | None = None,
        default_execution_target: str | None = None,
        risk_profile: str | None = None,
        status: str | None = None,
        applicable_modes: list[str] | None = None,
        recommended_capabilities: list[str] | None = None,
        recommended_source_profiles: list[str] | None = None,
        meta: dict | None = None,
    ):
        with self.session_scope() as session:
            repo = ProcedureRepository(session)
            procedure = repo.get_by_procedure_id(procedure_id)
            if procedure is None:
                return None
            if title is not None:
                procedure.title = str(title or "").strip()
            if description is not None:
                procedure.description = str(description or "").strip()
            if prompt_overlay is not None:
                procedure.prompt_overlay = str(prompt_overlay or "").strip()
            if default_execution_target is not None:
                procedure.default_execution_target = str(default_execution_target or "").strip()
            if risk_profile is not None:
                procedure.risk_profile = str(risk_profile or "standard").strip() or "standard"
            if status is not None:
                procedure.status = self._normalize_status(status)
            if applicable_modes is not None:
                procedure.applicable_modes = self._normalize_string_list(applicable_modes)
            if recommended_capabilities is not None:
                procedure.recommended_capabilities = self._normalize_string_list(recommended_capabilities)
            if recommended_source_profiles is not None:
                procedure.recommended_source_profiles = self._normalize_string_list(recommended_source_profiles)
            if meta is not None:
                merged_meta = dict(procedure.meta or {})
                merged_meta.update(dict(meta))
                procedure.meta = self.normalize_meta(merged_meta)
            session.flush()
            return procedure

    def archive_procedure(self, *, procedure_id: str):
        with self.session_scope() as session:
            repo = ProcedureRepository(session)
            procedure = repo.get_by_procedure_id(procedure_id)
            if procedure is None:
                return None
            procedure.status = "archived"
            session.flush()
            return procedure

    def get_by_procedure_id(self, procedure_id: str):
        with self.session_scope() as session:
            return ProcedureRepository(session).get_by_procedure_id(procedure_id)

    def get_detail_by_procedure_id(self, procedure_id: str) -> dict[str, Any] | None:
        procedure = self.get_by_procedure_id(procedure_id)
        if procedure is None:
            return None
        return self.get_detail_view(procedure)

    def list_active(self, *, principal_id):
        with self.session_scope() as session:
            return ProcedureRepository(session).list_active(principal_id)

    def list_all(self, *, principal_id):
        with self.session_scope() as session:
            return ProcedureRepository(session).list_all(principal_id)

    def get_thread_context(self, thread) -> dict[str, Any]:
        pinned_snapshot = None
        latest_inferred_snapshot = None
        effective_snapshot = None
        source = "none"
        latest_inferred_reason = ""
        latest_inferred_score = 0
        latest_inferred_at = ""

        pinned_id = str(getattr(thread, "pinned_procedure_id", "") or "").strip()
        if pinned_id:
            procedure = self.get_by_procedure_id(pinned_id)
            if procedure is not None and self._normalize_status(getattr(procedure, "status", "active")) == "active":
                pinned_snapshot = self.get_detail_view(procedure)
                effective_snapshot = pinned_snapshot
                source = "pinned"

        inferred_state = getattr(thread, "meta", {}) or {}
        inferred_payload = dict(inferred_state.get("latest_inferred_procedure") or {})
        inferred_id = str(inferred_payload.get("procedure_id") or "").strip()
        latest_inferred_reason = str(inferred_payload.get("reason") or "").strip()
        latest_inferred_score = max(int(inferred_payload.get("score", 0) or 0), 0)
        latest_inferred_at = str(inferred_payload.get("inferred_at") or "").strip()
        if inferred_id:
            procedure = self.get_by_procedure_id(inferred_id)
            if procedure is not None and self._normalize_status(getattr(procedure, "status", "active")) == "active":
                latest_inferred_snapshot = self.get_detail_view(procedure)
                if effective_snapshot is None:
                    effective_snapshot = latest_inferred_snapshot
                    source = "inferred"

        return {
            "source": source,
            "pinned_procedure": pinned_snapshot,
            "latest_inferred_procedure": latest_inferred_snapshot,
            "effective_procedure": effective_snapshot,
            "latest_inferred_reason": latest_inferred_reason,
            "latest_inferred_score": latest_inferred_score,
            "latest_inferred_at": latest_inferred_at,
        }

    def infer_for_turn(
        self,
        *,
        principal_id,
        content: str,
        preferred_mode: str = "",
        workspace_id: str = "",
    ) -> dict[str, Any]:
        best_procedure = None
        best_score = 0
        best_reasons: list[str] = []
        for procedure in self.list_active(principal_id=principal_id):
            score, reasons = self._score_inference(
                procedure,
                content=content,
                preferred_mode=preferred_mode,
                workspace_id=workspace_id,
            )
            if score > best_score:
                best_score = score
                best_procedure = procedure
                best_reasons = reasons
        if best_procedure is None or best_score <= 0:
            return {
                "matched": False,
                "score": 0,
                "reason": "",
                "procedure_id": "",
                "procedure": None,
                "snapshot": None,
            }
        return {
            "matched": True,
            "score": best_score,
            "reason": "; ".join(best_reasons),
            "procedure_id": best_procedure.procedure_id,
            "procedure": best_procedure,
            "snapshot": self.get_detail_view(best_procedure),
            "inferred_at": self._utcnow_iso(),
        }
