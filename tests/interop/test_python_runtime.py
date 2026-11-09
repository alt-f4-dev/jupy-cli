"""Unit tests of the Python-hosted runtime that do not require Julia."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

from jupy.runtime import JuliaRuntime, RuntimeConfigurationError, find_project_root


class RuntimeTests(unittest.TestCase):
    def test_project_discovery_prefers_nearest(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Project.toml").write_text("", encoding="utf-8")
            nested = root / "work" / "sub"
            nested.mkdir(parents=True)
            self.assertEqual(find_project_root(nested), root)

    def test_import_does_not_start_julia(self) -> None:
        runtime = JuliaRuntime()
        self.assertFalse(runtime.initialized)

    def test_missing_project_fails_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            runtime = JuliaRuntime(project=folder)
            with self.assertRaisesRegex(RuntimeConfigurationError, "no Julia project"):
                runtime.start()

    def test_rejects_module_injection(self) -> None:
        runtime = JuliaRuntime()
        for name in ("", "Base; exit()", "A.B", "Space name", "1Invalid"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    runtime.import_module(name)

    def test_lazy_start_and_cached_module(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Project.toml").write_text("", encoding="utf-8")
            fake_executable = root / "julia"
            fake_executable.write_text("", encoding="utf-8")
            fake_executable.chmod(0o755)
            fake_main = types.SimpleNamespace()
            fake_module = object()
            fake_main.Example = fake_module
            calls = []
            fake_main.seval = lambda expr: calls.append(expr)
            fake_juliacall = types.ModuleType("juliacall")
            fake_juliacall.Main = fake_main
            with patch.dict(sys.modules, {"juliacall": fake_juliacall}), patch.dict(os.environ, {}, clear=True):
                # A preimported JuliaCall cannot be reconfigured, so simulate the first
                # import only after environment selection is validated.
                runtime = JuliaRuntime(project=root, executable=str(fake_executable))
                with self.assertRaisesRegex(RuntimeConfigurationError, "initialized outside Jupy"):
                    runtime.start()
                del sys.modules["juliacall"]
                runtime.start()
                sys.modules["juliacall"] = fake_juliacall
                self.assertTrue(runtime.initialized)
                self.assertEqual(os.environ["PYTHON_JULIACALL_PROJECT"], str(root))
                self.assertIs(runtime.import_module("Example"), fake_module)
                self.assertIs(runtime.import_module("Example"), fake_module)
                self.assertEqual(calls, ["import Example"])


if __name__ == "__main__":
    unittest.main()
