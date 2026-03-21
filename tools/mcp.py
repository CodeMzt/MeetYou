from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from contextlib import AsyncExitStack

class MCPClient:
    """
    MCP (Model Context Protocol) 客户端类。
    用于启动基于 stdio 的 MCP 服务进程、建立与管理通信会话，并提取服务所支持的工具结构。
    """
    def __init__(self, server_command:str, server_args:list[str]):
        """初始化 MCPClient，提供目标服务启动命令与参数。"""
        self.server_command = server_command
        self.server_args = server_args
        self.session = None
        self.stdio_ctx = None
        self.session_ctx = None
        self.tools_schema = None
        self.read_stream = None
        self.write_stream = None
        self.exit_stack = AsyncExitStack()

    async def init_mcp_session(self):
        '''
        启动第三方MCP进程，建立stdio对话
        '''
        _server_params = StdioServerParameters(
            command=self.server_command,
            args=self.server_args,
            env=None
        )
    
        # 建立输入输出流
        self.stdio_ctx = stdio_client(_server_params)
        self.read_stream, self.write_stream = await self.exit_stack.enter_async_context(self.stdio_ctx)

        # 建立会话
        self.session_ctx = ClientSession(self.read_stream, self.write_stream)
        self.session = await self.exit_stack.enter_async_context(self.session_ctx)

        # 初始化会话
        await self.session.initialize()

    async def shutdown_mcp_session(self):
        '''
        关闭MCP会话
        '''
        await self.exit_stack.aclose()

    async def get_mcp_tools(self):
        '''
        获取MCP工具列表,转化为schema
        '''
        _tools = dict(await self.session.list_tools())
        self.tools_schema = []
        for _tool in _tools['tools']:
            _tool = dict(_tool)
            try:
                self.tools_schema.append({
                    "type": "function",
                    "function": {
                        "name": _tool['name'],
                        "description": _tool['description'],
                        "parameters": _tool['inputSchema']
                }
            })
            except Exception as e:
                pass

class MCPManager:
    """
    MCP 服务全局管理类。
    负责初始化所有配置的 MCP 服务，统筹管理其对应的客户端实例及提取到的工具列表。
    """
    def __init__(self):
        """初始化管理器的数据结构。"""
        self.mcp_servers_list = []
        self.mcp_clients = {}
        self.mcp_tools = {}

    async def init_mcp_servers(self, mcp_servers:dict):
        for _server_name, _server_info in mcp_servers.items():
            self.mcp_servers_list.append(_server_name)
            self.mcp_clients[_server_name] = MCPClient(_server_info['command'], _server_info['args'])
            await self.mcp_clients[_server_name].init_mcp_session()
            await self.mcp_clients[_server_name].get_mcp_tools()
            self.mcp_tools[_server_name] = self.mcp_clients[_server_name].tools_schema
        