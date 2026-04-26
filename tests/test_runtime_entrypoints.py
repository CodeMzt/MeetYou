import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import desktop_client.main as desktop_client_main
import edge_client.main as edge_client_main
import main as meetyou_main
import service_runtime.main as service_runtime_main


class RuntimeEntrypointTests(unittest.TestCase):
    def test_root_usage_mentions_split_production_entries(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            meetyou_main._print_usage()
        output = buffer.getvalue()
        self.assertIn("python -m service_runtime", output)
        self.assertIn("python -m desktop_client", output)
        self.assertIn("python -m edge_client", output)

    def test_root_main_dispatches_service_mode_to_service_runtime_entry(self):
        with mock.patch("main._run_service_mode") as run_service_mode:
            with mock.patch("sys.argv", ["main.py", "service"]):
                meetyou_main.main()
        run_service_mode.assert_called_once_with("service")

    def test_service_runtime_main_defaults_to_service(self):
        with mock.patch("service_runtime.main.run_runtime_entry") as run_runtime_entry:
            service_runtime_main.main([])
        run_runtime_entry.assert_called_once_with("service")

    def test_service_runtime_entry_exits_nonzero_on_start_failure(self):
        class _FailingRuntime:
            def __init__(self, command):
                self.command = command

            async def run(self):
                raise RuntimeError("boom")

        with mock.patch("service_runtime.main.setup_logger"):
            with mock.patch("service_runtime.main.ServiceRuntime", _FailingRuntime):
                with self.assertRaises(SystemExit) as captured:
                    service_runtime_main.run_runtime_entry("service")

        self.assertEqual(captured.exception.code, 1)

    def test_desktop_client_main_runs_runtime(self):
        fake_coroutine = object()
        with mock.patch("desktop_client.main.setup_logger") as setup_logger:
            with mock.patch("desktop_client.main.run_desktop_client", new=mock.Mock(return_value=fake_coroutine)) as run_desktop_client:
                with mock.patch("desktop_client.main.asyncio.run") as asyncio_run:
                    desktop_client_main.main([])
        setup_logger.assert_called_once_with(enable_console=True, component="desktop-client")
        run_desktop_client.assert_called_once_with()
        asyncio_run.assert_called_once_with(fake_coroutine)

    def test_edge_client_main_runs_runtime(self):
        fake_coroutine = object()
        with mock.patch("edge_client.main.setup_logger") as setup_logger:
            with mock.patch("edge_client.main.run_edge_client", new=mock.Mock(return_value=fake_coroutine)) as run_edge_client:
                with mock.patch("edge_client.main.asyncio.run") as asyncio_run:
                    edge_client_main.main([])
        setup_logger.assert_called_once_with(enable_console=True, component="edge-client")
        run_edge_client.assert_called_once_with()
        asyncio_run.assert_called_once_with(fake_coroutine)


if __name__ == "__main__":
    unittest.main()
