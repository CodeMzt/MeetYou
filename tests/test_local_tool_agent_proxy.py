from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

from tools import system_tools
from tools.document_tools import DocumentTools


class _FakeModeManager:
    def __init__(self, trusted_roots):
        self._trusted_roots = [str(Path(root).resolve()) for root in trusted_roots]

    def get_document_parser_config(self):
        return {
            "max_file_bytes": 2_000_000,
            "max_total_chars": 24_000,
            "max_chunks_per_document": 12,
            "enable_ocr": False,
        }

    def get_trusted_write_roots(self):
        return list(self._trusted_roots)

    def is_trusted_write_path(self, path_value: str) -> bool:
        candidate = str(Path(path_value).resolve())
        for root in self._trusted_roots:
            if candidate == root or candidate.startswith(f"{root}{os.sep}"):
                return True
        return False


class _FakeAgentDispatcher:
    def __init__(self):
        self.calls = []

    async def dispatch_local_capability(self, **kwargs):
        self.calls.append(dict(kwargs))
        suffix = kwargs["capability_suffix"]
        arguments = kwargs.get("arguments", {})
        if suffix == "shell.exec":
            return {"stdout": "123", "summary": "123"}
        if suffix == "file.read":
            return {
                "summary": arguments.get("path", ""),
                "content": '{"enabled": true}' if str(arguments.get("path", "")).endswith('.json') else 'alpha\n\nbeta',
                "size_bytes": 12,
            }
        if suffix == "file.write":
            return {"summary": arguments.get("path", ""), "bytes_written": len(str(arguments.get("content", "")).encode("utf-8"))}
        if suffix == "workspace.analyze":
            return {
                "tool": "analyze_workspace",
                "path": arguments.get("path", ""),
                "status": "ok",
                "focus": arguments.get("focus", ""),
                "summary": {
                    "directory_count": 1,
                    "file_count": 1,
                    "extension_counts": [{"extension": ".tsx", "count": 1}],
                    "manifest_files": ["package.json"],
                    "entry_clues": ["src/main.tsx"],
                    "large_files": [],
                    "binary_files": [],
                    "focus_hits": ["src/main.tsx"],
                    "tree_preview": ["src/", "  main.tsx"],
                },
                "answer_style": "demo",
            }
        raise AssertionError(f"unexpected capability suffix: {suffix}")


class LocalToolAgentProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_exec_sys_cmd_uses_agent_dispatcher(self):
        dispatcher = _FakeAgentDispatcher()
        system_tools.set_agent_dispatcher(dispatcher)
        try:
            result = await system_tools.exec_sys_cmd('python -c "print(123)"', session_id='sess_1')
        finally:
            system_tools.set_agent_dispatcher(None)

        self.assertEqual(result, '123')
        self.assertEqual(dispatcher.calls[0]['capability_suffix'], 'shell.exec')

    async def test_document_tools_use_agent_dispatcher_for_read_and_write(self):
        with tempfile.TemporaryDirectory() as trusted_dir:
            dispatcher = _FakeAgentDispatcher()
            tools = DocumentTools(_FakeModeManager([trusted_dir]), agent_dispatcher=dispatcher)
            target = Path(trusted_dir) / 'report.md'
            json_target = Path(trusted_dir) / 'config.json'

            read_payload = json.loads(await tools.read_local_documents([str(json_target)], session_id='sess_1'))
            write_payload = json.loads(
                await tools.write_local_document(
                    str(target),
                    '# Final\n',
                    preview=False,
                    session_id='sess_1',
                )
            )

            self.assertEqual(read_payload['documents'][0]['type'], 'json')
            self.assertEqual(write_payload['status'], 'written')
            self.assertEqual(dispatcher.calls[0]['capability_suffix'], 'file.read')
            self.assertEqual(dispatcher.calls[1]['capability_suffix'], 'file.write')

    async def test_document_tools_use_agent_dispatcher_for_workspace_analysis(self):
        with tempfile.TemporaryDirectory() as trusted_dir:
            dispatcher = _FakeAgentDispatcher()
            tools = DocumentTools(_FakeModeManager([trusted_dir]), agent_dispatcher=dispatcher)

            payload = json.loads(await tools.analyze_workspace(str(Path(trusted_dir)), session_id='sess_1', focus='src'))

            self.assertEqual(payload['status'], 'ok')
            self.assertEqual(dispatcher.calls[0]['capability_suffix'], 'workspace.analyze')
            self.assertEqual(dispatcher.calls[0]['arguments']['focus'], 'src')
