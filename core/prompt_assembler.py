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

    def _build_skill_first_policy(self, capability_set) -> str:
        policy_lines = ["[Skill-First Policy]"]
        active_or_loaded = _unique_strings([*capability_set.active_skills, *capability_set.loaded_skills])
        if active_or_loaded:
            policy_lines.append(
                f"Treat these skills as the primary operating procedure first: {', '.join(active_or_loaded)}."
            )
            policy_lines.append(
                "Use business tools under those skills instead of bypassing them with ad-hoc tool calls."
            )
        else:
            policy_lines.append(
                "Before using non-skill business tools for a multi-step or specialized workflow, first check whether an existing skill fits."
            )
            policy_lines.append(
                "Use list_skills to inspect relevant reusable skills, then use load_skill before continuing when a matching skill exists."
            )
        policy_lines.append(
            "Use direct tools immediately only when the task is obviously simple, one-step, or no skill would improve the workflow."
        )
        return "\n".join(policy_lines)

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
        prompt_sections.append(self._build_skill_first_policy(capability_set))
        plan_lines: list[str] = ["[Capability Plan]"]
        if capability_set.scene_ids:
            plan_lines.append(f"Scenes: {', '.join(capability_set.scene_ids)}")
        if capability_set.skill_activations:
            skill_bits = []
            for item in capability_set.skill_activations:
                skill_id = str(item.get("skill_id") or "").strip()
                reason = str(item.get("reason") or "").strip()
                if not skill_id:
                    continue
                skill_bits.append(f"{skill_id} ({reason})" if reason else skill_id)
            if skill_bits:
                plan_lines.append(f"Skills: {'; '.join(skill_bits)}")
        preferred_servers = [
            item["server_name"]
            for item in capability_set.mcp_diagnostics
            if item.get("usable")
        ]
        degraded_servers = [
            f"{item['server_name']} -> {', '.join(item.get('fallback_tools') or [])}"
            for item in capability_set.mcp_diagnostics
            if item.get("degraded")
        ]
        if preferred_servers:
            plan_lines.append(f"Preferred MCP: {', '.join(preferred_servers)}")
        if degraded_servers:
            plan_lines.append(f"Fallbacks: {'; '.join(degraded_servers)}")
        if len(plan_lines) > 1:
            prompt_sections.append("\n".join(plan_lines))
        return "\n\n".join(prompt_sections).strip()

    def assemble_for_route(self, route_context: dict[str, Any] | None) -> str:
        route_context = route_context or {}
        return self.assemble_for_mode(
            str(route_context.get("current_mode") or "").strip() or "normal",
            content=str(route_context.get("content") or "").strip(),
            active_skills=[str(item).strip() for item in route_context.get("active_skills", []) if str(item).strip()],
            loaded_skills=[str(item).strip() for item in route_context.get("loaded_skills", []) if str(item).strip()],
        )
