"""
平台适配器抽象基类（插座）。

定义跨平台 API 的统一接口，由各操作系统的具体实现（插头）去填充。
"""

from abc import ABC, abstractmethod


class PlatformAdapter(ABC):
    """
    平台适配器抽象基类。

    所有平台特定操作（UI 感知、进程列表、系统指标、编码转换等）
    必须通过此接口的具体实现来调用。
    """

    @abstractmethod
    def get_ui_context(self) -> dict:
        """
        获取当前光标/焦点处的 UI 控件信息。

        Returns:
            dict: 包含 ui_type, ui_name, ui_value, app_name 等字段。
                  如果不支持则返回 {"status": "not_supported"}。
        """

    @abstractmethod
    def get_running_apps(
        self, ignore_list: list[str] | None = None, mem_threshold: float = 0.5
    ) -> list[str]:
        """
        获取内存占用超过阈值的运行中应用列表。

        Args:
            ignore_list: 要忽略的进程名列表
            mem_threshold: 内存占用百分比阈值

        Returns:
            list[str]: 应用名称列表
        """

    @abstractmethod
    def get_system_vitals(self) -> dict:
        """
        获取系统生命体征（CPU%、RAM%、电池等）。

        Returns:
            dict: 包含 cpu_percent, ram_percent, battery_percent(可选), is_plugged(可选)
        """

    @abstractmethod
    def decode_command_output(self, raw_bytes: bytes) -> str:
        """
        按平台默认编码解码命令行输出字节。

        Args:
            raw_bytes: 命令的原始字节输出

        Returns:
            str: 解码后的文本
        """

    @abstractmethod
    def get_default_shell(self) -> str:
        """
        获取当前平台的默认 shell。

        Returns:
            str: 如 "cmd", "bash", "zsh"
        """
