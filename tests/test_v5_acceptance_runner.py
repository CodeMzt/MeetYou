from __future__ import annotations

import py_compile
import unittest
from pathlib import Path

from scripts.v5_real_acceptance import is_acceptance_project, is_acceptance_thread


class V5AcceptanceRunnerTests(unittest.TestCase):
    def test_v5_real_acceptance_runner_compiles(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "v5_real_acceptance.py"
        py_compile.compile(str(script_path), doraise=True)

    def test_cleanup_markers_match_acceptance_resources(self) -> None:
        self.assertTrue(is_acceptance_project({"title": "V5 real acceptance marker", "metadata": {}}))
        self.assertTrue(is_acceptance_project({"title": "Other", "metadata": {"acceptance": "v5_real_acceptance"}}))
        self.assertFalse(is_acceptance_project({"title": "普通项目", "metadata": {}}))
        self.assertTrue(is_acceptance_thread({"title": "V5 acceptance thread marker"}))
        self.assertFalse(is_acceptance_thread({"title": "普通对话"}))


if __name__ == "__main__":
    unittest.main()
