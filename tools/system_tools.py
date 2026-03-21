import asyncio
import datetime
import psutil

async def exec_sys_cmd(cmd: str):
    """
    异步执行操作系统底层终端命令。
    
    Args:
        cmd (str): 要执行的终端或 shell 命令。
        
    Returns:
        str: 执行的标准输出结果，若失败则返回格式化的标准错误信息。
    """
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
        

async def get_current_system_time():
    """
    异步获取当前系统的准确时间。
    
    Returns:
        str: 格式化的当前日期和时间字符串。
    """
    now_obj = datetime.datetime.now()
    time_str = now_obj.strftime("%Y-%m-%d %H:%M:%S %A")
    return f"当前宿主机系统时间是：{time_str}"


async def get_sys_vitals():
    """
    异步获取当前系统生命体征（主要资源使用情况），如 CPU、内存以及电池信息等。
    
    Returns:
        str: 系统资源占用的格式化报告。
    """
    sys_vitals = {
        'cpu_percent': psutil.cpu_percent(interval=0.1),
        'ram_percent': psutil.virtual_memory().percent,
        'battery_percent': None
    }
    
    # 笔记本，获取电池状态
    _batt = psutil.sensors_battery()
    if _batt:
        sys_vitals['battery_percent'] = _batt.percent
        sys_vitals['is_plugged'] = _batt.power_plugged
        
        return f"cpu占用：{sys_vitals['cpu_percent']}%\
    内存占用：{sys_vitals['ram_percent']}%\
    电池电量：{sys_vitals['battery_percent']}%\
    是否充电：{sys_vitals['is_plugged']}"
    else:
        return f"cpu占用：{sys_vitals['cpu_percent']}%\
    内存占用：{sys_vitals['ram_percent']}%"
