"""
系统工具模块。

提供命令执行（带安全策略）、时间获取、系统指标等功能。
平台抽象层只用于运行宿主机感知；终端命令能力默认通过本地后端承接。
"""

import asyncio
import datetime
import json
import logging
import re

from core.io_protocol import EventTarget, TargetKind
from core.runtime_context import get_event_context

logger = logging.getLogger("meetyou.system_tools")

# 模块级变量，由 App 初始化时注入
_platform_adapter = None
_cmd_policy = None
_event_bus = None
_background_status_provider = None
_heartbeat_settings_provider = None
_heartbeat_settings_updater = None
_temporary_reply_emitter = None
_core_restart_handler = None
_client_tool_dispatcher = None
_allow_local_fallback = True

_DEFAULT_BLACKLIST_PATTERNS = [
    r"(^|[;&|])\s*(rm|del|erase|rd|rmdir|Remove-Item)\b",
    r"(^|[;&|])\s*(shutdown|reboot|halt|poweroff|restart-computer|stop-computer)\b",
    r"\b(format|diskpart|mkfs(?:\.\w+)?|fdisk|parted|dd\s+if=|cipher\s+/w|sdelete)\b",
    r"(^|[;&|])\s*(reg(?:\.exe)?\s+(add|delete|import|load|unload)|regedit)\b",
    r"\b(bcdedit|bootrec|wevtutil\s+cl|vssadmin|wbadmin)\b",
    r"(^|[;&|])\s*(powershell(?:\.exe)?|pwsh)\b.*-(enc|encodedcommand|e)\b",
    r"\b(Invoke-Expression|iex|Set-ExecutionPolicy|Start-Process)\b",
    r"\b(curl|wget|Invoke-WebRequest|iwr)\b.*(\||&&|;).*\b(sh|bash|zsh|powershell|pwsh|cmd)(?:\.exe)?\b",
    r"(^|[;&|])\s*(net\s+(user|localgroup)|sc(?:\.exe)?\s+(config|create|delete|stop|start)|schtasks|crontab)\b",
    r"(^|[;&|])\s*(systemctl\s+(stop|disable|mask|reboot|poweroff)|service\s+\S+\s+(stop|restart))\b",
    r"(^|[;&|])\s*(taskkill|Stop-Process|pkill|killall|kill\s+-9)\b",
    r"\b(chmod\s+777|chown|takeown|icacls|attrib\s+[+-][rhs])\b",
    r"\b(netsh\b.*\badvfirewall\b|iptables|ufw|route\s+(add|delete|change))\b",
    r"\bgit\s+(reset\s+--hard|clean\s+-fdx|checkout\s+--)\b",
    r"\b(docker\s+(rm|rmi|system\s+prune|volume\s+rm)|kubectl\s+delete)\b",
]


def init_system_tools(
    platform_adapter,
    event_bus,
    cmd_policy_path: str = "user/cmd_policy.json",
    allow_local_fallback: bool = True,
):
    """
    初始化系统工具模块。

    Args:
        platform_adapter: PlatformAdapter 实例
        event_bus: EventBus 实例（用于危险命令确认）
        cmd_policy_path: 命令安全策略文件路径
    """
    global _platform_adapter, _cmd_policy, _event_bus, _allow_local_fallback
    _platform_adapter = platform_adapter
    _event_bus = event_bus
    _allow_local_fallback = bool(allow_local_fallback)

    try:
        with open(cmd_policy_path, "r", encoding="utf-8") as f:
            _cmd_policy = json.load(f)
        logger.info(f"命令安全策略已加载: {cmd_policy_path}")
    except FileNotFoundError:
        logger.warning(f"命令安全策略文件不存在: {cmd_policy_path}，使用默认（全部允许）")
        _cmd_policy = {"mode": "none"}
    except json.JSONDecodeError as e:
        logger.error(f"命令安全策略格式错误: {e}")
        _cmd_policy = {"mode": "none"}


def set_background_status_provider(provider):
    global _background_status_provider
    _background_status_provider = provider


def set_heartbeat_settings_provider(provider):
    global _heartbeat_settings_provider
    _heartbeat_settings_provider = provider


