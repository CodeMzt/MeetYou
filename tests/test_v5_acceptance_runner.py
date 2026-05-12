from __future__ import annotations

import py_compile
import unittest
from pathlib import Path


class V5AcceptanceRunnerTests(unittest.TestCase):
    def test_v5_real_acceptance_runner_compiles(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "v5_real_acceptance.py"
        py_compile.compile(str(script_path), doraise=True)


if __name__ == "__main__":
    unittest.main()
