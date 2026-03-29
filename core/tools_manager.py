"""
工具管理器。

统一管理系统内置工具和 MCP 外部工具的 Schema 和调用分派。
原 manager.py 中 ToolsManager 部分的独立重构。
"""

import asyncio
import inspect
import json
import logging

logger = logging.getLogger("meetyou.tools_manager")


class ToolsManager:
    """
    系统工具管理器。

    职责：
    1. 加载工具 Schema（从 JSON 文件 + MCP 服务器）
    2. 注册内置工具函数
    3. 统一分派工具调用（内置 vs MCP）
    """

    def __init__(self, memory, context_manager, mcp_manager, system_tools_module):
        """
        Args:
            memory: Memory 实例
            context_manager: ContextManager 实例
            mcp_manager: MCPManager 实例
            system_tools_module: system_tools 模块（包含 exec_sys_cmd 等函数）
        """
        self.tools_schema_dict: dict = {}
        self._mcp_manager = mcp_manager

        # 注册内置工具函数
        self.supported_funcs: dict = {
            "exec_sys_cmd": system_tools_module.exec_sys_cmd,
            "save_memory": memory.save_memory,
            "recall_memory": memory.recall_memory,
            "get_current_system_time": system_tools_module.get_current_system_time,
            "update_context": context_manager.update_context,
            "get_sys_vitals": system_tools_module.get_sys_vitals,
        }

    async def init_tools(self, tools_schema_path: str, mcp_servers: dict):
        """
        初始化：加载工具 Schema 并启动 MCP 服务。

        Args:
            tools_schema_path: tools.json 文件路径
            mcp_servers: MCP 服务器配置字典
        """
        with open(tools_schema_path, "r", encoding="utf-8") as f:
            self.tools_schema_dict = json.load(f)

        # 初始化 MCP 并聚合工具
        await self._mcp_manager.init_mcp_servers(mcp_servers)
        self.tools_schema_dict["mcp_tools"] = []
        for server_name in self._mcp_manager.mcp_servers_list:
            self.tools_schema_dict["mcp_tools"].extend(
                self._mcp_manager.mcp_tools[server_name]
            )
        logger.info(
            f"工具初始化完成: 内置 {len(self.supported_funcs)} 个, "
            f"MCP {len(self.tools_schema_dict.get('mcp_tools', []))} 个"
        )

    def get_all_tools(self) -> list[dict]:
        """获取所有工具的 Schema 列表（供发送给 LLM）"""
        all_tools = []
        for key in ("common_tools", "memory_tools", "context_tools", "mcp_tools"):
            all_tools.extend(self.tools_schema_dict.get(key, []))
        return all_tools

    def get_heartbeat_tools(self) -> list[dict]:
        """获取心跳可用的工具子集"""
        tools = []
        for key in ("common_tools", "memory_tools"):
            tools.extend(self.tools_schema_dict.get(key, []))
        return tools

    async def call_tool(
        self,
        tool_name: str,
        tool_args: dict,
        session_id: str = "",
        source=None,
    ) -> str:
        """
        统一工具调用分派。

        Args:
            tool_name: 工具名称
            tool_args: 参数字典

        Returns:
            str: 工具执行结果
        """
        # 内置工具
        if tool_name in self.supported_funcs:
            try:
                call_kwargs = dict(tool_args)
                func = self.supported_funcs[tool_name]
                signature = inspect.signature(func)
                if "session_id" in signature.parameters:
                    call_kwargs["session_id"] = session_id
                if "source" in signature.parameters:
                    call_kwargs["source"] = source
                return await func(**call_kwargs)
            except TypeError as e:
                return f"Error: 参数不匹配 {tool_name}: {e}"
            except Exception as e:
                logger.error(f"内置工具 {tool_name} 执行失败: {e}")
                return f"Error: {tool_name} 执行失败: {e}"

        # MCP 工具
        if tool_name in self._mcp_manager.tool_map:
            try:
                result = await asyncio.wait_for(
                    self._mcp_manager.call_mcp_tool(tool_name, tool_args),
                    timeout=10.0,
                )
                if result.content:
                    text = "\n".join(
                        item.text
                        for item in result.content
                        if getattr(item, "type", "") == "text"
                    )
                    return text
                return f"Error: MCP 工具 {tool_name} 返回空内容"
            except asyncio.TimeoutError:
                return f"Error: MCP 工具 {tool_name} 超时"
            except Exception as e:
                logger.error(f"MCP 工具 {tool_name} 执行失败: {e}")
                return f"Error: MCP 工具 {tool_name} 失败: {e}"

        return f"Error: 未找到工具 {tool_name}"