def set_heartbeat_settings_updater(updater):
    global _heartbeat_settings_updater
    _heartbeat_settings_updater = updater


def set_temporary_reply_emitter(emitter):
    global _temporary_reply_emitter
    _temporary_reply_emitter = emitter


def set_core_restart_handler(handler):
    global _core_restart_handler
    _core_restart_handler = handler


def set_client_tool_dispatcher(dispatcher):
    global _client_tool_dispatcher
    _client_tool_dispatcher = dispatcher


def set_capability_dispatcher(dispatcher):
    set_client_tool_dispatcher(dispatcher)


def set_local_fallback_enabled(enabled: bool):
    global _allow_local_fallback
    _allow_local_fallback = bool(enabled)


def _check_command_safety(cmd: str) -> tuple[str, str]:
    """
    检查命令安全状态。

    Returns:
        (status, reason) — status 为 "safe" / "blocked" / "needs_confirm"
    """
    if _cmd_policy is None or _cmd_policy.get("mode") == "none":
        return "safe", ""

    mode = _cmd_policy.get("mode", "blacklist")
    normalized_cmd = re.sub(r"\s+", " ", cmd.strip())
    cmd_lower = normalized_cmd.lower()

    if mode == "whitelist":
        whitelist = _cmd_policy.get("whitelist", [])
        for allowed in whitelist:
            if cmd_lower.startswith(str(allowed).strip().lower()):
                return "safe", ""
        return "blocked", f"命令不在白名单中: {cmd}"

    elif mode == "blacklist":
        configured_patterns = _cmd_policy.get("blacklist_patterns", [])
        blacklist: list[str] = []
        seen: set[str] = set()
        for pattern in [*_DEFAULT_BLACKLIST_PATTERNS, *configured_patterns]:
            pattern = str(pattern).strip()
            if not pattern or pattern in seen:
                continue
            seen.add(pattern)
            blacklist.append(pattern)

        for pattern in blacklist:
            try:
                if re.search(pattern, cmd, re.IGNORECASE) or re.search(
                    pattern,
                    normalized_cmd,
                    re.IGNORECASE,
                ):
                    return "needs_confirm", f"匹配危险规则: {pattern}"
            except re.error:
                if pattern.lower() in cmd_lower:
                    return "needs_confirm", f"匹配危险关键词: {pattern}"

    return "safe", ""


def assess_command_safety(cmd: str) -> dict[str, str]:
    status, reason = _check_command_safety(cmd)
    return {
        "status": status,
        "reason": reason,
    }


