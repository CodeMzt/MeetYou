"""
MCP (Model Context Protocol) client and server manager.

Responsibilities:
- start MCP server processes over stdio
- manage MCP sessions
- load tool schemas
- dispatch MCP tool calls
"""

from contextlib import AsyncExitStack
import asyncio
import io
import logging
import os
from pathlib import Path
import sys

try:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except ImportError:  # pragma: no cover - optional dependency
    class ClientSession:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            del args, kwargs

    class StdioServerParameters:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            del args, kwargs

    def stdio_client(*args, **kwargs):  # type: ignore[no-redef]
        del args, kwargs
        raise RuntimeError("The optional 'mcp' package is not installed.")

logger = logging.getLogger("meetyou.mcp")
_DEFAULT_MCP_AUTH_ENV: dict[str, tuple[str, ...]] = {
    "notion_knowledge": ("NOTION_TOKEN",),
    "tavily_web": ("TAVILY_API_KEY",),
}
_NODE_PACKAGE_LAUNCHERS = {"npm", "npm.cmd", "npx", "npx.cmd"}


def _resolve_server_process(
    command: str,
    args: list[str] | None = None,
    *,
    os_name: str | None = None,
    comspec: str | None = None,
) -> tuple[str, list[str]]:
    """
    On Windows, asyncio cannot directly spawn .cmd/.bat files as executables.
    Wrap them with cmd.exe /c so npx.cmd and similar tools work reliably.
    """
    resolved_args = list(args or [])
    current_os = os_name or os.name
    if current_os == "nt" and command.lower().endswith((".cmd", ".bat")):
        shell = comspec or os.environ.get("COMSPEC") or r"C:\Windows\System32\cmd.exe"
        return shell, ["/d", "/c", command, *resolved_args]
    return command, resolved_args


def _resolve_auth_env(server_name: str, info: dict) -> list[str]:
    auth_env = [str(item).strip() for item in info.get("auth_env", []) if str(item).strip()]
    if auth_env:
        return auth_env
    auth_env = [
        str(item).strip()
        for item in ((info.get("auth") or {}).get("env") or [])
        if str(item).strip()
    ]
    if auth_env:
        return auth_env
    return list(_DEFAULT_MCP_AUTH_ENV.get(str(server_name or "").strip(), ()))


def _resolve_cache_dir(candidate: str, *, default_relative: str) -> Path:
    path = Path(str(candidate or default_relative)).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _ensure_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _normalize_node_launcher_env(command: str, merged: dict[str, str]) -> dict[str, str]:
    launcher_name = Path(str(command or "")).name.lower()
    if launcher_name not in _NODE_PACKAGE_LAUNCHERS:
        return merged

    default_cache_dir = _resolve_cache_dir(
        merged.get("MEETYOU_MCP_NPM_CACHE_DIR") or os.environ.get("MEETYOU_MCP_NPM_CACHE_DIR") or ".npm-cache",
        default_relative=".npm-cache",
    )
    resolved_cache_dir = default_cache_dir
    configured_cache_dir = str(merged.get("NPM_CONFIG_CACHE") or merged.get("npm_config_cache") or "").strip()
    if configured_cache_dir:
        candidate = _resolve_cache_dir(configured_cache_dir, default_relative=".npm-cache")
        if _ensure_directory(candidate):
            resolved_cache_dir = candidate
        else:
            _ensure_directory(default_cache_dir)
    else:
        _ensure_directory(default_cache_dir)

    merged["NPM_CONFIG_CACHE"] = str(resolved_cache_dir)
    merged["npm_config_cache"] = str(resolved_cache_dir)

    xdg_cache_dir = resolved_cache_dir / "xdg"
    _ensure_directory(xdg_cache_dir)
    merged.setdefault("XDG_CACHE_HOME", str(xdg_cache_dir))

    home_dir = str(merged.get("HOME") or "").strip()
    if home_dir:
        resolved_home_dir = _resolve_cache_dir(home_dir, default_relative=".npm-cache/home")
        if not _ensure_directory(resolved_home_dir):
            home_dir = ""
    if not home_dir:
        fallback_home_dir = resolved_cache_dir / "home"
        _ensure_directory(fallback_home_dir)
        merged["HOME"] = str(fallback_home_dir)

    merged.setdefault("npm_config_update_notifier", "false")
    merged.setdefault("npm_config_fund", "false")
    return merged


