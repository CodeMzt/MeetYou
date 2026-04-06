from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AuthorizationDecision:
    tool_name: str
    action_risk: str
    allowed: bool
    visibility: str
    requires_confirmation: bool = False
    confirmation_kind: str = ""
    write_boundary: str = "not_applicable"
    write_path: str = ""
    trusted_root: bool | None = None
    read_only: bool = False
    policy_sources: list[str] = field(default_factory=list)
    reason_code: str = ""
    reason_message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "allowed": self.allowed,
            "visibility": self.visibility,
            "action_risk": self.action_risk,
            "read_only": self.read_only,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_kind": self.confirmation_kind,
            "write_boundary": self.write_boundary,
            "write_path": self.write_path,
            "trusted_root": self.trusted_root,
            "policy_sources": list(self.policy_sources),
            "reason_code": self.reason_code,
            "reason_message": self.reason_message,
            "details": dict(self.details),
            "side_effect_audit": {
                "tool_name": self.tool_name,
                "action_risk": self.action_risk,
                "allowed": self.allowed,
                "visibility": self.visibility,
                "read_only": self.read_only,
                "requires_confirmation": self.requires_confirmation,
                "confirmation_kind": self.confirmation_kind,
                "write_boundary": self.write_boundary,
                "write_path": self.write_path,
                "trusted_root": self.trusted_root,
                "policy_sources": list(self.policy_sources),
            },
        }


