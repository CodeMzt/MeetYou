from __future__ import annotations

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
            "authorization": dict(self.authorization),
        }


@dataclass(frozen=True)
class CapabilitySet:
    mode: str
    prompt_ids: list[str]
    mode_skill_ids: list[str]
    active_skills: list[str]
    loaded_skills: list[str]
    skill_ids: list[str]
    tools: list[str]
    mcp_servers: list[str]
    authorization: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "prompt_ids": list(self.prompt_ids),
            "mode_skill_ids": list(self.mode_skill_ids),
            "active_skills": list(self.active_skills),
            "loaded_skills": list(self.loaded_skills),
            "skill_ids": list(self.skill_ids),
            "tools": list(self.tools),
            "mcp_servers": list(self.mcp_servers),
            "authorization": dict(self.authorization),
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
            }
        return ModeCapability(
            capability_id=normalized_mode,
            prompt_ids=_unique_strings(payload.get("prompts")),
            mode_skill_ids=_unique_strings(payload.get("mode_skills")),
            tools=_unique_strings(payload.get("tools")),
            mcp_servers=_unique_strings(payload.get("mcp_servers")),
            skills=_unique_strings(payload.get("skills")),
            auto_skills=_unique_strings(payload.get("auto_skills")),
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
            prompt_only=not recommended_tools and not mcp_servers,
            storage_path=str((loaded or {}).get("storage_path") or "").strip(),
            authorization=_normalize_authorization(
                dict(configured.get("authorization") or (loaded or {}).get("authorization") or {}),
                source=f"skill:{capability_id}",
            ),
        )

    def resolve_active_skills(
        self,
        mode: str,
        *,
        content: str = "",
        activator: Callable[[str, str], bool] | None = None,
    ) -> list[str]:
        mode_capability = self.get_mode_capability(mode)
        active_skills = list(mode_capability.skills)
        for skill_id in mode_capability.auto_skills:
            if activator is None or activator(skill_id, content):
                active_skills.append(skill_id)
        return _unique_strings(active_skills)

    def build_capability_set(
        self,
        mode: str,
        *,
        content: str = "",
        active_skills: list[str] | None = None,
        loaded_skills: list[str] | None = None,
        activator: Callable[[str, str], bool] | None = None,
    ) -> CapabilitySet:
        mode_capability = self.get_mode_capability(mode)
        resolved_active_skills = _unique_strings(
            active_skills or self.resolve_active_skills(mode, content=content, activator=activator)
        )
        resolved_loaded_skills = _unique_strings(loaded_skills)
        prompt_ids = list(mode_capability.prompt_ids)
        tools = list(_unique_strings(self._manifest.get("basic_tools")))
        tools.extend(mode_capability.tools)
        mcp_servers = list(mode_capability.mcp_servers)
        skill_ids = list(mode_capability.mode_skill_ids)
        read_only_sources = [
            str(item).strip()
            for item in mode_capability.authorization.get("policy_sources", [])
            if str(item).strip() and mode_capability.authorization.get("read_only")
        ]
        for skill_id in [*resolved_active_skills, *resolved_loaded_skills]:
            skill_capability = self.get_skill_capability(skill_id)
            if skill_capability is None:
                continue
            prompt_ids.extend(skill_capability.prompt_ids)
            tools.extend(skill_capability.tools)
            mcp_servers.extend(skill_capability.mcp_servers)
            skill_ids.append(skill_capability.capability_id)
            if skill_capability.authorization.get("read_only"):
                read_only_sources.extend(skill_capability.authorization.get("policy_sources", []))
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
            tools=_unique_strings(tools),
            mcp_servers=_unique_strings(mcp_servers),
            authorization=authorization,
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
            if tool_checker is not None:
                for tool_name in capability_set.tools:
                    if not tool_checker(tool_name):
                        problems.append(f"tool {tool_name} is not available")
            if mcp_checker is not None:
                for server_name in capability_set.mcp_servers:
                    if not mcp_checker(server_name):
                        problems.append(f"mcp server {server_name} is not available")
        return _unique_strings(problems)
