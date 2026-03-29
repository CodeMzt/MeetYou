"""
MCP (Model Context Protocol) 客户端与管理器。

职责：
- 启动 MCP 服务进程（stdio 方式）
- 管理通信会话
- 提取工具 Schema
- 分派工具调用
"""

import logging

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from contextlib import AsyncExitStack

logger = logging.getLogger("meetyou.mcp")


class MCPClient:
    """单个 MCP 服务的客户端。"""

    def __init__(self, server_command: str, server_args: list[str]):
        self.server_command = server_command
        self.server_args = server_args
        self.session: ClientSession | None = None
        self.tools_schema: list[dict] | None = None
        self.exit_stack = AsyncExitStack()

    async def init_mcp_session(self):
        """启动 MCP 进程并建立 stdio 会话。"""
        params = StdioServerParameters(
            command=self.server_command,
            args=self.server_args,
            env=None,
        )
        stdio_ctx = stdio_client(params)
        read_stream, write_stream = await self.exit_stack.enter_async_context(stdio_ctx)

        session_ctx = ClientSession(read_stream, write_stream)
        self.session = await self.exit_stack.enter_async_context(session_ctx)
        await self.session.initialize()
        logger.info(f"MCP 会话已建立: {self.server_command} {self.server_args}")

    async def shutdown_mcp_session(self):
        """关闭 MCP 会话及进程。"""
        await self.exit_stack.aclose()

    async def load_mcp_tools(self):
        """获取 MCP 工具列表并转化为 OpenAI 格式 Schema。"""
        tools_resp = dict(await self.session.list_tools())
        self.tools_schema = []
        for tool in tools_resp.get("tools", []):
            tool = dict(tool)
            try:
                self.tools_schema.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("inputSchema", {}),
                    },
                })
            except (KeyError, TypeError) as e:
                logger.warning(f"跳过无效 MCP 工具: {e}")


class MCPManager:
    """MCP 服务全局管理器。"""

    def __init__(self):
        self.mcp_servers_list: list[str] = []
        self.mcp_clients: dict[str, MCPClient] = {}
        self.mcp_tools: dict[str, list[dict]] = {}
        self.tool_map: dict[str, str] = {}  # tool_name → server_name

    async def init_mcp_servers(self, mcp_servers: dict):
        """初始化所有配置的 MCP 服务。"""
        for name, info in mcp_servers.items():
            try:
                self.mcp_servers_list.append(name)
                client = MCPClient(info["command"], info["args"])
                self.mcp_clients[name] = client
                await client.init_mcp_session()
                await client.load_mcp_tools()
                self.mcp_tools[name] = client.tools_schema or []
                for func in self.mcp_tools[name]:
                    self.tool_map[func["function"]["name"]] = name
                logger.info(f"MCP 服务 [{name}] 初始化完成: {len(self.mcp_tools[name])} 个工具")
            except Exception as e:
                logger.error(f"MCP 服务 [{name}] 初始化失败: {e}")

    async def call_mcp_tool(self, tool_name: str, tool_args: dict):
        """调用 MCP 工具。"""
        server_name = self.tool_map.get(tool_name)
        if not server_name or server_name not in self.mcp_clients:
            raise ValueError(f"未找到 MCP 工具: {tool_name}")
        return await self.mcp_clients[server_name].session.call_tool(
            tool_name, arguments=tool_args
        )

    async def close_mcp_servers(self):
        """关闭所有 MCP 服务。"""
        for name in self.mcp_servers_list:
            try:
                await self.mcp_clients[name].shutdown_mcp_session()
                logger.info(f"MCP 服务 [{name}] 已关闭")
            except Exception as e:
                logger.error(f"MCP 服务 [{name}] 关闭失败: {e}")