class ToolAuthorizationGateway:
    def __init__(
        self,
        permission_policy,
        risk_classifier,
        *,
        mode_manager=None,
        command_safety_checker=None,
    ) -> None:
        self._permission_policy = permission_policy
        self._risk_classifier = risk_classifier
        self._mode_manager = mode_manager
        self._command_safety_checker = command_safety_checker

    def should_expose_tool(self, tool_name: str, *, route_context: dict[str, Any] | None = None) -> bool:
        decision = self.decide(tool_name, {}, route_context=route_context)
        return decision.allowed

    def decide(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None,
        *,
        route_context: dict[str, Any] | None = None,
    ) -> AuthorizationDecision:
        route_context = route_context or {}
        normalized_tool_args = dict(tool_args or {})
        action_risk = self._risk_classifier.get_tool_action_risk(tool_name)
        auth_policy = self._resolve_authorization_policy(route_context)
        policy_sources = [
            str(item).strip()
            for item in auth_policy.get("policy_sources", [])
            if str(item).strip()
        ]
        read_only = bool(auth_policy.get("read_only", False))

        if not self._permission_policy.is_tool_allowed(tool_name, route_context=route_context):
            return AuthorizationDecision(
                tool_name=tool_name,
                action_risk=action_risk,
                allowed=False,
                visibility="denied_by_route",
                read_only=read_only,
                policy_sources=policy_sources,
                reason_code="tool_not_allowed",
                reason_message="Tool call was denied by the current route policy.",
                details={
                    "tool_name": tool_name,
                    "current_mode": route_context.get("current_mode"),
                    "tool_bundle": list(route_context.get("tool_bundle", [])),
                    "mcp_servers": list(route_context.get("mcp_servers", [])),
                },
            )

        if read_only and action_risk != "read":
            return AuthorizationDecision(
                tool_name=tool_name,
                action_risk=action_risk,
                allowed=False,
                visibility="visible",
                read_only=True,
                policy_sources=policy_sources,
                reason_code="tool_readonly_violation",
                reason_message="Tool call was denied because the current mode or skill is read-only.",
                details={
                    "tool_name": tool_name,
                    "current_mode": route_context.get("current_mode"),
                    "action_risk": action_risk,
                    "policy_sources": policy_sources,
                },
            )

        command_decision = self._decide_command(tool_name, normalized_tool_args, action_risk, read_only, policy_sources)
        if command_decision is not None:
            return command_decision

        write_decision = self._decide_write_boundary(
            tool_name,
            normalized_tool_args,
            action_risk,
            read_only,
            policy_sources,
        )
        if write_decision is not None:
            return write_decision

        return AuthorizationDecision(
            tool_name=tool_name,
            action_risk=action_risk,
            allowed=True,
            visibility="visible",
            read_only=read_only,
            policy_sources=policy_sources,
        )

    @staticmethod
    def _resolve_authorization_policy(route_context: dict[str, Any]) -> dict[str, Any]:
        if isinstance(route_context.get("authorization_policy"), dict):
            return dict(route_context.get("authorization_policy") or {})
        capability_set = route_context.get("capability_set")
        if isinstance(capability_set, dict) and isinstance(capability_set.get("authorization"), dict):
            return dict(capability_set.get("authorization") or {})
        return {}

    def _decide_command(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        action_risk: str,
        read_only: bool,
        policy_sources: list[str],
    ) -> AuthorizationDecision | None:
        if tool_name != "exec_sys_cmd" or not callable(self._command_safety_checker):
            return None
        assessment = dict(self._command_safety_checker(str(tool_args.get("cmd") or "")) or {})
        status = str(assessment.get("status") or "safe").strip().lower()
        reason = str(assessment.get("reason") or "").strip()
        confirmed = bool(tool_args.get("confirmed", False))
        details = {
            "tool_name": tool_name,
            "command": str(tool_args.get("cmd") or ""),
            "policy_status": status,
            "policy_reason": reason,
        }
        if status == "blocked":
            return AuthorizationDecision(
                tool_name=tool_name,
                action_risk=action_risk,
                allowed=False,
                visibility="visible",
                read_only=read_only,
                policy_sources=policy_sources,
                reason_code="tool_command_blocked",
                reason_message="Tool call was blocked by the command safety policy.",
                details=details,
            )
        if status == "needs_confirm" and not confirmed:
            return AuthorizationDecision(
                tool_name=tool_name,
                action_risk=action_risk,
                allowed=False,
                visibility="visible",
                requires_confirmation=True,
                confirmation_kind="command_policy",
                read_only=read_only,
                policy_sources=policy_sources,
                reason_code="tool_confirmation_required",
                reason_message="Tool call requires explicit confirmation before executing a risky command.",
                details=details,
            )
        return AuthorizationDecision(
            tool_name=tool_name,
            action_risk=action_risk,
            allowed=True,
            visibility="visible",
            read_only=read_only,
            requires_confirmation=status == "needs_confirm",
            confirmation_kind="command_policy" if status == "needs_confirm" else "",
            policy_sources=policy_sources,
            details=details if status != "safe" else {},
        )

    def _decide_write_boundary(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        action_risk: str,
        read_only: bool,
        policy_sources: list[str],
    ) -> AuthorizationDecision | None:
        if tool_name not in {"write_local_document", "rewrite_local_document"}:
            return None
        path_value = str(tool_args.get("path") or "").strip()
        preview = bool(tool_args.get("preview", True))
        confirmed = bool(tool_args.get("confirmed", False))
        resolved_path = self._normalize_path(path_value)
        trusted_root = self._is_trusted_write_path(resolved_path)
        write_boundary = "preview" if preview else "trusted_root" if trusted_root else "untrusted_path"
        details = {
            "tool_name": tool_name,
            "path": resolved_path,
            "preview": preview,
            "confirmed": confirmed,
            "trusted_root": trusted_root,
        }
        if not preview and not confirmed:
            return AuthorizationDecision(
                tool_name=tool_name,
                action_risk=action_risk,
                allowed=False,
                visibility="visible",
                requires_confirmation=True,
                confirmation_kind="document_write",
                write_boundary=write_boundary,
                write_path=resolved_path,
                trusted_root=trusted_root,
                read_only=read_only,
                policy_sources=policy_sources,
                reason_code="tool_confirmation_required",
                reason_message="Tool call requires explicit confirmation before writing a local document.",
                details=details,
            )
        if not preview and not trusted_root:
            trusted_roots = []
            if self._mode_manager is not None and hasattr(self._mode_manager, "get_trusted_write_roots"):
                trusted_roots = list(self._mode_manager.get_trusted_write_roots())
            details["trusted_write_roots"] = trusted_roots
            return AuthorizationDecision(
                tool_name=tool_name,
                action_risk=action_risk,
                allowed=False,
                visibility="visible",
                write_boundary=write_boundary,
                write_path=resolved_path,
                trusted_root=trusted_root,
                read_only=read_only,
                policy_sources=policy_sources,
                reason_code="tool_write_boundary_violation",
                reason_message="Tool call was denied because the write target is outside trusted roots.",
                details=details,
            )
        return AuthorizationDecision(
            tool_name=tool_name,
            action_risk=action_risk,
            allowed=True,
            visibility="visible",
            read_only=read_only,
            requires_confirmation=not preview,
            confirmation_kind="document_write" if not preview else "",
            write_boundary=write_boundary,
            write_path=resolved_path,
            trusted_root=trusted_root,
            policy_sources=policy_sources,
            details=details if path_value else {},
        )

    @staticmethod
    def _normalize_path(path_value: str) -> str:
        if not path_value:
            return ""
        try:
            return str(Path(path_value).expanduser().resolve())
        except Exception:
            return path_value

    def _is_trusted_write_path(self, path_value: str) -> bool:
        if not path_value or self._mode_manager is None:
            return False
        checker = getattr(self._mode_manager, "is_trusted_write_path", None)
        if callable(checker):
            try:
                return bool(checker(path_value))
            except Exception:
                return False
        return False
