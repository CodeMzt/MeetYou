from __future__ import annotations

_ACTION_RISK_RANK = {
    "read": 0,
    "local_write": 1,
    "external_write": 2,
    "destructive": 3,
}

_DEFAULT_TOOL_ACTION_RISKS: dict[str, str] = {
    "exec_sys_cmd": "destructive",
    "ask_human": "read",
    "get_current_system_time": "read",
    "get_sys_vitals": "read",
    "get_background_status": "read",
    "remember_knowledge": "local_write",
    "search_memory": "read",
    "manage_memories": "local_write",
    "search_web": "read",
    "read_web_page": "read",
    "research_topic": "read",
    "inspect_page": "read",
    "track_source_updates": "read",
    "search_knowledge": "read",
    "manage_tasks": "local_write",
    "manage_scheduled_tasks": "local_write",
    "list_skills": "read",
    "load_skill": "read",
    "create_skill": "local_write",
    "analyze_workspace": "read",
    "read_local_documents": "read",
    "write_local_document": "local_write",
    "rewrite_local_document": "local_write",
    "compile_report": "read",
    "manage_schedule": "external_write",
    "draft_message": "external_write",
    "meeting_brief": "local_write",
    "sync_notes": "local_write",
    "build_study_plan": "read",
    "extract_learning_points": "read",
    "quiz_me": "read",
    "generate_flashcards": "read",
    "track_mastery": "local_write",
}


class ToolRiskClassifier:
    def __init__(self, action_risks: dict[str, str] | None = None):
        self._tool_action_risks = dict(_DEFAULT_TOOL_ACTION_RISKS)
        self._tool_action_risks.update(action_risks or {})

    def get_tool_action_risk(self, tool_name: str) -> str:
        if tool_name in self._tool_action_risks:
            return self._tool_action_risks[tool_name]
        lowered = str(tool_name or "").lower()
        if any(token in lowered for token in ("delete", "remove", "erase")):
            return "destructive"
        if any(token in lowered for token in ("write", "create", "append", "move", "rename")):
            return "local_write"
        return "read"

    def get_action_risk_for_tools(self, tool_names: list[str] | tuple[str, ...]) -> str:
        highest = "read"
        for tool_name in tool_names:
            risk = self.get_tool_action_risk(tool_name)
            if _ACTION_RISK_RANK.get(risk, 0) > _ACTION_RISK_RANK.get(highest, 0):
                highest = risk
        return highest
