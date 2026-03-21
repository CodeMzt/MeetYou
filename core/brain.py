from core.context import context_manager
from core.manager import tools_manager

import json
import aiohttp

class Brain:
    """
    大脑核心处理类，封装了与大语言模型通信的核心逻辑、聊天历史和 HTTP 会话管理。
    """
    def __init__(self):
        """
        初始化 Brain 实例的历史记录和会话占位。
        """
        self._chat_history = []
        self._chat_http_session = None

    async def init_brain(self, sys_prompt):
        """
        异步初始化大脑状态。
        加载系统提示词以及持久化的上下文记忆，同时开启异步的 HTTP 客户端会话。
        
        Args:
            sys_prompt (str): 系统提示词内容。
        """
        self._chat_history = [
            {
                "role": "system",
                "content": sys_prompt
            }
        ]

        self._chat_history.append({
            "role": "system",
            "content": await context_manager.load_context()
        })
        self._chat_http_session = aiohttp.ClientSession()

    async def close_brain(self):
        """
        异步关闭大脑工作状态，保存当前记忆上下文并安全断开 HTTP 连接会话。
        """
        if self._chat_http_session is not None:
            await self._chat_http_session.close()   
            self._chat_http_session = None

        context = await context_manager.load_context()
        self._chat_history.append(
            {
                "role": "system",
                "content": context
            }
        )

    async def input_brain(self, input_info, api_key, api_url, model):
        """
        异步调用模型接口进行推断和回应。
        处理用户或系统输入，合并光标信息后发起流式请求。
        如果包含工具调用，则自动解析并调用本地函数，持续交互直至返回最终文本结果。
        
        Args:
            input_info (dict): 当前的输入数据字典，包含 role 和 content。
            api_key (str): 模型访问 API Key。
            api_url (str): 模型 API 服务地址。
            model (str): 指定的模型名称。
            
        Yields:
            str: 模型的流式文本回复片段。
            
        Raises:
            Exception: 如果未调用 init_brain 即发起了请求。
        """
        self._chat_history.append(input_info)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": self._chat_history+[
                {
                    "role": "system",
                    "content": f"当前用户电脑光标信息：{json.dumps(context_manager.proprioception_info)}"
                }
            ],
            "tools": tools_manager.tools_schema_list["common_tools"]+tools_manager.tools_schema_list["memory_tools"]+tools_manager.tools_schema_list["context_tools"],
            "stream": True
        }
        if self._chat_http_session is None:
            raise Exception("Chat HTTP session is not initialized. Call init_brain first.")
        
        __tool_call_id = ''
        __func_name = ''
        __func_args = ''
        __is_tool_call = False

        async with self._chat_http_session.post(api_url, headers=headers, json=payload) as response:
            response.raise_for_status()
            assistant_content = ""
            while not response.content.at_eof():
                chunk = await response.content.readline()
                if chunk:
                    raw_line = chunk.decode("utf-8")
                    if raw_line.startswith("data:"):
                        json_data = raw_line[6:].strip()
                        if json_data.startswith("[DONE]"):
                            break
                        try:
                            data = json.loads(json_data)
                            choices = data.get("choices") or []
                            if not choices:
                                continue
                            delta = choices[0].get("delta") or {}
                            if "tool_calls" in delta:
                                __is_tool_call = True
                                tool_chunk = delta['tool_calls'][0]
                                if 'id' in tool_chunk:
                                    __tool_call_id = tool_chunk['id']
                                if 'function' in tool_chunk:
                                    func_chunk = tool_chunk['function']
                                    if 'name' in func_chunk:
                                        __func_name = func_chunk['name']
                                    if 'arguments' in func_chunk:
                                        __func_args += func_chunk['arguments']
                                continue
                            elif 'content' in delta:
                                output = delta.get("content")
                                if not output:
                                    continue
                                assistant_content += output
                                yield output
                        except Exception as e:
                            # yield (f"Error parsing JSON data: {e}\r\n")
                            continue
            self._chat_history.append({"role": "assistant", "content": assistant_content})
        if __is_tool_call:
            try:
                __func_args_dict = json.loads(__func_args) if __func_args else {}
            except Exception as e:
                result = f"Error parsing function arguments: {e}\r\n"
                __func_args_dict = None

            if __func_args_dict is not None:
                if __func_name in tools_manager.supported_funcs:
                    try:
                        result = await tools_manager.supported_funcs[__func_name](**__func_args_dict)
                    except TypeError as e:
                        result = f"Error: Argument mismatch for {__func_name}: {e}\r\n"
                    except Exception as e:
                        result = f"Error executing {__func_name}: {e}\r\n"
                else:
                    result = f"Error: Unknown function {__func_name}\r\n"

            self._chat_history.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                            "type": "function",
                            "id": __tool_call_id,
                            "function": {
                                "name": __func_name,
                                "arguments": __func_args
                            }
                        }
                    ]
                }
            )
            tool_output_info = {
                "role": "tool",
                "content": result,
                "tool_call_id": __tool_call_id,
            }
            
            async for chunk in self.input_brain(tool_output_info, api_key, api_url, model):
                yield chunk

brain_instance = Brain()
        



