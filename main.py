from tools.memory import init_deep_memory
from core.heart import close_heart
from core.config_manage import ConfigManager
from core.brain import init_brain
from core.brain import input_brain
from core.brain import close_brain
from core.heart import init_heart
from core.heart import heartbeat_cycle
from core.brain import init_tools
import asyncio
import traceback

async def setup():
    cfg = ConfigManager()
    sys_prompt = cfg.get_prompt("soul")
    await init_brain(sys_prompt)
    await init_heart()
    await init_deep_memory()
    api_key = cfg.get_config_item("api_key")
    api_url = cfg.get_config_item("api_url")
    model = cfg.get_config_item("model")
    
    tools_schema_path = cfg.get_config_item("tools_schema_path")
    await init_tools(tools_schema_path)
    
    start_prompt = cfg.get_prompt("start")

    return api_key, api_url, model, start_prompt

async def terminal_chat(api_key, api_url, model, start_prompt):
    __is_init = True
    while True:
        if __is_init:
            __is_init = False
            user_content = start_prompt
        else:
            user_content = await asyncio.to_thread(input, "User: ")
        if user_content == "exit":
            print("Mozart: 哎，回见！")
            await close_brain()
            await close_heart()
            break
        print("Mozart: ",end='')
        input_info = {
            "role": "user",
            "content": user_content
        }
        reply = input_brain(input_info, api_key, api_url, model)
        async for chunk in reply:
            print(chunk, end='',flush=True)
        print()

async def async_main():
    api_key, api_url, model, start_prompt = await setup()
    print("欢迎使用，输入exit退出")
    try:
        await asyncio.gather(terminal_chat(api_key, api_url, model, start_prompt),heartbeat_cycle())
    finally:
        await close_brain()
        await close_heart()

if __name__ == "__main__":
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\r\nMozart: 哎，回见！")
    except Exception as e:
        print(f"你干啥了，我怎么被关了，你看看报错：{type(e).__name__}: {e}")
        print(traceback.format_exc())

