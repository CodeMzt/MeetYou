from __future__ import annotations

from typing import Any

from core.capability_registry import CapabilityRegistry


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


class PromptAssembler:
    def __init__(self, capability_registry: CapabilityRegistry) -> None:
        self._capability_registry = capability_registry

    def assemble_for_mode(
        self,
        mode: str,
        *,
        content: str = "",
        active_skills: list[str] | None = None,
        loaded_skills: list[str] | None = None,
    ) -> str:
        capability_set = self._capability_registry.build_capability_set(
            mode,
            content=content,
            active_skills=active_skills,
            loaded_skills=loaded_skills,
        )
        prompt_sections: list[str] = []
        for prompt_id in capability_set.prompt_ids:
            prompt_text = self._capability_registry.get_prompt_text(prompt_id)
            if prompt_text and prompt_text not in prompt_sections:
                prompt_sections.append(prompt_text)
        for skill_id in _unique_strings(
            [*capability_set.mode_skill_ids, *capability_set.active_skills, *capability_set.loaded_skills]
        ):
            skill_capability = self._capability_registry.get_skill_capability(skill_id)
            skill_content = str((skill_capability.content if skill_capability is not None else "") or "").strip()
            if skill_content and skill_content not in prompt_sections:
                prompt_sections.append(skill_content)
        return "\n\n".join(prompt_sections).strip()

    def assemble_for_route(self, route_context: dict[str, Any] | None) -> str:
        route_context = route_context or {}
        return self.assemble_for_mode(
            str(route_context.get("current_mode") or "").strip() or "normal",
            content=str(route_context.get("content") or "").strip(),
            active_skills=[str(item).strip() for item in route_context.get("active_skills", []) if str(item).strip()],
            loaded_skills=[str(item).strip() for item in route_context.get("loaded_skills", []) if str(item).strip()],
        )
