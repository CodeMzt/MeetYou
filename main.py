import asyncio
import traceback

from tools.memory import init_memory
from core.heart import close_heart
from core.config_manage import ConfigManager
from core.brain import init_brain
from core.brain import input_brain
from core.brain import close_brain
from core.heart import init_heart
from core.heart import heartbeat_processor
from core.brain import init_tools
from core.sensors import listener
from core.context import sensory_queue
from core.context import shutdown_event
from core.sensors import output_field

api_key = ''
api_url = ''
model = ''
start_prompt = ''

def output(text:str):
    text = text.replace('\r', '')
    output_field.text += text
    output_field.buffer.cursor_position = len(output_field.text)

async def setup():
    global api_key,api_url,model,start_prompt
    cfg = ConfigManager()    
    tools_schema_path = cfg.get_config_item("tools_schema_path")
    await init_tools(tools_schema_path)
    sys_prompt = cfg.get_prompt("soul")
    await init_brain(sys_prompt)
    await init_heart()
    await init_memory()
    api_key = cfg.get_config_item("api_key")
    api_url = cfg.get_config_item("api_url")
    model = cfg.get_config_item("model")

    start_prompt = cfg.get_prompt("start")


async def brain_processor():
    output("Mozart: ")
    input_info = {"role": "user", "content": start_prompt}
    reply = input_brain(input_info, api_key, api_url, model)
    async for chunk in reply:
        output(chunk)
    output("\r\n")
    while True:
        get_task = asyncio.create_task(sensory_queue.get())
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, pending = await asyncio.wait(
            [get_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if shutdown_task in done:
            break
        event = get_task.result()

        if event["source"] == "user":
            input_info = {"role": "user", "content": event["content"]}
        elif event["source"] == "heart":
            input_info = {"role": "system", "content": f"系统后台心跳截获重要潜意识事务，请立刻作为内部处理：{event['content']}"}
        
        output("Mozart: ")
        reply = input_brain(input_info, api_key, api_url, model)
        async for chunk in reply:
            output(chunk)
        output('\r\n')



async def async_main():
    await setup()
    try:
        await asyncio.gather(brain_processor(),heartbeat_processor(),listener())
    finally:

        await close_brain()
        await close_heart()

if __name__ == "__main__":
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"你干啥了，我怎么被关了，你看看报错：{type(e).__name__}: {e}")
        print(traceback.format_exc())

