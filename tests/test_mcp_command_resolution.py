import unittest
import sys
import os
import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

mcp_module = types.ModuleType("mcp")
mcp_client_module = types.ModuleType("mcp.client")
mcp_client_session_module = types.ModuleType("mcp.client.session")
mcp_client_stdio_module = types.ModuleType("mcp.client.stdio")
mcp_client_session_module.ClientSession = object
mcp_client_stdio_module.StdioServerParameters = object
mcp_client_stdio_module.stdio_client = object
sys.modules.setdefault("mcp", mcp_module)
sys.modules.setdefault("mcp.client", mcp_client_module)
sys.modules.setdefault("mcp.client.session", mcp_client_session_module)
sys.modules.setdefault("mcp.client.stdio", mcp_client_stdio_module)

from tools.mcp import _compose_server_env, _resolve_server_process


class MCPCommandResolutionTests(unittest.TestCase):
    def test_wraps_cmd_with_cmd_exe_on_windows(self):
        command, args = _resolve_server_process(
            "npx.cmd",
            ["-y", "@playwright/mcp@latest"],
            os_name="nt",
            comspec=r"C:\Windows\System32\cmd.exe",
        )

        self.assertEqual(command, r"C:\Windows\System32\cmd.exe")
        self.assertEqual(
            args,
            ["/d", "/c", "npx.cmd", "-y", "@playwright/mcp@latest"],
        )

    def test_keeps_regular_executable_unchanged(self):
        command, args = _resolve_server_process(
            "python.exe",
            ["main.py"],
            os_name="nt",
            comspec=r"C:\Windows\System32\cmd.exe",
        )

        self.assertEqual(command, "python.exe")
        self.assertEqual(args, ["main.py"])

    def test_merges_server_env_with_process_env(self):
        os.environ["MEETYOU_TEST_PARENT_ENV"] = "parent"
        try:
            merged = _compose_server_env({"npm_config_cache": "cache-path"})
        finally:
            os.environ.pop("MEETYOU_TEST_PARENT_ENV", None)

        self.assertEqual(merged["MEETYOU_TEST_PARENT_ENV"], "parent")
        self.assertEqual(merged["npm_config_cache"], "cache-path")


if __name__ == "__main__":
    unittest.main()
