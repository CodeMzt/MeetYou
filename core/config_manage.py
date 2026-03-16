import json

_config_file_path = "config.json"

class ConfigManager:
    def __init__(self, config_file_path=_config_file_path):
        self.config_file_path = config_file_path
        try:
            with open(self.config_file_path, "r") as f:
                self.__config = json.load(f)
        except Exception as e:
            print(f"Error loading config file {self.config_file_path}: {e}")
            self.__config = {}


    def get_prompt(self, prompt_name):
        try:
            with open(self.get_config_item(f"{prompt_name}_path"), "r", encoding="utf-8") as f:
                prompt = f.read()
        except Exception as e:
            print(f"Error loading prompt file {self.get_config_item(f'{prompt_name}_path')}: {e}")
            prompt = ""
        return prompt
    
    def get_config_item(self, item_name):
        try:
            return self.__config[item_name]
        except Exception as e:
            print(f"Error getting config item {item_name}: {e}")
            return None
    
    def update_config_item(self, item_name, item_value):
        try:
            self.__config[item_name] = item_value
            with open(self.config_file_path, "w") as f:
                json.dump(self.__config, f, indent=4)
        except Exception as e:
            print(f"Error updating config item {item_name}: {e}")
