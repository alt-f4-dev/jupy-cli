"""Opt-in end-to-end smoke test: run with the project's uv/pip Python interpreter."""

from __future__ import annotations

from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

from jupy import JuliaRuntime, load as jupy_load

julia = JuliaRuntime(project=Path(__file__).resolve().parent / 'julia-project')

MODULE = Path(__file__).with_name("ExampleInterop.jl")
example = julia.load("ExampleInterop", path=MODULE)
assert example.increment(40) == 41
assert example.increment(41) == 42
assert julia.load("ExampleInterop") is example
assert julia.import_module("ExampleInterop") is example
assert example.double_increment(0) == 2
assert example.calls() == 4
try:
    example.fail()
except Exception as exc:
    assert "interop fixture failure" in str(exc)
else:
    raise AssertionError("Julia exception did not propagate")
assert julia.initialized
# Phase 2 contract resolves an existing Julia module and the underlying callable.
import jupy
contracted = jupy.bind_contract(
    REPO / "tests" / "contracts" / "increment.toml",
    path=MODULE,
    mode="structural",
)
assert contracted(9) == 10
assert jupy.resolve("examples.increment", version="1.0.0") is contracted
try:
    contracted(True)
except jupy.ContractViolation:
    pass
else:
    raise AssertionError("cross-language contract did not reject a boolean")

# Ordinary public load also discovers declared Julia method types, without
# requiring TOML or explicit function registration.
native = jupy.load("ExampleInterop", path=MODULE)
assert native is example
inventory = jupy.inspect_module("ExampleInterop")
assert inventory is not None, "missing automatic Julia inventory"
assert inventory["source"] == "runtime_method_reflection", inventory
discovered = {entry["name"]: entry for entry in inventory["functions"]}
assert "increment" in discovered, inventory
assert any("integer" in method["arguments"]
           for method in discovered["increment"]["methods"])
assert native.increment(10) == 11
# Discovery must not import the full Julia-side Jupy/PythonCall runtime merely
# to introspect a Julia function; that would degrade startup substantially.
assert not jupy.julia.start().seval("isdefined(Main, :Jupy)")

print("Python -> Julia: persistent runtime, automatic discovery and contracts verified")