def _decode_local_shell_output(raw_bytes: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


async def exec_sys_cmd(cmd: str, session_id: str = "", source=None, confirmed: bool = False) -> str:
    """
    安全执行系统命令。

    - 白名单之外的命令直接拦截
    - 黑名单命令弹出确认，用户同意后才执行
    - 其他命令正常执行

    Args:
        cmd: 终端命令

    Returns:
        str: 执行结果或拦截信息
    """
    status, reason = _check_command_safety(cmd)

    if status == "blocked":
        logger.warning(f"命令被拦截: {cmd} | {reason}")
        return f"[安全策略拦截] {reason}"

    if status == "needs_confirm" and not confirmed:
        if _event_bus is None:
            logger.warning(f"危险命令无法确认（EventBus 未注入），默认拒绝: {cmd}")
            return f"[安全策略] 危险命令已拦截（{reason}）"

        confirmed = await _event_bus.request_confirmation(
            f"请求执行危险命令: {cmd}\n"
            f"原因: {reason}\n"
            f"输入 y 确认执行，其他任意输入取消（{30}秒超时自动拒绝）",
            timeout=30.0,
            session_id=session_id or "system:confirm",
            source=source,
            target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
        )
        if not confirmed:
            logger.info(f"用户拒绝执行危险命令: {cmd}")
            return f"[用户已拒绝] 命令未执行: {cmd}"
        logger.info(f"用户确认执行危险命令: {cmd}")

    if _client_tool_dispatcher is not None:
        dispatch = getattr(_client_tool_dispatcher, "dispatch_directed_tool", None)
        if not callable(dispatch):
            dispatch = getattr(_client_tool_dispatcher, "dispatch_workspace_tool", None)
        if not callable(dispatch):
            raise RuntimeError("Client tool dispatcher does not support directed tool dispatch")
        result = await dispatch(
            tool_key="shell.exec",
            arguments={"command": cmd},
            session_id=session_id,
            title=f"Shell Command: {cmd[:48]}",
            operation_type="tool.exec_sys_cmd",
        )
        return str(result.get("stdout") or result.get("summary") or "")

    if not _allow_local_fallback:
        error = RuntimeError("Core local fallback is disabled")
        error.tool_error_code = "local_client_required"
        error.tool_error_message = "当前 Core 不再直接执行本地命令，请连接具备 shell.exec 的 Desktop Client 后重试。"
        error.tool_error_details = {
            "tool_key": "shell.exec",
            "session_id": str(session_id or ""),
            "command": str(cmd or ""),
        }
        error.tool_error_retryable = False
        raise error

    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode == 0:
        return _decode_local_shell_output(stdout).strip()
    else:
        return f"命令执行失败，错误信息：{_decode_local_shell_output(stderr).strip()}"


async def ask_human(
    question: str,
    options: list[str] | None = None,
    placeholder: str = "",
    timeout_seconds: int = 60,
    session_id: str = "",
    source=None,
) -> str:
    payload = {
        "answered": False,
        "timed_out": False,
        "selected_option": None,
        "answer_text": "",
        "request_id": "",
    }
    if _event_bus is None:
        logger.warning("Human input requested without EventBus: %s", question)
        return json.dumps(payload, ensure_ascii=False)

    result = await _event_bus.request_human_input(
        str(question or "").strip(),
        options=options or [],
        placeholder=str(placeholder or "").strip(),
        timeout=float(timeout_seconds or 60),
        session_id=session_id or "system:human_input",
        source=source,
        target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
    )
    payload.update(dict(result or {}))
    return json.dumps(payload, ensure_ascii=False)


async def request_user_confirmation(
    prompt: str,
    *,
    session_id: str = "",
    source=None,
    timeout_seconds: int = 30,
    metadata: dict | None = None,
) -> bool:
    if _event_bus is None:
        return False
    return await _event_bus.request_confirmation(
        str(prompt or "").strip(),
        timeout=float(timeout_seconds or 30),
        session_id=session_id or "system:confirm",
        source=source,
        target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
        metadata=dict(metadata or {}),
    )


async def get_current_system_time() -> str:
    """获取当前系统时间"""
    local_now = datetime.datetime.now().astimezone()
    utc_now = local_now.astimezone(datetime.timezone.utc)
    return (
        "当前宿主机系统时间："
        f"{local_now.strftime('%Y-%m-%d %H:%M:%S %A')} "
        f"(时区 {local_now.tzname() or 'UTC'})；"
        f"UTC 时间：{utc_now.replace(microsecond=0).isoformat().replace('+00:00', 'Z')}"
    )


async def get_sys_vitals() -> str:
    """获取 Core 运行宿主机的系统生命体征"""
    if _platform_adapter is None:
        return "平台适配器未初始化"

    vitals = _platform_adapter.get_system_vitals()
    parts = [
        f"CPU占用：{vitals.get('cpu_percent', 'N/A')}%",
        f"内存占用：{vitals.get('ram_percent', 'N/A')}%",
    ]
    if "battery_percent" in vitals:
        parts.append(f"电池电量：{vitals['battery_percent']}%")
        parts.append(f"是否充电：{vitals.get('is_plugged', 'N/A')}")

    return "  ".join(parts)


async def get_background_status() -> str:
    payload = {}
    provider = _background_status_provider
    if provider is not None:
        try:
            provided = provider()
            if asyncio.iscoroutine(provided):
                provided = await provided
            if isinstance(provided, dict):
                payload.update(provided)
        except Exception as exc:
            payload["provider_error"] = str(exc)

    if _platform_adapter is not None:
        try:
            payload["system_vitals"] = _platform_adapter.get_system_vitals()
        except Exception as exc:
            payload["system_vitals_error"] = str(exc)
        describe_capabilities = getattr(_platform_adapter, "describe_capabilities", None)
        if callable(describe_capabilities):
            try:
                payload["platform_capabilities"] = describe_capabilities()
            except Exception as exc:
                payload["platform_capabilities_error"] = str(exc)
        payload["platform_adapter"] = type(_platform_adapter).__name__

    payload["current_time"] = (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def manage_heartbeat_settings(action: str = "get", updates: dict | None = None) -> str:
    normalized_action = str(action or "get").strip().lower()
    if normalized_action not in {"get", "update"}:
        return json.dumps(
            {"ok": False, "error": "action must be get or update"},
            ensure_ascii=False,
            indent=2,
        )

    allowed = {
        "heartbeat_idle_poke_enabled",
        "heartbeat_idle_poke_after_seconds",
        "heartbeat_idle_poke_cooldown_seconds",
        "heartbeat_idle_context_compaction_enabled",
    }

    if normalized_action == "get":
        provider = _heartbeat_settings_provider
        payload = provider() if provider is not None else {}
        if asyncio.iscoroutine(payload):
            payload = await payload
        return json.dumps({"ok": True, **(payload if isinstance(payload, dict) else {})}, ensure_ascii=False, indent=2)

    requested = dict(updates or {})
    sanitized = {key: value for key, value in requested.items() if key in allowed}
    rejected = sorted(str(key) for key in requested if key not in allowed)
    updater = _heartbeat_settings_updater
    if updater is None:
        return json.dumps(
            {"ok": False, "error": "heartbeat settings updater is not available", "rejected_keys": rejected},
            ensure_ascii=False,
            indent=2,
        )
    result = updater(sanitized)
    if asyncio.iscoroutine(result):
        result = await result
    return json.dumps(
        {"ok": True, "requested_keys": sorted(sanitized), "rejected_keys": rejected, "result": result or {}},
        ensure_ascii=False,
        indent=2,
    )


async def emit_short_reply(content: str, session_id: str = "", source=None) -> str:
    text = re.sub(r"\s+", " ", str(content or "").strip())
    if not text:
        return json.dumps({"ok": False, "error": "content is required"}, ensure_ascii=False, indent=2)
    if len(text) > 120:
        text = text[:117].rstrip() + "..."

    emitter = _temporary_reply_emitter
    if emitter is None:
        return json.dumps(
            {"ok": False, "error": "temporary reply emitter is not available"},
            ensure_ascii=False,
            indent=2,
        )

    context = get_event_context()
    resolved_session_id = str(session_id or context.get("session_id") or "").strip()
    result = emitter(
        text,
        session_id=resolved_session_id,
        source=source if source is not None else context.get("source"),
        turn_id=str(context.get("turn_id") or "").strip(),
    )
    if asyncio.iscoroutine(result):
        result = await result
    payload = dict(result or {})
    payload.setdefault("ok", bool(payload.get("delivered")))
    payload.setdefault("content", text)
    payload.setdefault("session_id", resolved_session_id)
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def emit_temporary_reply(content: str, session_id: str = "", source=None) -> str:
    return await emit_short_reply(content, session_id=session_id, source=source)


async def restart_core(password: str, reason: str = "", delay_seconds: int = 1, session_id: str = "", source=None) -> str:
    handler = _core_restart_handler
    if handler is None:
        return json.dumps(
            {"ok": False, "accepted": False, "reason": "restart handler is not available"},
            ensure_ascii=False,
            indent=2,
        )
    context = get_event_context()
    resolved_session_id = str(session_id or context.get("session_id") or "").strip()
    result = handler(
        str(password or ""),
        reason=str(reason or ""),
        delay_seconds=int(delay_seconds or 0),
        session_id=resolved_session_id,
        source=source if source is not None else context.get("source"),
    )
    if asyncio.iscoroutine(result):
        result = await result
    payload = dict(result or {})
    payload.setdefault("ok", bool(payload.get("accepted")))
    payload.setdefault("session_id", resolved_session_id)
    return json.dumps(payload, ensure_ascii=False, indent=2)
