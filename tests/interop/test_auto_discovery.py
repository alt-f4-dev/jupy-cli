"""Automatic discovery and annotation guards: no contract files required."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
import jupy.discovery as discovery
from jupy.discovery import (
    annotation_guard, checked_module, inspect_python, invalidate,
    manifest_json, wire_python,
)
from jupy.contracts import ContractViolation


def fixture_module():
    module = types.ModuleType("automatic_fixture")
    def typed(value: int) -> int:
        return value + 1
    def untyped(value):
        return value
    def unsafe_annotation(value: "__import__('os').system('exit 1')"):
        return value
    for fn in (typed, untyped, unsafe_annotation):
        fn.__module__ = module.__name__
        module.__dict__[fn.__name__] = fn
    module.__dict__["foreign"] = lambda x: x
    return module


class AutomaticDiscoveryTests(unittest.TestCase):
    def test_inventory_does_not_require_toml_or_evaluate_annotations(self):
        module = fixture_module()
        info = inspect_python(module)
        self.assertIs(info, inspect_python(module))
        functions = {entry.name: entry for entry in info.functions}
        self.assertNotIn("foreign", functions)
        self.assertEqual(functions["typed"].parameters[0].type_kind, "integer")
        self.assertEqual(functions["typed"].returns, "integer")
        self.assertEqual(functions["untyped"].parameters[0].type_kind, "any")
        self.assertFalse(functions["untyped"].parameters[0].declared)
        self.assertEqual(functions["unsafe_annotation"].parameters[0].type_kind, "any")
        self.assertTrue(functions["unsafe_annotation"].parameters[0].declared)
        self.assertIn("typed\tinteger\tinteger", wire_python(module))
        self.assertIn('"module": "automatic_fixture"', manifest_json(module))

    def test_opt_in_guards_enforce_inferred_types_and_preserve_untyped(self):
        module = fixture_module()
        typed = module.typed
        guarded = annotation_guard(typed)
        self.assertEqual(guarded(7), 8)
        self.assertEqual(guarded(value=3), 4)
        with self.assertRaises(ContractViolation):
            guarded(True)
        with self.assertRaises(ContractViolation):
            guarded(value="wrong")
        self.assertIs(annotation_guard(module.untyped), module.untyped)
        view = checked_module(module)
        self.assertIs(view._source, module)
        self.assertIs(module.typed, typed)
        self.assertEqual(view.typed(2), 3)
        with self.assertRaises(ContractViolation):
            view.typed(False)
        self.assertEqual(module.typed(False), 1)
        self.assertIs(view.untyped, module.untyped)

    def test_large_module_discovery_is_explicitly_deferred_and_cached(self):
        class FakeMain:
            calls = 0
            def seval(self, expression):
                self.calls += 1
                self.source = expression
                return lambda module: "__JUPY_DEFERRED__\\t1000"

        class FakeRuntime:
            main = FakeMain()
            def start(self):
                return self.main

        name = "LargeModuleFixtureForDiscovery"
        discovery._JULIA.pop(name, None)
        runtime = FakeRuntime()
        with patch.object(discovery, "_JULIA_INSPECTOR", None):
            metadata = discovery.discover_julia(name, object(), runtime)
            self.assertEqual(metadata["source"], "deferred_large_module")
            self.assertEqual(metadata["symbol_count"], 1000)
            self.assertEqual(metadata["functions"], [])
            self.assertIn("length(symbols) > 128", runtime.main.source)
            self.assertIs(discovery.discover_julia(name, object(), runtime), metadata)
            self.assertEqual(runtime.main.calls, 1)
        discovery._JULIA.pop(name, None)

    def test_output_checks_and_cache_invalidation(self):
        module = fixture_module()
        def wrong(value: int) -> int:
            return str(value)
        wrong.__module__ = module.__name__
        module.wrong = wrong
        # Discovery is cached until deliberately invalidated by caller.
        info = inspect_python(module)
        self.assertIn("wrong", [entry.name for entry in info.functions])
        with self.assertRaises(ContractViolation):
            annotation_guard(module.wrong)(2)
        invalidate(module)
        self.assertIsNot(inspect_python(module), info)

    def test_string_annotations_without_code_execution(self):
        calls = []
        def function(x: int) -> bool:
            calls.append(x)
            return True
        f = annotation_guard(function)
        self.assertIs(f(2), True)
        with self.assertRaises(ContractViolation):
            f("bad")
        self.assertEqual(calls, [2])


if __name__ == "__main__":
    unittest.main()
