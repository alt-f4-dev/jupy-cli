"""Contract v1 conformance: structural O(1), strict value checks, registration.

Uses a minimal array protocol to avoid dependency on NumPy or Julia in unit CI.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
from jupy.contracts import (
    Contract, ContractError, ContractViolation, Registry, bind, compatibility,
    read_contract, Dimension,
)

CONTRACTS = ROOT / "tests" / "contracts"


class FakeArray:
    def __init__(self, rows, *, dtype="float64"):
        self._data = rows
        self.shape = (len(rows), len(rows[0])) if rows else (0, 0)
        self.dtype = dtype

    @property
    def flat(self):
        return (item for row in self._data for item in row)

    def __getitem__(self, item):
        i, j = item
        return self._data[i][j]


class Phase2Tests(unittest.TestCase):
    def test_parse_shared_contracts_and_dimension_grammar(self):
        simple = read_contract(CONTRACTS / "increment.toml")
        self.assertEqual((simple.identity, simple.version, len(simple.inputs)),
                         ("examples.increment", "1.0.0", 1))
        structural = read_contract(CONTRACTS / "structural.toml")
        self.assertEqual(structural.inputs[1].shape[0], Dimension(3, "N"))
        with self.assertRaises(ContractError):
            read_contract(CONTRACTS / "malformed.toml")
        with self.assertRaises(ContractError):
            Dimension.parse("N + 1")
        with self.assertRaises(ContractError):
            Dimension.parse("__import__('os')")
        with self.assertRaises(ContractError):
            Dimension.parse("-1")

    def test_trusted_zero_wrapper_and_static_fail_closed(self):
        c = read_contract(CONTRACTS / "increment.toml")
        f = lambda x: x + 1
        self.assertIs(bind(f, c, mode="trusted"), f)
        with self.assertRaisesRegex(ContractError, "static verification"):
            bind(f, c, mode="static")
        with self.assertRaises(ContractError):
            bind(f, c, mode="unchecked")

    def test_structural_validates_without_reading_element_values(self):
        c = read_contract(CONTRACTS / "structural.toml")
        array = FakeArray([[float(i == j) for j in range(6)] for i in range(6)])
        values_read = []
        class MetadataOnly:
            shape = (6, 6)
            dtype = "float64"
            def __getitem__(self, item):
                values_read.append(item)
                raise AssertionError("structural validator must never inspect elements")
        bound = bind(lambda n, a: n + 1, c)
        self.assertEqual(bound(2, MetadataOnly()), 3)
        self.assertEqual(values_read, [])
        self.assertEqual(bound(2, array), 3)
        with self.assertRaises(ContractViolation):
            bound(3, array)
        with self.assertRaises(ContractViolation):
            bound(2, FakeArray([[0.0]], dtype="float32"))
        with self.assertRaises(ContractViolation):
            bound(2, array, unsupported=True)

    def test_strict_scans_values_and_enforces_symmetry(self):
        c = read_contract(CONTRACTS / "numeric.toml")
        with self.assertRaisesRegex(ContractError, "numerical predicates"):
            bind(lambda x: 1.0, c, mode="structural")
        bound = bind(lambda x: float(x[0, 0] + x[1, 1]), c, mode="strict")
        self.assertEqual(bound(FakeArray([[1., 2.], [2., 3.]])), 4.0)
        with self.assertRaisesRegex(ContractViolation, "symmetric"):
            bound(FakeArray([[1., 3.], [2., 4.]]))
        with self.assertRaisesRegex(ContractViolation, "nonfinite"):
            bound(FakeArray([[float("inf"), 0.], [0., 2.]]))
        with self.assertRaisesRegex(ContractViolation, "nonfinite"):
            bind(lambda x: float("nan"), c, mode="strict")(FakeArray([[1., 0.], [0., 1.]]))

    def test_registry_collisions_version_discovery_and_compatibility(self):
        c = read_contract(CONTRACTS / "increment.toml")
        registry = Registry()
        f = lambda x: x + 1
        v1 = registry.register(c.identity, f, contract=c)
        self.assertIs(registry.resolve(c.identity), v1)
        self.assertIs(registry.resolve(c.identity, version=c.version), v1)
        self.assertIs(registry.describe(c.identity), c)
        with self.assertRaisesRegex(ContractError, "registration already exists"):
            registry.register(c.identity, f, contract=c)
        with self.assertRaises(ContractError):
            registry.register("different.identity", f, contract=c)
        c2 = replace(c, version="1.0.1")
        registry.register(c.identity, f, contract=c2)
        with self.assertRaisesRegex(ContractError, "found 2"):
            registry.resolve(c.identity)
        self.assertTrue(compatibility(c, c2))
        self.assertFalse(compatibility(c, replace(c, output=replace(c.output, kind="float"))))

    def test_bad_function_and_bad_output(self):
        c = read_contract(CONTRACTS / "increment.toml")
        with self.assertRaises(ContractError):
            bind(9, c)
        wrong = bind(lambda n: "incorrect", c)
        with self.assertRaises(ContractViolation):
            wrong(4)
        with self.assertRaises(ContractViolation):
            wrong(True)


if __name__ == "__main__":
    unittest.main()
