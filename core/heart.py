import asyncio
from core.config_manage import ConfigManager
import aiohttp

__heart_prompt = '''
[Heartbeat]这是系统的心跳机制，严格按照如下要求进行!回复且只能回复[HEARTBEAT_OK]
'''
__heart_http_session = None
__heart_interval = 60
__heart_api_key = ""
__heart_api_url = ""
__heart_model = ""

async def init_heart():
    global __heart_prompt, __heart_interval, __heart_api_key, __heart_api_url, __heart_model
    cfg = ConfigManager()

    try:
        __heart_prompt = cfg.get_prompt("heartbeat")
    except Exception as e:
        print(f"Error loading heartbeat prompt: {e}")

    try:
        __heart_interval = int(cfg.get_config_item("heartbeat_interval") or __heart_interval)
    except Exception as e:
        print(f"Error loading heartbeat interval: {e}")

    __heart_api_url = cfg.get_config_item("heartbeat_api_url") or __heart_api_url
    __heart_api_key = cfg.get_config_item("heartbeat_api_key") or __heart_api_key
    __heart_model = cfg.get_config_item("heart_model") or __heart_model

    global __heart_http_session
    __heart_http_session = aiohttp.ClientSession()

async def close_heart():
    global __heart_http_session
    if __heart_http_session:
        await __heart_http_session.close()
        __heart_http_session = None

async def heartbeat_cycle():
    while True:
        if __heart_http_session is None:
            raise Exception("Heart HTTP session is not initialized. Call init_heart first.")

        if not __heart_api_url or not __heart_model:
            print("Heartbeat config missing: heartbeat_api_url or heart_model")
            await asyncio.sleep(__heart_interval)
            continue

        headers = {}
        if __heart_api_key:
            headers = {
                "Authorization": f"Bearer {__heart_api_key}",
                "Content-Type": "application/json",
            }

        payload = {
            "model": __heart_model,
            "messages": [{"role": "user", "content": __heart_prompt}],
            "stream": False,
        }

        try:
            async with __heart_http_session.post(__heart_api_url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.json()
                message = data.get("message") or {}
                output = (message.get("content") or "").strip()
                if output and output not in ("[HEARTBEAT_OK]", "HEARTBEAT_OK"):
                    print(f"Heartbeat failed with response: {output}")
        except Exception as e:
            print(f"Heartbeat error: {e}")

        await asyncio.sleep(__heart_interval)
