import json
from core.sensors import listener_instance

_CONFIG_FILE_PATH = "user/config.json"
_MCP_SERVER_CONFIG_PATH = "user/mcp_servers.json"

class ConfigManager:
    """
    配置管理器类，负责加载和管理全局通用配置以及 MCP 服务器配置。
    """
    def __init__(self, config_file_path=_CONFIG_FILE_PATH):
        """
        初始化 ConfigManager 实例并加载配置文件。
        
        Args:
            config_file_path (str): 配置文件路径，默认为 _CONFIG_FILE_PATH。
        """
        self.config_file_path = config_file_path
        self.mcp_server_config_path = _MCP_SERVER_CONFIG_PATH
        try:
            with open(self.config_file_path, "r", encoding="utf-8") as f:
                self.__config = json.load(f)

        except Exception as e:
            listener_instance.system_output(f"Error loading config file {self.config_file_path}: {e}")
            self.__config = {}

        try:
            with open(self.mcp_server_config_path, "r", encoding="utf-8") as f:
                self.__mcp_server_config = json.load(f)
        except Exception as e:
            listener_instance.system_output(f"Error loading mcp server config file {self.mcp_server_config_path}: {e}")
            self.__mcp_server_config = {}


    def get_prompt(self, prompt_name):
        """
        根据提示词名称，从配置文件读取对应路径并加载提示词内容。
        
        Args:
            prompt_name (str): 提示词名称标识（如 'soul', 'start')。
            
        Returns:
            str: 提取的提示词文本内容，读取失败则返回空字符串。
        """
        try:
            with open(self.get_config_item(f"{prompt_name}_path"), "r", encoding="utf-8") as f:
                prompt = f.read()
        except Exception as e:
            listener_instance.system_output(f"Error loading prompt file {self.get_config_item(f'{prompt_name}_path')}: {e}")
            prompt = ""
        return prompt
    
    def get_config_item(self, item_name):
        """
        获取指定的配置项值。
        
        Args:
            item_name (str): 配置项的键名。
            
        Returns:
            Any: 配置项的值。若不存在或发生异常则返回 None。
        """
        try:
            return self.__config[item_name]
        except Exception as e:
            listener_instance.system_output(f"Error getting config item {item_name}: {e}")
            return None
    
    def update_config_item(self, item_name, item_value):
        """
        更新指定的配置项，并将最新的配置持久化到文件中。
        
        Args:
            item_name (str): 待更新的配置项名称。
            item_value (Any): 配置项的新值。
        """
        try:
            self.__config[item_name] = item_value
            with open(self.config_file_path, "w") as f:
                json.dump(self.__config, f, indent=4)
        except Exception as e:
            listener_instance.system_output(f"Error updating config item {item_name}: {e}")
    
    def get_mcp_servers(self):
        """
        获取已配置的 MCP 服务器列表参数。
        
        Returns:
            dict: MCP 服务器的配置信息字典，如果没配置则返回空字典。
        """
        try:
            return self.__mcp_server_config.get("mcpServers",{})
        except Exception as e:
            listener_instance.system_output(f"Error getting mcp servers: {e}")
            return {}

cfg = ConfigManager()   


from tools.system_tools import get_current_system_time
from tools.system_tools import exec_sys_cmd
from tools.system_tools import get_sys_vitals
from tools.memory import memory_instance
from core.context import context_manager

class ToolsManager:
    """
    系统工具管理器类。统一管理系统内所有被支持的功能函数，以及负责其 Schema 加载。
    """
    def __init__(self):
        """
        初始化 ToolsManager，装载默认支持的方法引用。
        """
        self.tools = {}
        self.tools_schema_list = []
        self.supported_funcs = {
            'exec_sys_cmd': exec_sys_cmd,
            'save_memory': memory_instance.save_memory,
            'recall_memory': memory_instance.recall_memory,
            'get_current_system_time': get_current_system_time,
            'update_context': context_manager.update_context,
            'get_sys_vitals': get_sys_vitals,
        }

    async def init_tools(self, tools_schema_path: str):
        """
        根据给定的路径异步初始化所有的工具 Schema 列表。
        
        Args:
            tools_schema_path (str): JSON 格式的工具结构声明文件路径。
        """
        with open(tools_schema_path, "r",encoding="utf-8") as f:
            self.tools_schema_list = json.load(f)

tools_manager = ToolsManager()
