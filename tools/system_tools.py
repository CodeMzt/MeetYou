"""
系统工具模块。

提供命令执行（带安全策略）、时间获取、系统指标等功能。
使用平台抽象层实现跨平台兼容。
"""

import asyncio
import datetime
import json
import logging
import re

from core.io_protocol import EventTarget, TargetKind

logger = logging.getLogger("meetyou.system_tools")

# 模块级变量，由 App 初始化时注入
_platform_adapter = None
_cmd_policy = None
_event_bus = None

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


def init_system_tools(platform_adapter, event_bus, cmd_policy_path: str = "user/cmd_policy.json"):
    """
    初始化系统工具模块。

    Args:
        platform_adapter: PlatformAdapter 实例
        event_bus: EventBus 实例（用于危险命令确认）
        cmd_policy_path: 命令安全策略文件路径
    """
    global _platform_adapter, _cmd_policy, _event_bus
    _platform_adapter = platform_adapter
    _event_bus = event_bus

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


async def exec_sys_cmd(cmd: str, session_id: str = "", source=None) -> str:
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

    if status == "needs_confirm":
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

    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if _platform_adapter:
        decode = _platform_adapter.decode_command_output
    else:
        decode = lambda b: b.decode("utf-8", errors="replace")

    if process.returncode == 0:
        return decode(stdout).strip()
    else:
        return f"命令执行失败，错误信息：{decode(stderr).strip()}"


async def get_current_system_time() -> str:
    """获取当前系统时间"""
    now = datetime.datetime.now()
    return f"当前宿主机系统时间是：{now.strftime('%Y-%m-%d %H:%M:%S %A')}"


async def get_sys_vitals() -> str:
    """获取系统生命体征"""
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
