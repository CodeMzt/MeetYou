import asyncio
import aiohttp

from tools.memory import memory_instance
from core.brain import brain_instance
from core.context import context_manager
from core.sensors import listener_instance
from core.manager import cfg
from core.manager import tools_manager

class Heart:
    """
    系统心脏模块类。
    负责在后台按设定的间隔节拍循环运行，探测系统状态并判断是否需要主动触发系统思维。
    """
    def __init__(self):
        """
        初始化 Heart 对象，定义心跳相关属性。
        """
        self._heart_prompt = ''
        self._heart_http_session = None
        self._heart_interval = 60
        self._heart_api_key = ""
        self._heart_api_url = ""
        self._heart_model = ""

    async def init_heart(self):
        """
        依据全局配置异步初始化心脏对象的各项参数（提示词、频率、API Key和模型）。
        同步建立异步 HTTP 请求会话。
        """
        try:
            self._heart_prompt = cfg.get_prompt("heartbeat")
        except Exception as e:
            listener_instance.system_output(f"Error loading heartbeat prompt: {e}")

        try:
            self._heart_interval = int(cfg.get_config_item("heartbeat_interval") or self._heart_interval)
        except Exception as e:
            listener_instance.system_output(f"Error loading heartbeat interval: {e}")

        self._heart_api_url = cfg.get_config_item("heartbeat_api_url") or self._heart_api_url
        self._heart_api_key = cfg.get_config_item("heartbeat_api_key") or self._heart_api_key
        self._heart_model = cfg.get_config_item("heart_model") or self._heart_model

        self._heart_http_session = aiohttp.ClientSession()

    async def close_heart(self):
        """
        异步关闭心脏运行环境及对应的网络请求客户端会话。
        """
        if self._heart_http_session:
            await self._heart_http_session.close()
            self._heart_http_session = None

    async def heartbeat_processor(self):
        """
        心跳核心处理任务协程。
        按固定间隔发起请求探测后台状态；如果检测到并返回了有意义的状态突变，将其投递到系统的信息流队列中充当潜意识触发器。
        同时每次心跳循环兼具推进记忆消退的逻辑。
        """

        while True:
            if context_manager.shutdown_event.is_set():
                break       
            if self._heart_http_session is None:
                raise Exception("Heart HTTP session is not initialized. Call init_heart first.")

            if not self._heart_api_url or not self._heart_model:
                listener_instance.system_output("[system] [heart] [Error] Heartbeat config missing: heartbeat_api_url or heart_model")
                try:
                    await asyncio.wait_for(context_manager.shutdown_event.wait(), timeout=self._heart_interval)
                    break
                except asyncio.TimeoutError:
                    continue

            if(tools_manager.tools_schema_list is None):
                try:
                    await asyncio.wait_for(context_manager.shutdown_event.wait(), timeout=1.0)
                    break
                except asyncio.TimeoutError:
                    continue

            headers = {}
            if self._heart_api_key:
                headers = {
                    "Authorization": f"Bearer {self._heart_api_key}",
                    "Content-Type": "application/json",
                }

            payload = {
                "model": self._heart_model,
                "messages": [{"role": "user", "content": self._heart_prompt}],
                "stream": False,
                "tools": tools_manager.tools_schema_list["common_tools"]+tools_manager.tools_schema_list["memory_tools"],
            }

            try:
                async with self._heart_http_session.post(self._heart_api_url, json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    message = data.get("message") or {}
                    output = (message.get("content") or "").strip()
                    if output and output not in ("[HEARTBEAT_OK]", "HEARTBEAT_OK"):
                        heart_sensor = {
                            "source": "heart",
                            "content": output
                        }
                        await context_manager.sensory_queue.put(heart_sensor)
            except Exception as e:
                listener_instance.system_output(f"[system] [heart] [Error] Heartbeat error: {e}")

            await memory_instance.fade_memory()
            try:
                await asyncio.wait_for(context_manager.shutdown_event.wait(), timeout=self._heart_interval)
                break
            except asyncio.TimeoutError:
                pass


heart_instance = Heart()
