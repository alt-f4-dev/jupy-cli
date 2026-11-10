"""Phase 1 module identity, failed initialization, and cache atomicity."""

import builtins
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))
import jupy.runtime as runtime


class StabilizationTests(unittest.TestCase):
    def setUp(self):
        self.saved = (runtime._MAIN, runtime._CONFIG, dict(runtime._MODULES),
                      dict(runtime._SOURCES), runtime._FAILED)
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

    def environment(self, root):
        (root / "Project.toml").touch()
        executable = root / "julia"
        executable.touch()
        return runtime.JuliaRuntime(project=root, executable=str(executable))

    def test_default_facade_uses_fast_cached_runtime_but_explicit_facade_validates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            explicit = self.environment(root)
            main = types.SimpleNamespace(Example=object())
            with patch.object(runtime, "_MAIN", main), patch.object(
                runtime, "_CONFIG", (root.resolve(), (root / "julia").resolve())
            ), patch.object(runtime, "_resolve_julia", side_effect=AssertionError(
                "cached default runtime must not resolve Julia again"
            )), patch.object(runtime, "find_project_root", side_effect=AssertionError(
                "cached default runtime must not discover its project again"
            )):
                self.assertIs(runtime.julia.start(), main)
                # Explicitly configured clients may not bypass conflict checks.
                with self.assertRaisesRegex(AssertionError, "must not resolve Julia"):
                    explicit.start()

    def test_failed_native_start_is_poisoned_but_preflight_is_not(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            client = self.environment(root)
            original = builtins.__import__
            calls = []
            def fail_juliacall(name, *args, **kwargs):
                if name == "juliacall":
                    calls.append(1)
                    raise RuntimeError("simulated partial native initialization")
                return original(name, *args, **kwargs)
            with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules):
                sys.modules.pop("juliacall", None)
                with patch("builtins.__import__", side_effect=fail_juliacall):
                    with self.assertRaisesRegex(RuntimeError, "partial native initialization"):
                        client.start()
                    self.assertTrue(runtime._FAILED)
                    self.assertNotIn("PYTHON_JULIACALL_PROJECT", os.environ)
                    with self.assertRaisesRegex(runtime.RuntimeConfigurationError, "restart the Python process"):
                        client.start()
                    self.assertEqual(len(calls), 1)

    def test_preflight_conflict_does_not_poison_process(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            client = self.environment(root)
            with patch.dict(os.environ, {"PYTHON_JULIACALL_PROJECT": str(root / "other")}, clear=True):
                with self.assertRaisesRegex(runtime.RuntimeConfigurationError, "PYTHON_JULIACALL_PROJECT"):
                    client.start()
                self.assertFalse(runtime._FAILED)

    def test_source_identity_alias_collision_and_failed_load(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            client = self.environment(root)
            code = root / "Example.jl"
            code.write_text("module Example end\n", encoding="utf-8")
            other = root / "Other.jl"
            other.write_text("module Other end\n", encoding="utf-8")
            module = object()
            main = types.SimpleNamespace()
            includes = []
            def include(src):
                includes.append(src)
                main.Example = module
            main.include = include
            main.seval = lambda expr: includes.append(expr)
            with patch.object(runtime, "_MAIN", main), patch.object(
                runtime, "_CONFIG", (root.resolve(), (root / "julia").resolve())
            ):
                self.assertIs(client.load("Example", path=code), module)
                self.assertIs(client.load("Example"), module)
                self.assertEqual(includes, [str(code.resolve())])
                with self.assertRaisesRegex(runtime.RuntimeConfigurationError, "cannot change source"):
                    client.load("Example", path=other)
                with self.assertRaisesRegex(runtime.RuntimeConfigurationError, "already registered"):
                    client.load("AnotherName", path=code)
                with self.assertRaises(AttributeError):
                    client.load("DoesNotExist")
                self.assertNotIn("DoesNotExist", runtime._MODULES)

    def test_failed_source_include_not_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            client = self.environment(root)
            source = root / "Broken.jl"
            source.touch()
            main = types.SimpleNamespace(include=lambda path: (_ for _ in ()).throw(ValueError("bad source")))
            with patch.object(runtime, "_MAIN", main), patch.object(
                runtime, "_CONFIG", (root.resolve(), (root / "julia").resolve())
            ):
                with self.assertRaisesRegex(ValueError, "bad source"):
                    client.load("Broken", path=source)
                self.assertNotIn("Broken", runtime._MODULES)
                self.assertNotIn(source.resolve(), runtime._SOURCES)


if __name__ == "__main__":
    unittest.main()
