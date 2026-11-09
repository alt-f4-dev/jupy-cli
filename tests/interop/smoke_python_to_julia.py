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
assert example.calls() == 2
assert julia.initialized
print("Python -> Julia: persistent runtime and state verified")
