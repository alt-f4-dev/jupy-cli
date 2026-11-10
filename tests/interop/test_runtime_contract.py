"""Process-global runtime contract tests without starting Julia."""

import builtins
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))
import jupy.runtime as runtime


class GlobalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.saved = (runtime._MAIN, runtime._CONFIG, dict(runtime._MODULES), dict(runtime._SOURCES), runtime._FAILED)
        runtime._MAIN = None
        runtime._CONFIG = None
        runtime._MODULES.clear()
        runtime._SOURCES.clear()
        runtime._FAILED = False

    def tearDown(self):
        runtime._MAIN, runtime._CONFIG, modules, sources, failed = self.saved
        runtime._MODULES.clear()
        runtime._MODULES.update(modules)
        runtime._SOURCES.clear()
        runtime._SOURCES.update(sources)
        runtime._FAILED = failed

    def test_single_initialization_and_conflicts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            a, b = root / "a", root / "b"
            a.mkdir(); b.mkdir()
            (a / "Project.toml").touch()
            (b / "Project.toml").touch()
            exe = root / "julia"; exe.touch()
            other = root / "other-julia"; other.touch()
            fake_module = object()
            fake_main = types.SimpleNamespace(Example=fake_module)
            imports = []
            fake_main.seval = lambda code: imports.append(code)
            fake_juliacall = types.ModuleType("juliacall")
            fake_juliacall.Main = fake_main
            original_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if name == "juliacall":
                    return fake_juliacall
                return original_import(name, *args, **kwargs)

            with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules):
                sys.modules.pop("juliacall", None)
                with patch("builtins.__import__", side_effect=fake_import):
                    first = runtime.JuliaRuntime(project=a, executable=str(exe))
                    second = runtime.JuliaRuntime(project=a, executable=str(exe))
                    self.assertIs(first.start(), fake_main)
                    self.assertIs(second.start(), fake_main)
                    self.assertIs(first.load("Example"), fake_module)
                    self.assertIs(second.load("Example"), fake_module)
                    self.assertEqual(imports, ["import Example"])
                    self.assertEqual(Path(os.environ["PYTHON_JULIACALL_PROJECT"]).resolve(), a.resolve())
                    self.assertEqual(Path(os.environ["PYTHON_JULIACALL_EXE"]).resolve(), exe.resolve())
                    with self.assertRaisesRegex(runtime.RuntimeConfigurationError, "cannot switch"):
                        runtime.JuliaRuntime(project=b, executable=str(exe)).start()
                    with self.assertRaisesRegex(runtime.RuntimeConfigurationError, "cannot switch"):
                        runtime.JuliaRuntime(project=a, executable=str(other)).start()

    def test_rejects_preexisting_juliacall(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / "Project.toml").touch()
            exe = root / "julia"; exe.touch()
            with patch.dict(sys.modules, {"juliacall": types.ModuleType("juliacall")}):
                with self.assertRaisesRegex(runtime.RuntimeConfigurationError, "before Jupy"):
                    runtime.JuliaRuntime(project=root, executable=str(exe)).start()

    def test_concurrent_start_only_imports_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / "Project.toml").touch()
            exe = root / "julia"; exe.touch()
            fake = types.ModuleType("juliacall"); fake.Main = types.SimpleNamespace()
            calls = []
            original_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if name == "juliacall":
                    calls.append(1)
                    return fake
                return original_import(name, *args, **kwargs)

            with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules):
                sys.modules.pop("juliacall", None)
                with patch("builtins.__import__", side_effect=fake_import):
                    errors = []
                    def start():
                        try:
                            runtime.JuliaRuntime(project=root, executable=str(exe)).start()
                        except Exception as exc:
                            errors.append(exc)
                    threads = [threading.Thread(target=start) for _ in range(8)]
                    for thread in threads: thread.start()
                    for thread in threads: thread.join()
                    self.assertEqual(errors, [])
                    self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
