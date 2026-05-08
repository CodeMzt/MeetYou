from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


def _unique_strings(values: list[Any] | tuple[Any, ...] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _normalize_authorization(payload: dict[str, Any] | None, *, source: str = "") -> dict[str, Any]:
    policy = dict(payload or {})
    policy_sources = [
        str(item).strip()
        for item in policy.get("policy_sources", [])
        if str(item).strip()
    ]
    if source and source not in policy_sources:
        policy_sources.append(source)
    return {
        "read_only": bool(policy.get("read_only", False)),
        "policy_sources": policy_sources,
    }


def _append_source(target: dict[str, list[str]], item: str, source: str) -> None:
    normalized_item = str(item or "").strip()
    normalized_source = str(source or "").strip()
    if not normalized_item or not normalized_source:
        return
    values = target.setdefault(normalized_item, [])
    if normalized_source not in values:
        values.append(normalized_source)


def _tool_action_risk(tool_name: str) -> str:
    lowered = str(tool_name or "").strip().lower()
    if not lowered:
        return "read"
    if lowered in {"exec_core_cmd", "exec_sys_cmd"}:
        return "destructive"
    if lowered in {"send_delivery_message", "create_scheduled_workflow", "create_scheduled_delivery"}:
        return "external_write"
    if lowered in {"set_delivery_preference", "manage_scheduled_workflows", "manage_scheduled_deliveries"}:
        return "local_write"
    if any(token in lowered for token in ("delete", "remove", "erase")):
        return "destructive"
    if any(token in lowered for token in ("write", "create", "append", "move", "rename")):
        return "local_write"
    if any(token in lowered for token in ("draft", "schedule")):
        return "external_write"
    if any(token in lowered for token in ("manage_tasks", "manage_scheduled_jobs", "track_mastery", "switch_workspace")):
        return "local_write"
    return "read"


@dataclass(frozen=True)
class PromptCapability:
    capability_id: str
    kind: str
    text: str
    path: str
    fallback: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.capability_id,
            "kind": self.kind,
            "text": self.text,
            "path": self.path,
            "fallback": self.fallback,
        }


@dataclass(frozen=True)
class SkillCapability:
    capability_id: str
    skill_type: str
    title: str
    summary: str
    prompt_ids: list[str]
    tools: list[str]
    mcp_servers: list[str]
    content: str
    applicable_modes: list[str]
    scenarios: list[str]
    activation_keywords: list[str]
    scene_ids: list[str]
    fallback_tools: list[str]
    prompt_only: bool
    storage_path: str
    authorization: dict[str, Any]

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        payload = {
            "id": self.capability_id,
            "skill_type": self.skill_type,
            "title": self.title,
            "summary": self.summary,
            "prompt_ids": list(self.prompt_ids),
            "tools": list(self.tools),
            "mcp_servers": list(self.mcp_servers),
            "applicable_modes": list(self.applicable_modes),
            "scenarios": list(self.scenarios),
            "activation_keywords": list(self.activation_keywords),
            "scenes": list(self.scene_ids),
            "fallback_tools": list(self.fallback_tools),
            "prompt_only": self.prompt_only,
            "storage_path": self.storage_path,
            "authorization": dict(self.authorization),
        }
        if include_content:
            payload["content"] = self.content
        return payload


@dataclass(frozen=True)
class ModeCapability:
    capability_id: str
    prompt_ids: list[str]
    mode_skill_ids: list[str]
    tools: list[str]
    mcp_servers: list[str]
    skills: list[str]
    auto_skills: list[str]
    scene_ids: list[str]
    authorization: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.capability_id,
            "prompts": list(self.prompt_ids),
            "mode_skills": list(self.mode_skill_ids),
            "tools": list(self.tools),
            "mcp_servers": list(self.mcp_servers),
            "skills": list(self.skills),
            "auto_skills": list(self.auto_skills),
            "scenes": list(self.scene_ids),
            "authorization": dict(self.authorization),
        }


