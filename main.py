import asyncio
import traceback

from core.manager import cfg
from tools.memory import memory_instance
from core.brain import brain_instance
from core.heart import heart_instance
from core.sensors import listener_instance, proprioceptor_instance
from core.context import context_manager
from core.manager import tools_manager

api_key = ''
api_url = ''
model = ''
start_prompt = ''

def output(text:str):
    """
    更新系统输出到界面，并将光标移动到末尾。
    
    Args:
        text (str): 要输出的文本内容。
    """
    text = text.replace('\r', '')
    listener_instance.output_field.text += text
    listener_instance.output_field.buffer.cursor_position = len(listener_instance.output_field.text)

async def setup():
    """
    异步任务：初始化系统所需的各项服务。
    包括工具管理器、记忆模块、大脑、心脏对象，并加载全局配置以及启动提示词。
    """
    global api_key,api_url,model,start_prompt
     
    tools_schema_path = cfg.get_config_item("tools_schema_path")
    await tools_manager.init_tools(tools_schema_path)
    await memory_instance.init_memory()
    sys_prompt = cfg.get_prompt("soul")
    await brain_instance.init_brain(sys_prompt)
    await heart_instance.init_heart()
    api_key = cfg.get_config_item("api_key")
    api_url = cfg.get_config_item("api_url")
    model = cfg.get_config_item("model")

    start_prompt = cfg.get_prompt("start")


async def brain_processor():
    """
    核心处理协程：主控大脑逻辑。
    负责监听用户输入和系统心脏的事件，并通过模型获取回复输出到界面。
    """
    output("Mozart: ")
    input_info = {"role": "user", "content": start_prompt}
    reply = brain_instance.input_brain(input_info, api_key, api_url, model)
    async for chunk in reply:
        output(chunk)
    output("\r\n")
    while True:
        get_task = asyncio.create_task(context_manager.sensory_queue.get())
        shutdown_task = asyncio.create_task(context_manager.shutdown_event.wait())
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
        reply = brain_instance.input_brain(input_info, api_key, api_url, model)
        async for chunk in reply:
            output(chunk)
        output('\r\n')



async def async_main():
    """
    异步主函数。
    依次调用 setup 初始化资源，并并发运行系统的所有核心模块（大脑、心脏、监听器、本体感受器）。
    最后在系统退出时优雅地关闭资源。
    """
    await setup()
    try:
        await asyncio.gather(brain_processor(),heart_instance.heartbeat_processor(),listener_instance.run(),proprioceptor_instance.run())
    finally:
        await brain_instance.close_brain()
        await heart_instance.close_heart()

if __name__ == "__main__":
    """程序入口。"""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"你干啥了，我怎么被关了，你看看报错：{type(e).__name__}: {e}")
        print(traceback.format_exc())
    finally:
        exit()

