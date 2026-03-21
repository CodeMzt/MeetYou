import asyncio
from tools.memory import memory_instance

class ContextManager:
    """
    系统上下文管理器类。
    用于记录光标位置、当前运行的应用信息，以及管理系统的内部消息队列和关闭事件。
    """
    def __init__(self):
        """初始化上下文管理器状态。"""
        self.proprioception_info = {
            'ui_info': '',
            'running_apps': [],
            'last_update_time': 0,
        }
        self.sensory_queue = asyncio.Queue()
        self.shutdown_event = asyncio.Event()

    async def load_context(self):
        """
        从记忆系统中异步加载最近保存的上下文信息。
        
        Returns:
            str: 提取的上下文文本，如果没有则返回缺省提示。
        """
        context_list = await memory_instance.retrieve_memory_net('context', 1, 0)
        if not context_list:
            return "当前没有暂存的上下文信息。"
        return "\n".join([info.get('content', '') for info in context_list])

    async def update_context(self, context:str):
        """
        异步更新并持久化新的系统上下文到记忆中。
        
        Args:
            context (str): 要保存的上下文内容。
        """
        return await memory_instance.update_memory('context',context)



context_manager = ContextManager()