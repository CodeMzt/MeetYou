import asyncio

async def exec_sys_cmd(cmd: str):
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode == 0:
        try:
            return stdout.decode("gbk", "strict").strip()
        except UnicodeDecodeError:
            return stdout.decode("utf-8", "strict").strip()
    else:
        try:
            return f"命令执行失败，错误信息：{stderr.decode('gbk', 'strict').strip()}"
        except UnicodeDecodeError:
            return f"命令执行失败，错误信息：{stderr.decode('utf-8', 'strict').strip()}"
        
import datetime

async def get_current_system_time():
    now_obj = datetime.datetime.now()
    time_str = now_obj.strftime("%Y-%m-%d %H:%M:%S %A")
    return f"当前宿主机系统时间是：{time_str}"