@dataclass(frozen=True)
class SceneCapability:
    capability_id: str
    title: str
    summary: str
    applicable_modes: list[str]
    skill_ids: list[str]
    tools: list[str]
    mcp_servers: list[str]
    fallback_tools: list[str]
    activation_keywords: list[str]
    source_profile: str
    authorization: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.capability_id,
            "title": self.title,
            "summary": self.summary,
            "applicable_modes": list(self.applicable_modes),
            "skills": list(self.skill_ids),
            "tools": list(self.tools),
            "mcp_servers": list(self.mcp_servers),
            "fallback_tools": list(self.fallback_tools),
            "activation_keywords": list(self.activation_keywords),
            "source_profile": self.source_profile,
            "authorization": dict(self.authorization),
        }


@dataclass(frozen=True)
class MCPServerCapability:
    capability_id: str
    title: str
    summary: str
    scenarios: list[str]
    risk_level: str
    auth_env: list[str]
    fallback_tools: list[str]
    enabled_by_default: bool
    boundary: str
    managed_by: str
    classification_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.capability_id,
            "title": self.title,
            "summary": self.summary,
            "scenarios": list(self.scenarios),
            "risk_level": self.risk_level,
            "auth_env": list(self.auth_env),
            "fallback_tools": list(self.fallback_tools),
            "enabled_by_default": self.enabled_by_default,
            "boundary": self.boundary,
            "managed_by": self.managed_by,
            "classification_reason": self.classification_reason,
        }


@dataclass(frozen=True)
class CapabilitySet:
    mode: str
    prompt_ids: list[str]
    mode_skill_ids: list[str]
    active_skills: list[str]
    loaded_skills: list[str]
    skill_ids: list[str]
    scene_ids: list[str]
    tools: list[str]
    mcp_servers: list[str]
    authorization: dict[str, Any]
    skill_activations: list[dict[str, Any]]
    capability_sources: dict[str, Any]
    mcp_diagnostics: list[dict[str, Any]]
    degradation_notes: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "prompt_ids": list(self.prompt_ids),
            "mode_skill_ids": list(self.mode_skill_ids),
            "active_skills": list(self.active_skills),
            "loaded_skills": list(self.loaded_skills),
            "skill_ids": list(self.skill_ids),
            "scene_ids": list(self.scene_ids),
            "tools": list(self.tools),
            "mcp_servers": list(self.mcp_servers),
            "authorization": dict(self.authorization),
            "skill_activations": [dict(item) for item in self.skill_activations],
            "capability_sources": dict(self.capability_sources),
            "mcp_diagnostics": [dict(item) for item in self.mcp_diagnostics],
            "degradation_notes": [dict(item) for item in self.degradation_notes],
        }


