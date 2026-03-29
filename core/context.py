"""
上下文管理器。

负责：
1. 聊天历史的滑动窗口管理 + 摘要压缩
2. 持久化上下文（记忆节点）的加载与更新
3. 本体感知信息（光标/进程等）的存储
4. 自动获取模型上下文限度并据此裁剪
"""

import json
import logging

logger = logging.getLogger("meetyou.context")


class ContextManager:
    """
    系统上下文管理器。

    管理聊天历史token预算、持久化上下文、本体感知信息。
    """

    def __init__(self, memory, adapter, event_bus):
        """
        Args:
            memory: Memory 实例
            adapter: 主对话的 LLMAdapter 实例（用于获取上下文限度和做摘要）
            event_bus: EventBus 实例
        """
        self._memory = memory
        self._adapter = adapter
        self._event_bus = event_bus

        # 本体感知信息
        self.proprioception_info: dict = {
            "ui_info": "",
            "running_apps": [],
            "last_update_time": 0,
        }

    # ============================================================
    # 持久化上下文（基于记忆图谱）
    # ============================================================

    async def load_context(self) -> str:
        """从记忆系统加载最近保存的上下文"""
        context_list = await self._memory.retrieve_memory_net("context", 1, 0)
        if not context_list:
            return "当前没有暂存的上下文信息。"
        return "\n".join(info.get("content", "") for info in context_list)

    async def update_context(self, context: str) -> str:
        """更新并持久化上下文到记忆"""
        return await self._memory.update_memory("context", context)

    # ============================================================
    # Token 估算
    # ============================================================

    @staticmethod
    def estimate_tokens(messages: list[dict]) -> int:
        """
        粗估消息列表的 token 数。

        使用启发式规则：中文约 1.5 字/token，英文约 4 字符/token。
        综合取 ~2 字符/token 作为保守估计。
        """
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        total_chars += len(part.get("text", ""))
            # tool_calls 也占 token
            if "tool_calls" in msg:
                total_chars += len(json.dumps(msg["tool_calls"], ensure_ascii=False))
        return int(total_chars / 1.8)

    # ============================================================
    # 滑动窗口 + 摘要压缩
    # ============================================================

    def get_context_limit(self, model_name: str) -> int:
        """获取模型的上下文窗口大小"""
        return self._adapter.get_context_limit(model_name)

    async def trim_history(
        self,
        chat_history: list[dict],
        model: str,
        session,
        api_url: str,
        api_key: str,
        reserve_ratio: float = 0.75,
    ):
        """
        滑动窗口 + 摘要压缩。

        当聊天历史超过模型上下文限度的 reserve_ratio 时，将最早的对话轮次
        摘要化，替换为一条摘要消息。

        Args:
            chat_history: 聊天历史列表（会被就地修改）
            model: 当前模型名称
            session: aiohttp.ClientSession
            api_url: API 地址
            api_key: API 密钥
            reserve_ratio: 可用比例（默认 75%，预留 25% 给模型回复）
        """
        limit = self.get_context_limit(model)
        usable_tokens = int(limit * reserve_ratio)
        current_tokens = self.estimate_tokens(chat_history)

        if current_tokens <= usable_tokens:
            return  # 不需要裁剪

        logger.info(
            f"上下文裁剪触发: {current_tokens} tokens > {usable_tokens} 可用 "
            f"(模型限度 {limit})"
        )

        # 收集要压缩的旧消息（保留 index 0 的 system prompt）
        messages_to_summarize = []
        while (
            self.estimate_tokens(chat_history) > usable_tokens
            and len(chat_history) > 3  # 至少保留 system + 最近一轮
        ):
            # 移除 system prompt 之后的最早消息
            removed = chat_history.pop(1)
            messages_to_summarize.append(removed)

        if not messages_to_summarize:
            return

        # 生成摘要
        summary = await self._summarize(
            messages_to_summarize, session, api_url, api_key, model
        )

        # 插入摘要到 system prompt 之后
        chat_history.insert(1, {
            "role": "system",
            "content": f"[历史对话摘要]\n{summary}",
        })

        logger.info(
            f"裁剪完成: 压缩 {len(messages_to_summarize)} 条消息为摘要, "
            f"当前 {self.estimate_tokens(chat_history)} tokens"
        )

    async def _summarize(
        self,
        messages: list[dict],
        session,
        api_url: str,
        api_key: str,
        model: str,
    ) -> str:
        """调用主模型对一组消息做摘要"""
        # 拼接待摘要的内容
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                lines.append(f"[{role}]: {content}")

        text_to_summarize = "\n".join(lines)

        summary_messages = [
            {
                "role": "system",
                "content": "请将以下对话历史压缩为简洁的摘要，保留关键信息、决策和约定。输出纯文本，字数尽量精简。",
            },
            {
                "role": "user",
                "content": text_to_summarize,
            },
        ]

        try:
            result = await self._adapter.chat(
                session, api_url, api_key, model, summary_messages
            )
            summary = result.get("content", "").strip()
            if summary:
                return summary
        except Exception as e:
            logger.error(f"摘要生成失败: {e}")

        # 兜底：截取原文前 300 字
        return text_to_summarize[:800] + "..."