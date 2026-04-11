"""
Office and coordination helper tools.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from tools.document_tools import DocumentTools, _dedupe_keep_order, _normalize_text, _trim_text


def _utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item).strip() for item in (value or []) if str(item).strip()]


class OfficeTools:
    def __init__(self, mode_manager, document_tools: DocumentTools, state_backend=None):
        self._mode_manager = mode_manager
        self._document_tools = document_tools
        self._state_path = Path("user/office_state.json")
        self._state_backend = state_backend

    def set_state_backend(self, backend) -> None:
        self._state_backend = backend

    def _load_state(self) -> dict[str, Any]:
        if self._state_backend is not None:
            payload = self._state_backend.load()
            if isinstance(payload, dict) and payload:
                return payload
        if not self._state_path.exists():
            return {"schedules": [], "message_drafts": [], "synced_notes": []}
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            if self._state_backend is not None:
                self._state_backend.save(payload)
            return payload
        except Exception:
            return {"schedules": [], "message_drafts": [], "synced_notes": []}

    def _save_state(self, state: dict[str, Any]) -> None:
        if self._state_backend is not None:
            self._state_backend.save(state)
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _integration_status(self, source_system: str) -> dict[str, Any]:
        integrations = self._mode_manager.get_office_integrations()
        payload = integrations.get(source_system) or {"enabled": False, "draft_only": True}
        return {
            "source_system": source_system,
            "enabled": bool(payload.get("enabled", False)),
            "draft_only": bool(payload.get("draft_only", True)),
        }

    async def manage_schedule(
        self,
        action: str,
        when: str = "",
        attendees: list[str] | str | None = None,
        source_system: str = "local",
        title: str = "",
        details: str = "",
        confirmed: bool = False,
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> str:
        del session_id, source, route_context, activity_callback
        normalized_action = str(action or "").strip().lower()
        integration = self._integration_status(str(source_system or "local").strip().lower() or "local")
        state = self._load_state()

        if normalized_action == "list":
            payload = {
                "tool": "manage_schedule",
                "action": "list",
                "source_system": integration["source_system"],
                "items": state.get("schedules", [])[-10:],
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)

        schedule_entry = {
            "schedule_id": f"sch_{uuid4().hex[:10]}",
            "title": _normalize_text(title) or "Untitled schedule item",
            "when": _normalize_text(when),
            "attendees": _safe_list(attendees),
            "details": _normalize_text(details),
            "source_system": integration["source_system"],
            "created_at": _utcnow_iso(),
        }

        if normalized_action not in {"draft", "create"}:
            return json.dumps(
                {
                    "tool": "manage_schedule",
                    "status": "invalid_action",
                    "allowed_actions": ["draft", "create", "list"],
                },
                ensure_ascii=False,
                indent=2,
            )

        if normalized_action == "draft" or integration["draft_only"] or (integration["source_system"] != "local" and not confirmed):
            schedule_entry["status"] = "draft" if normalized_action == "draft" else "requires_confirmation"
            state.setdefault("schedules", []).append(schedule_entry)
            self._save_state(state)
            return json.dumps(
                {
                    "tool": "manage_schedule",
                    "action": normalized_action,
                    "status": schedule_entry["status"],
                    "action_risk": "external_write" if integration["source_system"] != "local" else "local_write",
                    "integration": integration,
                    "schedule": schedule_entry,
                    "answer_style": "Present this as a draft or pending calendar action unless the tool explicitly confirms creation.",
                },
                ensure_ascii=False,
                indent=2,
            )

        schedule_entry["status"] = "created"
        state.setdefault("schedules", []).append(schedule_entry)
        self._save_state(state)
        return json.dumps(
            {
                "tool": "manage_schedule",
                "action": normalized_action,
                "status": "created",
                "action_risk": "local_write",
                "integration": integration,
                "schedule": schedule_entry,
            },
            ensure_ascii=False,
            indent=2,
        )

    async def draft_message(
        self,
        channel: str,
        recipients: list[str] | str,
        goal: str,
        tone: str = "clear",
        subject: str = "",
        context_notes: str = "",
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> str:
        del session_id, source, route_context, activity_callback
        normalized_channel = _normalize_text(channel) or "general"
        recipient_list = _safe_list(recipients)
        normalized_goal = _normalize_text(goal)
        normalized_tone = _normalize_text(tone) or "clear"
        normalized_subject = _normalize_text(subject) or f"{normalized_channel.title()} follow-up"
        outline = [
            f"Open with the purpose: {normalized_goal or 'state the requested purpose clearly'}.",
            "Share the key context in 1-3 concise points.",
            "State the specific ask, next step, or decision needed.",
            "Close with ownership, timing, or a reply request if appropriate.",
        ]
        draft = {
            "subject": normalized_subject,
            "opening_hint": f"Write in a {normalized_tone} tone and address {', '.join(recipient_list) or 'the recipient'} directly.",
            "body_outline": outline,
            "goal": normalized_goal,
            "context_notes": _trim_text(context_notes, 800),
        }

        state = self._load_state()
        state.setdefault("message_drafts", []).append(
            {
                "draft_id": f"msg_{uuid4().hex[:10]}",
                "channel": normalized_channel,
                "recipients": recipient_list,
                "goal": normalized_goal,
                "tone": normalized_tone,
                "subject": normalized_subject,
                "created_at": _utcnow_iso(),
            }
        )
        self._save_state(state)

        return json.dumps(
            {
                "tool": "draft_message",
                "status": "draft_ready",
                "action_risk": "external_write",
                "channel": normalized_channel,
                "recipients": recipient_list,
                "draft": draft,
                "answer_style": "Write the actual message as a draft. Do not claim it has been sent.",
            },
            ensure_ascii=False,
            indent=2,
        )

    def _read_notes_input(self, notes: str) -> str:
        raw = str(notes or "").strip()
        if not raw:
            return ""
        note_path = Path(raw).expanduser()
        if note_path.exists() and note_path.is_file():
            collected = self._document_tools._collect_document(note_path.resolve(), goal="meeting brief", chunking="auto")
            return str(collected.get("content_excerpt") or "")
        return raw

    async def meeting_brief(
        self,
        notes: str,
        title: str = "",
        attendees: list[str] | str | None = None,
        output_path: str = "",
        preview: bool = True,
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> str:
        del session_id, source, route_context, activity_callback
        text = self._read_notes_input(notes)
        sentences = [
            item.strip(" -")
            for item in re.split(r"[\n\r]+|(?<=[.!?。！？])\s+", text)
            if item.strip()
        ]

        decisions = [sentence for sentence in sentences if any(token in sentence.lower() for token in ("decide", "decision", "approved", "agree"))]
        action_items = [
            sentence for sentence in sentences
            if any(token in sentence.lower() for token in ("todo", "action", "follow up", "owner", "next step", "负责", "跟进"))
        ]
        risks = [sentence for sentence in sentences if any(token in sentence.lower() for token in ("risk", "blocker", "issue", "problem", "阻塞", "风险"))]
        attendees_list = _safe_list(attendees)
        normalized_title = _normalize_text(title) or "Meeting Brief"
        overview = _trim_text(" ".join(sentences[:4]), 500)

        markdown = "\n".join(
            [
                f"# {normalized_title}",
                "",
                f"- Attendees: {', '.join(attendees_list) if attendees_list else 'Not specified'}",
                f"- Overview: {overview or 'No overview extracted.'}",
                "",
                "## Decisions",
                *([f"- {item}" for item in decisions[:8]] or ["- None extracted"]),
                "",
                "## Action Items",
                *([f"- {item}" for item in action_items[:8]] or ["- None extracted"]),
                "",
                "## Risks",
                *([f"- {item}" for item in risks[:6]] or ["- None extracted"]),
                "",
            ]
        ).strip() + "\n"

        payload = {
            "tool": "meeting_brief",
            "status": "ready",
            "title": normalized_title,
            "attendees": attendees_list,
            "overview": overview,
            "decisions": decisions[:8],
            "action_items": action_items[:8],
            "risks": risks[:6],
            "brief_markdown": markdown,
        }

        if output_path:
            write_result = await self._document_tools.write_local_document(
                output_path,
                markdown,
                mode="overwrite",
                preview=preview,
            )
            payload["write_result"] = json.loads(write_result)

        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def sync_notes(
        self,
        source_paths: list[str] | str,
        target_path: str = "",
        source_system: str = "local",
        preview: bool = True,
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> str:
        del session_id, source, route_context, activity_callback
        normalized_source_system = str(source_system or "local").strip().lower() or "local"
        paths = [source_paths] if isinstance(source_paths, str) else list(source_paths or [])

        if normalized_source_system != "local":
            return json.dumps(
                {
                    "tool": "sync_notes",
                    "status": "draft_plan_only",
                    "source_system": normalized_source_system,
                    "action_risk": "external_write",
                    "answer_style": "Explain the sync plan and ask for a confirmed integration step before claiming success.",
                },
                ensure_ascii=False,
                indent=2,
            )

        documents_raw = await self._document_tools.read_local_documents(paths, goal="sync notes", chunking="auto")
        documents_payload = json.loads(documents_raw)
        sections: list[str] = []
        synced_paths: list[str] = []
        for document in documents_payload.get("documents", []):
            if document.get("status") != "ok":
                continue
            synced_paths.append(str(document.get("path") or ""))
            sections.extend(
                [
                    f"## {document.get('name') or Path(document.get('path', '')).name}",
                    str(document.get("content_excerpt") or ""),
                    "",
                ]
            )

        merged_markdown = "\n".join(["# Synced Notes", "", *sections]).strip() + "\n"
        state = self._load_state()
        sync_record = {
            "sync_id": f"sync_{uuid4().hex[:10]}",
            "source_paths": _dedupe_keep_order(synced_paths),
            "target_path": _normalize_text(target_path),
            "created_at": _utcnow_iso(),
        }
        state.setdefault("synced_notes", []).append(sync_record)
        self._save_state(state)

        payload = {
            "tool": "sync_notes",
            "status": "ready",
            "source_system": normalized_source_system,
            "action_risk": "local_write",
            "merged_markdown": merged_markdown,
            "documents": documents_payload.get("documents", []),
            "sync_record": sync_record,
        }
        if target_path:
            payload["write_result"] = json.loads(
                await self._document_tools.write_local_document(
                    target_path,
                    merged_markdown,
                    mode="overwrite",
                    preview=preview,
                )
            )
        return json.dumps(payload, ensure_ascii=False, indent=2)
