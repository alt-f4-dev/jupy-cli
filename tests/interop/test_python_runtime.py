"""Unit tests of Python-hosted runtime without starting Julia."""

from __future__ import annotations

import builtins
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
        self.assertFalse(JuliaRuntime().initialized)

    def test_missing_project_fails_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeConfigurationError, "no Julia project"):
                JuliaRuntime(project=folder).start()

    def test_rejects_invalid_module_names(self) -> None:
        runtime = JuliaRuntime()
        for name in ("", "Base; exit()", "A.B", "Space name", "1Invalid"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                runtime.import_module(name)

    def test_rejects_preinitialized_juliacall(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Project.toml").write_text("", encoding="utf-8")
            exe = root / "julia"
            exe.write_text("", encoding="utf-8")
            with patch.dict(sys.modules, {"juliacall": types.ModuleType("juliacall")}):
                with self.assertRaisesRegex(RuntimeConfigurationError, "initialized outside Jupy"):
                    JuliaRuntime(project=root, executable=str(exe)).start()

    def test_lazy_start_and_cached_module(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Project.toml").write_text("", encoding="utf-8")
            exe = root / "julia"
            exe.write_text("", encoding="utf-8")
            fake_main = types.SimpleNamespace()
            fake_module = object()
            fake_main.Example = fake_module
            calls = []
            fake_main.seval = lambda expr: calls.append(expr)
            fake_juliacall = types.ModuleType("juliacall")
            fake_juliacall.Main = fake_main
            real_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if name == "juliacall":
                    return fake_juliacall
                return real_import(name, *args, **kwargs)

            with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules):
                sys.modules.pop("juliacall", None)
                with patch("builtins.__import__", side_effect=fake_import):
                    runtime = JuliaRuntime(project=root, executable=str(exe))
                    self.assertIs(runtime.start(), fake_main)
                    self.assertIs(runtime.start(), fake_main)
                    self.assertTrue(runtime.initialized)
                    self.assertEqual(os.environ["PYTHON_JULIACALL_PROJECT"], str(root))
                    self.assertIs(runtime.import_module("Example"), fake_module)
                    self.assertIs(runtime.import_module("Example"), fake_module)
                    self.assertEqual(calls, ["import Example"])


if __name__ == "__main__":
    unittest.main()