class CapabilityRegistry:
    def __init__(self, manifest: dict[str, Any], skill_registry) -> None:
        self._manifest = dict(manifest or {})
        self._skill_registry = skill_registry
        self._repo_root = Path(__file__).resolve().parent.parent

    def _absolute_path(self, path_value: str) -> Path:
        candidate = Path(str(path_value or "").strip())
        if not candidate.is_absolute():
            candidate = self._repo_root / candidate
        return candidate

    def get_prompt_capability(self, prompt_id: str) -> PromptCapability | None:
        normalized_id = str(prompt_id or "").strip()
        if not normalized_id:
            return None
        registry = self._manifest.get("prompt_registry") or {}
        entry = dict(registry.get(normalized_id) or {})
        if not entry:
            return None
        fallback = str(entry.get("fallback") or "").strip()
        explicit_text = str(entry.get("text") or "").strip()
        kind = str(entry.get("kind") or "mode").strip().lower() or "mode"
        path_value = str(entry.get("path") or "").strip()
        if not path_value:
            file_name = str(entry.get("file") or "").strip()
            base_dir_key = "skill_prompt_dir" if kind == "skill" else "prompt_dir"
            base_dir = str(self._manifest.get(base_dir_key) or "").strip()
            if file_name and base_dir:
                path_value = str(Path(base_dir) / file_name)
        resolved_text = explicit_text
        resolved_path = ""
        if not resolved_text and path_value:
            prompt_path = self._absolute_path(path_value)
            resolved_path = str(prompt_path)
            try:
                resolved_text = prompt_path.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                resolved_text = ""
        if not resolved_text:
            resolved_text = fallback
        return PromptCapability(
            capability_id=normalized_id,
            kind=kind,
            text=resolved_text,
            path=resolved_path,
            fallback=fallback,
        )

    def get_prompt_text(self, prompt_id: str) -> str:
        prompt = self.get_prompt_capability(prompt_id)
        return prompt.text if prompt is not None else ""

    def get_mode_capability(self, mode: str) -> ModeCapability:
        normalized_mode = str(mode or "").strip().lower()
        definitions = self._manifest.get("mode_definitions") or {}
        payload = dict(definitions.get(normalized_mode) or {})
        if not payload:
            payload = {
                "prompts": [f"mode:{normalized_mode}"],
                "mode_skills": [f"mode:{normalized_mode}"],
                "tools": [],
                "mcp_servers": [],
                "skills": [],
                "auto_skills": [],
                "scenes": [],
            }
        return ModeCapability(
            capability_id=normalized_mode,
            prompt_ids=_unique_strings(payload.get("prompts")),
            mode_skill_ids=_unique_strings(payload.get("mode_skills")),
            tools=_unique_strings(payload.get("tools")),
            mcp_servers=_unique_strings(payload.get("mcp_servers")),
            skills=_unique_strings(payload.get("skills")),
            auto_skills=_unique_strings(payload.get("auto_skills")),
            scene_ids=_unique_strings(payload.get("scenes")),
            authorization=_normalize_authorization(payload.get("authorization"), source=f"mode:{normalized_mode}"),
        )

    def get_skill_capability(self, skill_id: str) -> SkillCapability | None:
        normalized_id = str(skill_id or "").strip()
        if not normalized_id:
            return None
        configured = dict((self._manifest.get("skills") or {}).get(normalized_id) or {})
        loaded = self._skill_registry.load_skill(normalized_id)
        if loaded is None and not configured:
            return None
        recommended_tools = _unique_strings(
            list(configured.get("tools") or []) + list((loaded or {}).get("recommended_tools") or [])
        )
        mcp_servers = _unique_strings(configured.get("mcp_servers"))
        prompt_ids = _unique_strings(configured.get("prompts"))
        content = str((loaded or {}).get("content") or "").strip()
        capability_id = str((loaded or {}).get("id") or normalized_id).strip()
        return SkillCapability(
            capability_id=capability_id,
            skill_type=str((loaded or {}).get("skill_type") or "reusable").strip(),
            title=str((loaded or {}).get("title") or normalized_id).strip(),
            summary=str((loaded or {}).get("summary") or "").strip(),
            prompt_ids=prompt_ids,
            tools=recommended_tools,
            mcp_servers=mcp_servers,
            content=content,
            applicable_modes=_unique_strings((loaded or {}).get("applicable_modes")),
            scenarios=_unique_strings((loaded or {}).get("scenarios")),
            activation_keywords=_unique_strings(configured.get("activation_keywords")),
            scene_ids=_unique_strings(configured.get("scenes")),
            fallback_tools=_unique_strings(configured.get("fallback_tools")),
            prompt_only=not recommended_tools and not mcp_servers,
            storage_path=str((loaded or {}).get("storage_path") or "").strip(),
            authorization=_normalize_authorization(
                dict(configured.get("authorization") or (loaded or {}).get("authorization") or {}),
                source=f"skill:{capability_id}",
            ),
        )

    def get_scene_capability(self, scene_id: str) -> SceneCapability | None:
        normalized_id = str(scene_id or "").strip()
        if not normalized_id:
            return None
        payload = dict((self._manifest.get("scene_definitions") or {}).get(normalized_id) or {})
        if not payload:
            return None
        return SceneCapability(
            capability_id=normalized_id,
            title=str(payload.get("title") or normalized_id).strip(),
            summary=str(payload.get("summary") or "").strip(),
            applicable_modes=_unique_strings(payload.get("applicable_modes")),
            skill_ids=_unique_strings(payload.get("skills")),
            tools=_unique_strings(payload.get("tools")),
            mcp_servers=_unique_strings(payload.get("mcp_servers")),
            fallback_tools=_unique_strings(payload.get("fallback_tools")),
            activation_keywords=_unique_strings(payload.get("activation_keywords")),
            source_profile=str(payload.get("source_profile") or "").strip(),
            authorization=_normalize_authorization(payload.get("authorization"), source=f"scene:{normalized_id}"),
        )

    def get_mcp_server_capability(self, server_name: str) -> MCPServerCapability | None:
        normalized_name = str(server_name or "").strip()
        if not normalized_name:
            return None
        payload = dict((self._manifest.get("mcp_catalog") or {}).get(normalized_name) or {})
        if not payload:
            return None
        auth_env = _unique_strings(payload.get("auth_env"))
        if not auth_env:
            auth_env = _unique_strings(((payload.get("auth") or {}).get("env")))
        return MCPServerCapability(
            capability_id=normalized_name,
            title=str(payload.get("title") or normalized_name).strip(),
            summary=str(payload.get("summary") or "").strip(),
            scenarios=_unique_strings(payload.get("scenarios")),
            risk_level=str(payload.get("risk_level") or "read").strip(),
            auth_env=auth_env,
            fallback_tools=_unique_strings(payload.get("fallback_tools")),
            enabled_by_default=bool(payload.get("enabled_by_default", True)),
            boundary=str(payload.get("boundary") or "core_mcp").strip() or "core_mcp",
            managed_by=str(payload.get("managed_by") or "core").strip() or "core",
            classification_reason=str(payload.get("classification_reason") or "").strip(),
        )

    @staticmethod
    def _normalize_skill_activation(skill_id: str, raw_result: Any, *, source: str) -> dict[str, Any]:
        base = {
            "skill_id": str(skill_id or "").strip(),
            "active": False,
            "reason": "",
            "signals": [],
            "confidence": "",
            "adapter_name": "",
            "source": source,
        }
        if isinstance(raw_result, dict):
            payload = dict(raw_result)
            payload["skill_id"] = str(payload.get("skill_id") or base["skill_id"]).strip()
            payload["active"] = bool(payload.get("active", payload.get("value", False)))
            payload["reason"] = str(payload.get("reason") or "").strip()
            payload["signals"] = _unique_strings(payload.get("signals"))
            payload["confidence"] = str(payload.get("confidence") or "").strip()
            payload["adapter_name"] = str(payload.get("adapter_name") or "").strip()
            payload["source"] = str(payload.get("source") or source).strip()
            return payload
        return {
            **base,
            "active": bool(raw_result),
        }

    def _resolve_skill_activations(
        self,
        mode: str,
        *,
        content: str = "",
        active_skills: list[str] | None = None,
        loaded_skills: list[str] | None = None,
        activator: Callable[[str, str], Any] | None = None,
    ) -> tuple[list[str], list[dict[str, Any]], list[str]]:
        mode_capability = self.get_mode_capability(mode)
        activation_records: list[dict[str, Any]] = []
        resolved_active_skills: list[str] = []
        resolved_loaded_skills = _unique_strings(loaded_skills)
        if active_skills is not None:
            for skill_id in _unique_strings(active_skills):
                resolved_active_skills.append(skill_id)
                activation_records.append(
                    {
                        "skill_id": skill_id,
                        "active": True,
                        "reason": "Route selected this skill explicitly.",
                        "signals": [],
                        "confidence": "",
                        "adapter_name": "",
                        "source": "route",
                    }
                )
        else:
            for skill_id in mode_capability.skills:
                resolved_active_skills.append(skill_id)
                activation_records.append(
                    {
                        "skill_id": skill_id,
                        "active": True,
                        "reason": f"Mode {mode_capability.capability_id} attaches this skill by default.",
                        "signals": [f"mode:{mode_capability.capability_id}"],
                        "confidence": "high",
                        "adapter_name": "",
                        "source": "mode",
                    }
                )
            for skill_id in mode_capability.auto_skills:
                normalized = self._normalize_skill_activation(
                    skill_id,
                    activator(skill_id, content) if activator is not None else True,
                    source="router",
                )
                if not normalized.get("active"):
                    continue
                resolved_active_skills.append(skill_id)
                activation_records.append(normalized)
        for skill_id in resolved_loaded_skills:
            activation_records.append(
                {
                    "skill_id": skill_id,
                    "active": True,
                    "reason": "This skill was loaded into the current route context.",
                    "signals": ["loaded_skill"],
                    "confidence": "high",
                    "adapter_name": "",
                    "source": "loaded",
                }
            )
        unique_active = _unique_strings(resolved_active_skills)
        unique_activation_records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in activation_records:
            skill_id = str(record.get("skill_id") or "").strip()
            if not skill_id or skill_id in seen:
                continue
            seen.add(skill_id)
            unique_activation_records.append(record)
        return unique_active, unique_activation_records, resolved_loaded_skills

    def _resolve_scene_ids(
        self,
        mode: str,
        *,
        content: str,
        mode_capability: ModeCapability,
        skill_capabilities: list[SkillCapability],
    ) -> list[str]:
        lowered = str(content or "").lower()
        resolved_scene_ids = list(mode_capability.scene_ids)
        for skill_capability in skill_capabilities:
            resolved_scene_ids.extend(skill_capability.scene_ids)
        scene_definitions = self._manifest.get("scene_definitions") or {}
        for scene_id in _unique_strings(scene_definitions.keys()):
            capability = self.get_scene_capability(scene_id)
            if capability is None:
                continue
            if capability.applicable_modes and mode not in capability.applicable_modes:
                continue
            has_keyword = any(keyword.lower() in lowered for keyword in capability.activation_keywords if keyword)
            has_skill = any(skill.capability_id in capability.skill_ids for skill in skill_capabilities)
            if has_keyword or has_skill:
                resolved_scene_ids.append(scene_id)
        return _unique_strings(resolved_scene_ids)

    def describe_mcp_servers(
        self,
        server_names: list[str] | tuple[str, ...],
        *,
        available_mcp_servers: list[str] | None = None,
        configured_mcp_servers: list[str] | None = None,
        env_provider: Callable[[str], str | None] | None = None,
    ) -> list[dict[str, Any]]:
        available_set = set(_unique_strings(available_mcp_servers))
        configured_set = set(_unique_strings(configured_mcp_servers))
        lookup_env = env_provider or os.getenv
        diagnostics: list[dict[str, Any]] = []
        for server_name in _unique_strings(list(server_names or [])):
            capability = self.get_mcp_server_capability(server_name)
            fallback_tools = list((capability.fallback_tools if capability is not None else []))
            auth_env = list((capability.auth_env if capability is not None else []))
            missing_auth = [env_name for env_name in auth_env if not str(lookup_env(env_name) or "").strip()]
            if missing_auth:
                status = "requires_auth"
            elif available_set:
                if server_name in available_set:
                    status = "enabled"
                elif configured_set and server_name in configured_set:
                    status = "unavailable"
                else:
                    status = "not_enabled"
            elif configured_set:
                status = "configured" if server_name in configured_set else "declared"
            else:
                status = "declared"
            usable = status in {"enabled", "configured", "declared"}
            diagnostics.append(
                {
                    "server_name": server_name,
                    "title": str((capability.title if capability is not None else server_name) or server_name).strip(),
                    "summary": str((capability.summary if capability is not None else "") or "").strip(),
                    "status": status,
                    "usable": usable,
                    "risk_level": str((capability.risk_level if capability is not None else "read") or "read").strip(),
                    "scenarios": list((capability.scenarios if capability is not None else [])),
                    "auth_env": auth_env,
                    "missing_auth": missing_auth,
                    "fallback_tools": fallback_tools,
                    "degraded": not usable and bool(fallback_tools),
                    "boundary": str((capability.boundary if capability is not None else "core_mcp") or "core_mcp"),
                    "managed_by": str((capability.managed_by if capability is not None else "core") or "core"),
                    "classification_reason": str((capability.classification_reason if capability is not None else "") or ""),
                }
            )
        return diagnostics

    def resolve_active_skills(
        self,
        mode: str,
        *,
        content: str = "",
        activator: Callable[[str, str], Any] | None = None,
    ) -> list[str]:
        mode_capability = self.get_mode_capability(mode)
        active_skills = list(mode_capability.skills)
        for skill_id in mode_capability.auto_skills:
            normalized = self._normalize_skill_activation(
                skill_id,
                activator(skill_id, content) if activator is not None else True,
                source="router",
            )
            if normalized.get("active"):
                active_skills.append(skill_id)
        return _unique_strings(active_skills)

    def build_capability_set(
        self,
        mode: str,
        *,
        content: str = "",
        active_skills: list[str] | None = None,
        loaded_skills: list[str] | None = None,
        activator: Callable[[str, str], Any] | None = None,
        available_mcp_servers: list[str] | None = None,
        configured_mcp_servers: list[str] | None = None,
        env_provider: Callable[[str], str | None] | None = None,
    ) -> CapabilitySet:
        mode_capability = self.get_mode_capability(mode)
        resolved_active_skills, skill_activations, resolved_loaded_skills = self._resolve_skill_activations(
            mode,
            content=content,
            active_skills=active_skills,
            loaded_skills=loaded_skills,
            activator=activator,
        )
        prompt_ids = list(mode_capability.prompt_ids)
        tools = list(_unique_strings(self._manifest.get("basic_tools")))
        tools.extend(mode_capability.tools)
        desired_mcp_servers = list(mode_capability.mcp_servers)
        skill_ids = list(mode_capability.mode_skill_ids)
        capability_sources = {
            "tools": {},
            "mcp_servers": {},
            "skills": {},
            "scenes": {},
        }
        read_only_sources = [
            str(item).strip()
            for item in mode_capability.authorization.get("policy_sources", [])
            if str(item).strip() and mode_capability.authorization.get("read_only")
        ]
        for tool_name in tools:
            _append_source(capability_sources["tools"], tool_name, f"basic:{mode_capability.capability_id}")
        for tool_name in mode_capability.tools:
            _append_source(capability_sources["tools"], tool_name, f"mode:{mode_capability.capability_id}")
        for server_name in desired_mcp_servers:
            _append_source(capability_sources["mcp_servers"], server_name, f"mode:{mode_capability.capability_id}")
        for skill_id in mode_capability.mode_skill_ids:
            _append_source(capability_sources["skills"], skill_id, f"mode:{mode_capability.capability_id}")
        skill_capabilities: list[SkillCapability] = []
        for skill_id in [*resolved_active_skills, *resolved_loaded_skills]:
            skill_capability = self.get_skill_capability(skill_id)
            if skill_capability is None:
                continue
            skill_capabilities.append(skill_capability)
            prompt_ids.extend(skill_capability.prompt_ids)
            tools.extend(skill_capability.tools)
            desired_mcp_servers.extend(skill_capability.mcp_servers)
            skill_ids.append(skill_capability.capability_id)
            _append_source(capability_sources["skills"], skill_capability.capability_id, f"skill:{skill_capability.capability_id}")
            for tool_name in skill_capability.tools:
                _append_source(capability_sources["tools"], tool_name, f"skill:{skill_capability.capability_id}")
            for server_name in skill_capability.mcp_servers:
                _append_source(capability_sources["mcp_servers"], server_name, f"skill:{skill_capability.capability_id}")
            if skill_capability.authorization.get("read_only"):
                read_only_sources.extend(skill_capability.authorization.get("policy_sources", []))
        scene_ids = self._resolve_scene_ids(
            mode_capability.capability_id,
            content=content,
            mode_capability=mode_capability,
            skill_capabilities=skill_capabilities,
        )
        for scene_id in scene_ids:
            scene_capability = self.get_scene_capability(scene_id)
            if scene_capability is None:
                continue
            _append_source(capability_sources["scenes"], scene_capability.capability_id, f"scene:{scene_capability.capability_id}")
            tools.extend(scene_capability.tools)
            desired_mcp_servers.extend(scene_capability.mcp_servers)
            for tool_name in scene_capability.tools:
                _append_source(capability_sources["tools"], tool_name, f"scene:{scene_capability.capability_id}")
            for server_name in scene_capability.mcp_servers:
                _append_source(capability_sources["mcp_servers"], server_name, f"scene:{scene_capability.capability_id}")
            if scene_capability.authorization.get("read_only"):
                read_only_sources.extend(scene_capability.authorization.get("policy_sources", []))
        mcp_diagnostics = self.describe_mcp_servers(
            desired_mcp_servers,
            available_mcp_servers=available_mcp_servers,
            configured_mcp_servers=configured_mcp_servers,
            env_provider=env_provider,
        )
        usable_mcp_servers = [
            item["server_name"]
            for item in mcp_diagnostics
            if item.get("usable")
        ]
        degradation_notes = [
            {
                "capability_type": "mcp_server",
                "capability_id": item["server_name"],
                "status": item["status"],
                "fallback_tools": list(item.get("fallback_tools") or []),
                "reason": (
                    f"MCP server {item['server_name']} is {item['status']} and the route will fall back to native tools."
                    if item.get("fallback_tools")
                    else f"MCP server {item['server_name']} is {item['status']}."
                ),
            }
            for item in mcp_diagnostics
            if not item.get("usable")
        ]
        authorization = {
            "read_only": bool(read_only_sources),
            "policy_sources": _unique_strings(read_only_sources),
        }
        return CapabilitySet(
            mode=mode_capability.capability_id,
            prompt_ids=_unique_strings(prompt_ids),
            mode_skill_ids=list(mode_capability.mode_skill_ids),
            active_skills=resolved_active_skills,
            loaded_skills=resolved_loaded_skills,
            skill_ids=_unique_strings(skill_ids),
            scene_ids=scene_ids,
            tools=_unique_strings(tools),
            mcp_servers=_unique_strings(usable_mcp_servers if available_mcp_servers is not None else desired_mcp_servers),
            authorization=authorization,
            skill_activations=skill_activations,
            capability_sources=capability_sources,
            mcp_diagnostics=mcp_diagnostics,
            degradation_notes=degradation_notes,
        )

    def validate(
        self,
        *,
        tool_checker: Callable[[str], bool] | None = None,
        mcp_checker: Callable[[str], bool] | None = None,
    ) -> list[str]:
        problems: list[str] = []
        for mode in _unique_strings((self._manifest.get("enabled_modes") or [])):
            capability_set = self.build_capability_set(mode)
            if not capability_set.prompt_ids:
                problems.append(f"mode {mode} is missing prompt_ids")
            for prompt_id in capability_set.prompt_ids:
                if self.get_prompt_capability(prompt_id) is None:
                    problems.append(f"prompt {prompt_id} is not registered")
            for skill_id in capability_set.skill_ids:
                if self.get_skill_capability(skill_id) is None:
                    problems.append(f"skill {skill_id} is not registered")
            for scene_id in capability_set.scene_ids:
                if self.get_scene_capability(scene_id) is None:
                    problems.append(f"scene {scene_id} is not registered")
            if tool_checker is not None:
                for tool_name in capability_set.tools:
                    if not tool_checker(tool_name):
                        problems.append(f"tool {tool_name} is not available")
        for skill in self._skill_registry.list_skills():
            capability = self.get_skill_capability(skill.get("id"))
            if capability is None:
                problems.append(f"skill {skill.get('id')} is not registered")
                continue
            for prompt_id in capability.prompt_ids:
                if self.get_prompt_capability(prompt_id) is None:
                    problems.append(f"prompt {prompt_id} is not registered")
            for tool_name in [*capability.tools, *capability.fallback_tools]:
                if tool_checker is not None and not tool_checker(tool_name):
                    problems.append(f"tool {tool_name} is not available")
            for server_name in capability.mcp_servers:
                if self.get_mcp_server_capability(server_name) is None:
                    problems.append(f"mcp server {server_name} is not declared")
            if capability.authorization.get("read_only"):
                for tool_name in capability.tools:
                    if _tool_action_risk(tool_name) != "read":
                        problems.append(f"read-only skill {capability.capability_id} exposes write tool {tool_name}")
        for scene_id in _unique_strings((self._manifest.get("scene_definitions") or {}).keys()):
            capability = self.get_scene_capability(scene_id)
            if capability is None:
                continue
            for skill_id in capability.skill_ids:
                if self.get_skill_capability(skill_id) is None:
                    problems.append(f"scene {scene_id} references unknown skill {skill_id}")
            for tool_name in [*capability.tools, *capability.fallback_tools]:
                if tool_checker is not None and not tool_checker(tool_name):
                    problems.append(f"tool {tool_name} is not available")
            for server_name in capability.mcp_servers:
                if self.get_mcp_server_capability(server_name) is None:
                    problems.append(f"scene {scene_id} references unknown mcp server {server_name}")
            if capability.authorization.get("read_only"):
                for tool_name in capability.tools:
                    if _tool_action_risk(tool_name) != "read":
                        problems.append(f"read-only scene {scene_id} exposes write tool {tool_name}")
        if mcp_checker is not None:
            for server_name in _unique_strings((self._manifest.get("mcp_catalog") or {}).keys()):
                if self.get_mcp_server_capability(server_name) is None:
                    continue
                if not mcp_checker(server_name):
                    continue
        return _unique_strings(problems)

    def get_diagnostics(
        self,
        *,
        tool_names: list[str] | None = None,
        available_mcp_servers: list[str] | None = None,
        configured_mcp_servers: list[str] | None = None,
        env_provider: Callable[[str], str | None] | None = None,
    ) -> dict[str, Any]:
        tool_checker = (lambda tool_name: tool_name in set(_unique_strings(tool_names))) if tool_names else None
        problems = self.validate(tool_checker=tool_checker)
        skills = []
        for skill in self._skill_registry.list_skills():
            capability = self.get_skill_capability(skill.get("id"))
            if capability is not None:
                skills.append(capability.to_dict())
        scenes = []
        for scene_id in _unique_strings((self._manifest.get("scene_definitions") or {}).keys()):
            capability = self.get_scene_capability(scene_id)
            if capability is not None:
                scenes.append(capability.to_dict())
        mcp_servers = self.describe_mcp_servers(
            list((self._manifest.get("mcp_catalog") or {}).keys()),
            available_mcp_servers=available_mcp_servers,
            configured_mcp_servers=configured_mcp_servers,
            env_provider=env_provider,
        )
        return {
            "problems": problems,
            "skills": skills,
            "scenes": scenes,
            "mcp_servers": mcp_servers,
        }
