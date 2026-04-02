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
import logging
import os

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


def _compose_server_env(server_env: dict | None = None) -> dict[str, str]:
    """
    Merge explicit MCP env overrides with the current process environment so
    per-server settings do not accidentally drop secrets loaded from `.env`.
    """
    merged = dict(os.environ)
    for key, value in (server_env or {}).items():
        merged[str(key)] = str(value)
    return merged


class MCPClient:
    """Client wrapper for a single MCP server."""

    def __init__(
        self,
        server_command: str,
        server_args: list[str] | None = None,
        server_env: dict | None = None,
    ):
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
            env=_compose_server_env(self.server_env),
        )
        stdio_ctx = stdio_client(params)
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

    async def init_mcp_servers(self, mcp_servers: dict):
        """Initialize all enabled MCP servers from config."""
        self.mcp_servers_list = []
        self.mcp_clients = {}
        self.mcp_tools = {}
        self.tool_map = {}

        for name, info in mcp_servers.items():
            if not info.get("enabled", True):
                logger.info("Skipping disabled MCP server [%s]", name)
                continue

            command = info.get("command")
            args = info.get("args") or []
            env = info.get("env") or None

            if not command:
                logger.error("Skipping MCP server [%s]: missing command", name)
                continue

            client = MCPClient(command, args, env)
            try:
                await client.init_mcp_session()
                await client.load_mcp_tools()
            except Exception as exc:
                logger.error("Failed to initialize MCP server [%s]: %s", name, exc)
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
            for func in self.mcp_tools[name]:
                self.tool_map[func["function"]["name"]] = name

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
