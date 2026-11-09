"""Opt-in end-to-end smoke test: run with the project's uv/pip Python interpreter."""

from __future__ import annotations

from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

from jupy import JuliaRuntime

julia = JuliaRuntime(project=Path(__file__).resolve().parent / 'julia-project')

MODULE = Path(__file__).with_name("ExampleInterop.jl")
example = julia.import_module("ExampleInterop", path=MODULE)
assert example.increment(40) == 41
assert example.increment(41) == 42
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
print("Python -> Julia: persistent runtime and state verified")
