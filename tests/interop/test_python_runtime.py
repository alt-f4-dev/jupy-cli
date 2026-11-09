"""Lightweight runtime tests: no Julia process required."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))
from jupy.runtime import JuliaRuntime, RuntimeConfigurationError, find_project_root


class RuntimeTests(unittest.TestCase):
    def test_project_discovery_prefers_nearest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Project.toml").touch()
            nested = root / "nested" / "child"
            nested.mkdir(parents=True)
            self.assertEqual(find_project_root(nested), root.resolve())

    def test_import_is_lazy(self):
        self.assertFalse(JuliaRuntime(project=".", executable="missing")._project is None)

    def test_missing_project_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeConfigurationError, "no Julia project"):
                JuliaRuntime(project=folder).start()

    def test_invalid_module_names_rejected_before_start(self):
        runtime = JuliaRuntime()
        for name in ("", "Base; exit()", "A.B", "Space name", "1Invalid"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                runtime.import_module(name)


if __name__ == "__main__":
    unittest.main()
