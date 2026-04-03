import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


class DocumentToolsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._workspace = tempfile.TemporaryDirectory()
        self._outside = tempfile.TemporaryDirectory()
        self.workspace_path = Path(self._workspace.name)
        self.outside_path = Path(self._outside.name)
        self.tools = DocumentTools(_FakeModeManager([self.workspace_path]))

    async def asyncTearDown(self):
        self._outside.cleanup()
        self._workspace.cleanup()

    async def test_analyze_workspace_detects_structure(self):
        (self.workspace_path / "src").mkdir()
        (self.workspace_path / "assets").mkdir()
        (self.workspace_path / "package.json").write_text('{"name":"demo"}', encoding="utf-8")
        (self.workspace_path / "src" / "main.tsx").write_text("export default 'ok'\n", encoding="utf-8")
        (self.workspace_path / "assets" / "logo.png").write_bytes(b"\x89PNGdemo")

        raw = await self.tools.analyze_workspace(str(self.workspace_path), depth=3, focus="src")
        payload = json.loads(raw)
        entry_clues = {item.replace("\\", "/") for item in payload["summary"]["entry_clues"]}
        focus_hits = {item.replace("\\", "/") for item in payload["summary"]["focus_hits"]}
        tree_preview = [item.replace("\\", "/") for item in payload["summary"]["tree_preview"]]

        self.assertEqual(payload["status"], "ok")
        self.assertIn("package.json", payload["summary"]["manifest_files"])
        self.assertIn("src/main.tsx", entry_clues)
        self.assertIn("src/main.tsx", focus_hits)
        self.assertTrue(any(item.endswith("src/") for item in tree_preview))

    async def test_read_local_documents_supports_common_formats(self):
        note_path = self.workspace_path / "note.txt"
        json_path = self.workspace_path / "config.json"
        csv_path = self.workspace_path / "rows.csv"
        html_path = self.workspace_path / "page.html"

        note_path.write_text("alpha\n\nbeta", encoding="utf-8")
        json_path.write_text('{"enabled": true, "name": "demo"}', encoding="utf-8")
        csv_path.write_text("name,score\nalex,95\nsam,88\n", encoding="utf-8")
        html_path.write_text("<html><body><h1>Hello</h1><p>World</p></body></html>", encoding="utf-8")

        raw = await self.tools.read_local_documents(
            [str(note_path), str(json_path), str(csv_path), str(html_path)],
            goal="summarize",
        )
        payload = json.loads(raw)

        self.assertEqual(payload["document_count"], 4)
        self.assertEqual(payload["readable_count"], 4)
        document_types = {item["type"] for item in payload["documents"]}
        self.assertEqual(document_types, {"text", "json", "csv", "html"})

    async def test_write_local_document_preview_and_trust_guard(self):
        trusted_path = self.workspace_path / "docs" / "report.md"
        outside_path = self.outside_path / "report.md"

        preview = json.loads(
            await self.tools.write_local_document(
                str(trusted_path),
                "# Draft\n",
                preview=True,
            )
        )
        written = json.loads(
            await self.tools.write_local_document(
                str(trusted_path),
                "# Final\n",
                preview=False,
            )
        )
        blocked = json.loads(
            await self.tools.write_local_document(
                str(outside_path),
                "# Outside\n",
                preview=False,
            )
        )

        self.assertEqual(preview["status"], "preview")
        self.assertEqual(written["status"], "written")
        self.assertEqual(trusted_path.read_text(encoding="utf-8"), "# Final\n")
        self.assertEqual(blocked["status"], "blocked_untrusted_path")

    async def test_rewrite_local_document_requires_replacement_then_updates_section(self):
        target = self.workspace_path / "summary.md"
        target.write_text("# Report\n\n## Summary\nOld summary\n\n## Next\nOld next\n", encoding="utf-8")

        needs_content = json.loads(
            await self.tools.rewrite_local_document(
                str(target),
                instructions="Refresh the summary",
                section_selector="Summary",
                preview=True,
            )
        )
        preview = json.loads(
            await self.tools.rewrite_local_document(
                str(target),
                instructions="Refresh the summary",
                section_selector="Summary",
                replacement_content="New summary",
                preview=True,
            )
        )
        written = json.loads(
            await self.tools.rewrite_local_document(
                str(target),
                instructions="Refresh the summary",
                section_selector="Summary",
                replacement_content="New summary",
                preview=False,
            )
        )

        self.assertEqual(needs_content["status"], "needs_replacement_content")
        self.assertEqual(preview["status"], "preview")
        self.assertEqual(written["status"], "written")
        self.assertIn("## Summary\nNew summary", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
