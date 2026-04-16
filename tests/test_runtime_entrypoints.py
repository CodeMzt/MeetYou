import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import desktop_agent.main as desktop_agent_main
import edge_agent.main as edge_agent_main
import main as meetyou_main
import service_runtime.main as service_runtime_main


class RuntimeEntrypointTests(unittest.TestCase):
    def test_root_usage_mentions_split_production_entries(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            meetyou_main._print_usage()
        output = buffer.getvalue()
        self.assertIn("python -m service_runtime", output)
        self.assertIn("python -m desktop_agent", output)
        self.assertIn("python -m edge_agent", output)

    def test_root_main_dispatches_service_mode_to_service_runtime_entry(self):
        with mock.patch("main._run_service_mode") as run_service_mode:
            with mock.patch("sys.argv", ["main.py", "service"]):
                meetyou_main.main()
        run_service_mode.assert_called_once_with("service")

    def test_service_runtime_main_defaults_to_service(self):
        with mock.patch("service_runtime.main.run_runtime_entry") as run_runtime_entry:
            service_runtime_main.main([])
        run_runtime_entry.assert_called_once_with("service")

    def test_desktop_agent_main_runs_runtime(self):
        fake_coroutine = object()
        with mock.patch("desktop_agent.main.setup_logger") as setup_logger:
            with mock.patch("desktop_agent.main.run_desktop_agent", new=mock.Mock(return_value=fake_coroutine)) as run_desktop_agent:
                with mock.patch("desktop_agent.main.asyncio.run") as asyncio_run:
                    desktop_agent_main.main([])
        setup_logger.assert_called_once_with(enable_console=True, component="desktop-agent")
        run_desktop_agent.assert_called_once_with()
        asyncio_run.assert_called_once_with(fake_coroutine)

    def test_edge_agent_main_runs_runtime(self):
        fake_coroutine = object()
        with mock.patch("edge_agent.main.setup_logger") as setup_logger:
            with mock.patch("edge_agent.main.run_edge_agent", new=mock.Mock(return_value=fake_coroutine)) as run_edge_agent:
                with mock.patch("edge_agent.main.asyncio.run") as asyncio_run:
                    edge_agent_main.main([])
        setup_logger.assert_called_once_with(enable_console=True, component="edge-agent")
        run_edge_agent.assert_called_once_with()
        asyncio_run.assert_called_once_with(fake_coroutine)


if __name__ == "__main__":
    unittest.main()
