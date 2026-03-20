from tools.system_tools import get_current_system_time
from tools.memory import recall_memory
from tools.memory import save_memory
from tools.memory import update_memory
from tools.memory import retrieve_memory_net
from tools.system_tools import exec_sys_cmd
import json
import aiohttp

__chat_history = []
__chat_http_session = None

__tool_schemas_list = None

async def load_context():
    context_list = await retrieve_memory_net('context', 1, 0)
    if not context_list:
        return "当前没有暂存的上下文信息。"
    return "\n".join([info.get('content', '') for info in context_list])

async def update_context(context:str):
    return await update_memory('context',context)

async def init_tools(tools_schema_path: str):
    global __tool_schemas_list
    with open(tools_schema_path, "r",encoding="utf-8") as f:
        __tool_schemas_list = json.load(f)

async def init_brain(sys_prompt):
    global __chat_history
    __chat_history = [
        {
            "role": "system",
            "content": sys_prompt
        }
    ]
    global __chat_http_session
    __chat_http_session = aiohttp.ClientSession()

async def close_brain():
    global __chat_http_session
    if __chat_http_session is not None:
        await __chat_http_session.close()   
        __chat_http_session = None

    global __chat_history
    context = await load_context()
    __chat_history.append(
        {
            "role": "system",
            "content": context
        }
        )

async def input_brain(input_info,api_key,api_url,model):
    global __chat_history
    __chat_history.append(input_info)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": __chat_history,
        "tools": __tool_schemas_list["common_tools"]+__tool_schemas_list["memory_tools"]+__tool_schemas_list["context_tools"],
        "stream": True
    }
    if __chat_http_session is None:
        raise Exception("Chat HTTP session is not initialized. Call init_brain first.")
    
    __tool_call_id = ''
    __func_name = ''
    __func_args = ''
    __is_tool_call = False

    async with __chat_http_session.post(api_url, headers=headers, json=payload) as response:
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
        __chat_history.append(
            {
                "role": "assistant",
                "content": assistant_content
            }
        )
    if __is_tool_call:
        # yield (f"Tool call: {__tool_call_id}, {__func_name}, {__func_args}\r\n")
        try:
            __func_args_dict = json.loads(__func_args)
        except Exception as e:
            result = (f"Error parsing function arguments: {e}\r\n")
            __func_args_dict = {}
        if __func_name == 'exec_sys_cmd':
            cmd = __func_args_dict.get('cmd')
            if not cmd:
                result =  (f"Error: exec_sys_cmd function missing 'cmd' argument\r\n")
            # yield f"Executing command: {cmd}\r\n"
            else: 
                result = await exec_sys_cmd(cmd)
        elif __func_name == 'save_memory':
            memory_text = __func_args_dict.get('memory_text')
            if not memory_text:
                result =  (f"Error: save_memory function missing 'memory_text' argument\r\n")
            else:
                result = await save_memory(memory_text)
        elif __func_name == 'recall_memory':
            query_text = __func_args_dict.get('query_text')
            if not query_text:
                result =  (f"Error: recall_memory function missing 'query_text' argument\r\n")
            else:
                result = await recall_memory(query_text)
        elif __func_name == 'get_current_system_time':
            result = await get_current_system_time()
        elif __func_name == 'update_context':
            context = __func_args_dict.get('context')
            if not context:
                result =  (f"Error: update_context function missing 'context' argument\r\n")
            else:
                result = await update_context(context)
        else:
            result =  f"Error: Unknown function {__func_name}\r\n"

        __chat_history.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
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
        
        async for chunk in input_brain(tool_output_info, api_key, api_url, model):
            yield chunk
        