def _compose_server_env(command: str, server_env: dict | None = None) -> dict[str, str]:
    """
    Merge explicit MCP env overrides with the current process environment so
    per-server settings do not accidentally drop secrets loaded from `.env`.
    """
    merged = dict(os.environ)
    for key, value in (server_env or {}).items():
        merged[str(key)] = str(value)
    return _normalize_node_launcher_env(command, merged)


class _LoggerWriter:
    def __init__(self, server_name: str, *, fallback_stream=None):
        self._server_name = str(server_name or "unknown")
        self._buffer = ""
        self._fallback_stream = fallback_stream if fallback_stream is not None else (getattr(sys, "__stderr__", None) or sys.stderr)

    def write(self, text: str) -> int:
        message = str(text or "")
        if not message:
            return 0
        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if line:
                logger.warning("MCP server [%s] stderr: %s", self._server_name, line)
        return len(message)

    def flush(self) -> None:
        line = self._buffer.strip()
        if line:
            logger.warning("MCP server [%s] stderr: %s", self._server_name, line)
        self._buffer = ""

    def fileno(self) -> int:
        fileno = getattr(self._fallback_stream, "fileno", None)
        if fileno is None:
            raise io.UnsupportedOperation("fileno")
        return int(fileno())


class MCPClient:
    """Client wrapper for a single MCP server."""

    def __init__(
        self,
        server_command: str,
        server_args: list[str] | None = None,
        server_env: dict | None = None,
        *,
        server_name: str = "",
    ):
        self.server_name = str(server_name or server_command).strip() or "unknown"
        self.server_command = server_command
        self.server_args = server_args or []
        self.server_env = server_env or None
        self.session: ClientSession | None = None
        self.tools_schema: list[dict] | None = None
        self.exit_stack = AsyncExitStack()

    async def init_mcp_session(self):
        """Start the MCP server process and initialize a stdio session."""
        command, args = _resolve_server_process(
            self.server_command,
            self.server_args,
        )
        params = StdioServerParameters(
            command=command,
            args=args,
            env=_compose_server_env(command, self.server_env),
            cwd=Path.cwd(),
        )
        stdio_ctx = stdio_client(params, errlog=_LoggerWriter(self.server_name))
        read_stream, write_stream = await self.exit_stack.enter_async_context(stdio_ctx)

        session_ctx = ClientSession(read_stream, write_stream)
        self.session = await self.exit_stack.enter_async_context(session_ctx)
        await self.session.initialize()
        logger.info("MCP session initialized: %s %s", command, args)

    async def shutdown_mcp_session(self):
        """Close the MCP session and its server process."""
        await self.exit_stack.aclose()

    async def load_mcp_tools(self):
        """Load MCP tools and convert them into OpenAI-style function schema."""
        if self.session is None:
            raise RuntimeError("MCP session is not initialized")

        tools_resp = dict(await self.session.list_tools())
        self.tools_schema = []
        for tool in tools_resp.get("tools", []):
            tool = dict(tool)
            try:
                self.tools_schema.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": tool.get("inputSchema", {}),
                        },
                    }
                )
            except (KeyError, TypeError) as exc:
                logger.warning("Skipping invalid MCP tool schema: %s", exc)


