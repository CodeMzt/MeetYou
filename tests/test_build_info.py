from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from build_info import load_build_info, resolve_build_info, write_build_info


class BuildInfoTests(unittest.TestCase):
    def test_load_build_info_reads_known_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "build_info.json"
            write_build_info(
                path,
                {
                    "git_commit": "abc123",
                    "branch": "feat/test",
                    "build_time": "2026-04-24T00:00:00Z",
                    "component": "core",
                    "package_version": "1.2.3",
                    "ignored": "secret",
                },
            )
            loaded = load_build_info(path, component="core", package_version="0.0.0")

        self.assertEqual(loaded["git_commit"], "abc123")
        self.assertEqual(loaded["branch"], "feat/test")
        self.assertEqual(loaded["component"], "core")
        self.assertEqual(loaded["package_version"], "1.2.3")
        self.assertNotIn("ignored", loaded)

    def test_load_build_info_falls_back_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            loaded = load_build_info(Path(tmp_dir) / "missing.json", component="desktop_backend", package_version="9.9.9")

        self.assertEqual(loaded["component"], "desktop_backend")
        self.assertEqual(loaded["package_version"], "9.9.9")
        self.assertTrue(loaded["git_commit"])
        self.assertTrue(loaded["branch"])

    def test_resolve_build_info_allows_override(self):
        payload = resolve_build_info(
            component="ui",
            package_version="1.0.0",
            git_commit="manual-commit",
            branch="manual-branch",
            build_time="2026-04-24T01:02:03Z",
        )
        self.assertEqual(
            payload,
            {
                "git_commit": "manual-commit",
                "branch": "manual-branch",
                "build_time": "2026-04-24T01:02:03Z",
                "component": "ui",
                "package_version": "1.0.0",
            },
        )


if __name__ == "__main__":
    unittest.main()
