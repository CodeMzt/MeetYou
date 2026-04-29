import unittest
import sys
import os
import types
import asyncio
import io
import tempfile

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

mcp_module = types.ModuleType("mcp")
mcp_client_module = types.ModuleType("mcp.client")
mcp_client_session_module = types.ModuleType("mcp.client.session")
mcp_client_stdio_module = types.ModuleType("mcp.client.stdio")
mcp_client_session_module.RuntimeSession = object
mcp_client_stdio_module.StdioServerParameters = object
mcp_client_stdio_module.stdio_client = object
sys.modules.setdefault("mcp", mcp_module)
sys.modules.setdefault("mcp.client", mcp_client_module)
sys.modules.setdefault("mcp.client.session", mcp_client_session_module)
sys.modules.setdefault("mcp.client.stdio", mcp_client_stdio_module)

from tools.mcp import MCPManager, _LoggerWriter, _compose_server_env, _resolve_server_process


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
            merged = _compose_server_env("python", {"npm_config_cache": "cache-path"})
        finally:
            os.environ.pop("MEETYOU_TEST_PARENT_ENV", None)

        self.assertEqual(merged["MEETYOU_TEST_PARENT_ENV"], "parent")
        self.assertEqual(merged["npm_config_cache"], "cache-path")

    def test_node_launchers_get_writable_cache_defaults(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            previous = os.environ.get("MEETYOU_MCP_NPM_CACHE_DIR")
            os.environ["MEETYOU_MCP_NPM_CACHE_DIR"] = os.path.join(tmp_dir, "npm-cache")
            try:
                merged = _compose_server_env("npx", {})
                cache_exists = os.path.isdir(merged["NPM_CONFIG_CACHE"])
                xdg_exists = os.path.isdir(merged["XDG_CACHE_HOME"])
                home_exists = os.path.isdir(merged["HOME"])
            finally:
                if previous is None:
                    os.environ.pop("MEETYOU_MCP_NPM_CACHE_DIR", None)
                else:
                    os.environ["MEETYOU_MCP_NPM_CACHE_DIR"] = previous

        self.assertTrue(cache_exists)
        self.assertEqual(merged["NPM_CONFIG_CACHE"], merged["npm_config_cache"])
        self.assertTrue(xdg_exists)
        self.assertTrue(home_exists)

    def test_known_auth_env_defaults_prevent_blind_startup(self):
        previous = os.environ.get("TAVILY_API_KEY")
        os.environ.pop("TAVILY_API_KEY", None)
        try:
            manager = MCPManager()
            asyncio.run(
                manager.init_mcp_servers(
                    {
                        "tavily_web": {
                            "command": "npx",
                            "args": ["-y", "tavily-mcp@0.1.3"],
                            "enabled": True,
                        }
                    }
                )
            )
        finally:
            if previous is None:
                os.environ.pop("TAVILY_API_KEY", None)
            else:
                os.environ["TAVILY_API_KEY"] = previous

        diagnostic = manager.get_server_diagnostic("tavily_web")
        self.assertEqual(diagnostic["status"], "requires_auth")
        self.assertEqual(diagnostic["missing_auth"], ["TAVILY_API_KEY"])

    def test_logger_writer_exposes_fileno_from_fallback_stream(self):
        class _FallbackStream:
            def fileno(self):
                return 123

        writer = _LoggerWriter("filesystem_tools", fallback_stream=_FallbackStream())

        self.assertEqual(writer.fileno(), 123)

    def test_logger_writer_raises_when_fallback_stream_has_no_fileno(self):
        writer = _LoggerWriter("filesystem_tools", fallback_stream=object())

        with self.assertRaises(io.UnsupportedOperation):
            writer.fileno()


if __name__ == "__main__":
    unittest.main()
