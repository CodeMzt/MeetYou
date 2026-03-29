"""
大脑核心处理模块。

职责：
- 管理聊天历史
- 通过 LLMAdapter 与模型通信
- 支持多 tool_call 并行解析（按 index 分组）
- 循环处理工具调用（替代递归）
- 多模态输入接口
- 自动上下文裁剪
"""

import json
import logging

import aiohttp

from core.brain_session import BrainSession
from core.runtime_context import get_event_context

logger = logging.getLogger("meetyou.brain")


class Brain:
    """
    大脑核心处理类。

    封装与 LLM 通信的核心逻辑：聊天历史管理、流式响应处理、
    多工具调用循环、上下文自动裁剪。
    """

    def __init__(self, adapter, tools_manager, context_manager, event_bus, exception_router):
        """
        Args:
            adapter: LLMAdapter 实例（主对话用）
            tools_manager: ToolsManager 实例
            context_manager: ContextManager 实例
            event_bus: EventBus 实例
            exception_router: ExceptionRouter 实例
        """
        self._adapter = adapter
        self._tools_manager = tools_manager
        self._context_manager = context_manager
        self._event_bus = event_bus
        self._exception_router = exception_router
        self._base_messages: list[dict] = []
        self._sessions: dict[str, BrainSession] = {}
        self._http_session: aiohttp.ClientSession | None = None

    async def init_brain(self, sys_prompt: str):
        """
        初始化大脑：加载 system prompt、持久化上下文、创建 HTTP session。
        """
        self._base_messages = [
            {"role": "system", "content": sys_prompt},
        ]
        # 加载持久化上下文
        context = await self._context_manager.load_context()
        self._base_messages.append({"role": "system", "content": context})

        self._http_session = aiohttp.ClientSession()
        logger.info("Brain 初始化完成")

    async def close_brain(self):
        """关闭大脑：保存上下文，关闭 HTTP session。"""
        for session in self._sessions.values():
            await self._save_session_context(session)

        if self._http_session is not None:
            await self._http_session.close()
            self._http_session = None
        logger.info("Brain 已关闭")

    def get_or_create_session(self, session_id: str) -> BrainSession:
        session = self._sessions.get(session_id)
        if session is None:
            session = BrainSession(
                session_id=session_id,
                chat_history=[dict(message) for message in self._base_messages],
            )
            self._sessions[session_id] = session
        session.touch()
        return session

    async def close_session(self, session_id: str):
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await self._save_session_context(session)

    async def _save_session_context(self, session: BrainSession):
        if len(session.chat_history) <= 2:
            return
        recent = session.chat_history[2:]
        lines = []
        for msg in recent[-6:]:
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                lines.append(f"[{msg.get('role', '')}]: {content[:200]}")
        if lines:
            summary = "\n".join(lines)
            try:
                await self._context_manager.update_context(summary)
            except Exception as e:
                logger.error(f"关闭时保存上下文失败: {e}")

    async def input_brain(self, session_id: str, input_info: dict, api_key: str, api_url: str, model: str):
        """
        处理一次输入并流式返回模型回复。

        支持多 tool_call 并行 + 循环处理（非递归）。

        Args:
            input_info: 消息字典 {"role": str, "content": str | list}
            api_key: API Key
            api_url: API URL
            model: 模型名称

        Yields:
            str: 模型的流式文本片段
        """
        if self._http_session is None:
            raise RuntimeError("Brain HTTP session 未初始化，请先调用 init_brain()")

        session = self.get_or_create_session(session_id)
        session.chat_history.append(input_info)
        session.touch()

        # 上下文裁剪
        await self._context_manager.trim_history(
            session.chat_history, model, self._http_session, api_url, api_key
        )

        # 循环处理（支持连续多轮工具调用）
        while True:
            # 构建消息列表（附加本体感知信息）
            messages = session.chat_history + [
                {
                    "role": "system",
                    "content": f"当前用户电脑光标信息：{json.dumps(self._context_manager.proprioception_info, ensure_ascii=False)}",
                }
            ]

            tools = self._tools_manager.get_all_tools()
            assistant_content = ""
            tool_calls = []

            # 流式请求
            async for event in self._adapter.stream_chat(
                self._http_session, api_url, api_key, model, messages, tools
            ):
                if event.type == "text" and event.text:
                    assistant_content += event.text
                    yield event.text
                elif event.type == "reasoning" and event.reasoning_text:
                    # 推理过程可以选择性输出
                    pass
                elif event.type == "tool_calls" and event.tool_calls:
                    tool_calls = event.tool_calls
                elif event.type == "error":
                    logger.error(f"流式响应错误: {event.error}")

            # 记录 assistant 回复
            if assistant_content:
                session.chat_history.append({
                    "role": "assistant",
                    "content": assistant_content,
                })

            # 没有工具调用，结束循环
            if not tool_calls:
                break

            # ---- 处理所有 tool_calls ----

            # 记录 assistant 的 tool_calls 消息
            session.chat_history.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "type": "function",
                        "id": tc.id,
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments_str,
                        },
                    }
                    for tc in tool_calls
                ],
            })

            # 逐个执行并记录结果
            for tc in tool_calls:
                try:
                    args = tc.arguments
                except Exception:
                    args = {}

                try:
                    context = get_event_context()
                    result = await self._tools_manager.call_tool(
                        tc.name,
                        args,
                        session_id=context.get("session_id", session_id),
                        source=context.get("source"),
                    )
                except Exception as e:
                    result = f"Error: 工具 {tc.name} 执行异常: {e}"

                session.chat_history.append({
                    "role": "tool",
                    "content": result if isinstance(result, str) else str(result),
                    "tool_call_id": tc.id,
                })

            # 循环回去让 LLM 处理工具结果