class MCPManager:
    """Global manager for all configured MCP servers."""

    def __init__(self):
        self.mcp_servers_list: list[str] = []
        self.mcp_clients: dict[str, MCPClient] = {}
        self.mcp_tools: dict[str, list[dict]] = {}
        self.tool_map: dict[str, str] = {}
        self.server_diagnostics: dict[str, dict] = {}

    async def init_mcp_servers(self, mcp_servers: dict):
        """Initialize all enabled MCP servers from config."""
        self.mcp_servers_list = []
        self.mcp_clients = {}
        self.mcp_tools = {}
        self.tool_map = {}
        self.server_diagnostics = {}

        for name, info in mcp_servers.items():
            auth_env = _resolve_auth_env(name, info)
            missing_auth = [env_name for env_name in auth_env if not str(os.environ.get(env_name) or "").strip()]
            diagnostic = {
                "server_name": name,
                "enabled": bool(info.get("enabled", True)),
                "status": "declared",
                "tool_count": 0,
                "tool_names": [],
                "usable": False,
                "degraded": False,
                "auth_env": auth_env,
                "missing_auth": missing_auth,
                "command": str(info.get("command") or "").strip(),
            }
            if not info.get("enabled", True):
                logger.info("Skipping disabled MCP server [%s]", name)
                diagnostic["status"] = "not_enabled"
                diagnostic["degraded"] = False
                self.server_diagnostics[name] = diagnostic
                continue

            command = info.get("command")
            args = info.get("args") or []
            env = info.get("env") or None

            if not command:
                logger.error("Skipping MCP server [%s]: missing command", name)
                diagnostic["status"] = "unavailable"
                diagnostic["error"] = "missing_command"
                diagnostic["degraded"] = True
                self.server_diagnostics[name] = diagnostic
                continue

            if missing_auth:
                logger.info("Skipping MCP server [%s]: missing auth env %s", name, ", ".join(missing_auth))
                diagnostic["status"] = "requires_auth"
                diagnostic["degraded"] = True
                self.server_diagnostics[name] = diagnostic
                continue

            client = MCPClient(command, args, env, server_name=name)
            try:
                await client.init_mcp_session()
                await client.load_mcp_tools()
            except Exception as exc:
                logger.error("Failed to initialize MCP server [%s]: %s", name, exc)
                diagnostic["status"] = "unavailable"
                diagnostic["error"] = str(exc)
                diagnostic["degraded"] = True
                self.server_diagnostics[name] = diagnostic
                try:
                    await client.shutdown_mcp_session()
                except Exception as close_error:
                    logger.debug(
                        "Cleanup after MCP server [%s] init failure also failed: %s",
                        name,
                        close_error,
                    )
                continue

            self.mcp_servers_list.append(name)
            self.mcp_clients[name] = client
            self.mcp_tools[name] = client.tools_schema or []
            diagnostic["status"] = "enabled"
            diagnostic["tool_count"] = len(self.mcp_tools[name])
            diagnostic["tool_names"] = [
                str((func.get("function") or {}).get("name") or "").strip()
                for func in self.mcp_tools[name]
                if str((func.get("function") or {}).get("name") or "").strip()
            ]
            diagnostic["usable"] = diagnostic["tool_count"] > 0
            diagnostic["degraded"] = not diagnostic["usable"]
            if not diagnostic["usable"]:
                diagnostic["warning"] = "no_tools_exposed"
            for func in self.mcp_tools[name]:
                self.tool_map[func["function"]["name"]] = name
            self.server_diagnostics[name] = diagnostic

            logger.info(
                "MCP server [%s] initialized with %s tools",
                name,
                len(self.mcp_tools[name]),
            )

    async def call_mcp_tool(self, tool_name: str, tool_args: dict):
        """Call an MCP tool by name."""
        server_name = self.tool_map.get(tool_name)
        client = self.mcp_clients.get(server_name or "")
        if client is None or client.session is None:
            raise ValueError(f"未找到可用的 MCP 工具: {tool_name}")
        return await client.session.call_tool(tool_name, arguments=tool_args)

    async def close_mcp_servers(self):
        """Close all successfully initialized MCP servers."""
        for name in self.mcp_servers_list:
            try:
                client = self.mcp_clients.get(name)
                if client is None:
                    continue
                await client.shutdown_mcp_session()
                logger.info("MCP server [%s] closed", name)
            except asyncio.CancelledError as exc:
                logger.warning("MCP server [%s] close was cancelled: %s", name, exc)
            except Exception as exc:
                logger.error("Failed to close MCP server [%s]: %s", name, exc)

    def get_server_diagnostics(self) -> list[dict]:
        return [dict(payload) for payload in self.server_diagnostics.values()]

    def get_server_diagnostic(self, server_name: str) -> dict | None:
        payload = self.server_diagnostics.get(str(server_name or "").strip())
        return dict(payload) if isinstance(payload, dict) else None
