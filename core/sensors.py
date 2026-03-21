from prompt_toolkit import Application
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

from core.context import context_manager

import asyncio
import uiautomation as auto
import win32process
import psutil
import time


class Listener:
    """
    负责处理用户界面（CLI 终端交互）的监听器核心类。
    基于 prompt_toolkit 提供异步的文本展示与输入支持。
    """
    def __init__(self):
        """初始化 Listener 界面的布局与按键绑定事件。"""
        self.output_field = TextArea(text="", read_only=True, scrollbar=True)
        self.input_field = TextArea(height=5, prompt="User: ")
        
        self.container = HSplit([
            self.output_field, 
            Window(height=1, char='='), # 用等号作为中间的分隔线
            self.input_field
        ])
        
        self.layout = Layout(self.container, focused_element=self.input_field)
        self.kb = KeyBindings()
        
        @self.kb.add('c-c')
        def handle_exit(event):
            event.app.exit()
            
        @self.kb.add(Keys.ScrollUp)
        def scroll_up(event):
            self.output_field.buffer.cursor_up(count=3)
            
        @self.kb.add(Keys.ScrollDown)
        def scroll_down(event):
            self.output_field.buffer.cursor_down(count=3)
            
        @self.kb.add(Keys.PageUp)
        def pageup(event):
            self.output_field.buffer.cursor_up(count=10)
            
        @self.kb.add(Keys.PageDown)
        def pagedown(event):
            self.output_field.buffer.cursor_down(count=10)
            
        @self.kb.add('enter')
        def handle_enter(event):
            user_text = self.input_field.text
            if user_text.strip():
                if user_text == "exit":
                    event.app.exit()
                    return
                self.output_field.text += f"You: {user_text}\n"
                self.output_field.buffer.cursor_position = len(self.output_field.text)
                context_manager.sensory_queue.put_nowait({
                    "source": "user",
                    "content": user_text
                })
            self.input_field.text = ""

        self.app = Application(
            layout=self.layout,      
            key_bindings=self.kb,    
            full_screen=True,    # 全屏模式
            mouse_support=True,   
        )

    def system_output(self, text: str):
        """
        同步将系统级信息输出到终端显示界面。
        
        Args:
            text (str): 待输出的字符串。
        """
        self.output_field.text += text + "\n"
        self.output_field.buffer.cursor_position = len(self.output_field.text)
        try:
            self.app.invalidate()
        except Exception:
            pass

    async def run(self):
        """
        异步运行 Listener 应用界面。
        捕获异常，并在退出边界统一清理相关界面与状态。
        """
        try:
            await self.app.run_async()
        except Exception as e:
            raise e
        finally:
            self.output_field.text += "\nMozart: 哎，回见！\n"
            self.output_field.buffer.cursor_position = len(self.output_field.text)
            context_manager.shutdown_event.set()

class Proprioceptor:
    """
    本体感受器类。
    负责系统底层的自动化信息获取，例如光标位置、窗口焦点、前台进程列表等系统级硬件及软件上下文提取。
    """
    def _fetch_ui_info(self):
        """
        同步获取当前悬停 UI 控件上下文及高内存占用的程序列表。
        
        Returns:
            tuple: (控件信息字典, 运行应用列表) 返回包含深层 UI 结构和活动进程。
        """
        _thInit = auto.UIAutomationInitializerInThread()
        _cursor_x, _cursor_y = auto.GetCursorPos()
        _hovered_control = auto.ControlFromPoint(_cursor_x, _cursor_y)
    
        if not _hovered_control:
            return '当前没有感知到任何控件', []
        
        _deep_context = {
            'ui_type': _hovered_control.ControlTypeName,
            'ui_name': _hovered_control.Name,
            'ui_value': '',
            'ui_rectangle': str(_hovered_control.BoundingRectangle),
        }
    
        try:
            _deep_context['ui_value'] = _hovered_control.GetValuePattern().Value
        except Exception:
            pass
        
        _hwnd = _hovered_control.NativeWindowHandle
        if _hwnd:
            _, _pid = win32process.GetWindowThreadProcessId(_hwnd)
            try:
                _process = psutil.Process(_pid)
                _deep_context['app_name'] = _process.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                _deep_context['app_name'] = 'unknown'
    
        _running_apps = []
        _ignore_list = [
            'svchost.exe','system','runtimebroker.exe','conhost.exe','taskhostw.exe','explorer.exe','taskmgr.exe'
        ]
        for _proc in psutil.process_iter(['name', 'memory_percent']):
            try:
                _p_name = _proc.info['name']
                _p_mem = _proc.info['memory_percent']
                if _p_name not in _ignore_list and _p_mem is not None and _p_mem > 0.5:
                    _running_apps.append(_p_name.replace('.exe',''))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return _deep_context,_running_apps

    async def run(self, interval_seconds = 5.0):
        """
        异步轮询运行本体感受器，定期刷新并更新至全局上下文管理器。
        
        Args:
            interval_seconds (float): 默认刷新间隔时长。
        """
        while not context_manager.shutdown_event.is_set():
            try:
                _ui_info,_running_apps = await asyncio.to_thread(self._fetch_ui_info)
                if _ui_info:
                    context_manager.proprioception_info['ui_info'] = _ui_info
                    context_manager.proprioception_info['running_apps'] = _running_apps
                    context_manager.proprioception_info['last_update_time'] = time.time()
            except Exception as e:
                listener_instance.system_output(f"[System] [Proprioceptor] [Error] {e}")
    
            try:
                await asyncio.wait_for(context_manager.shutdown_event.wait(), timeout=interval_seconds)
                break
            except asyncio.TimeoutError:
                pass


listener_instance = Listener()
proprioceptor_instance = Proprioceptor()
