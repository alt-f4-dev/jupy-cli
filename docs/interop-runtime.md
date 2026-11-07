# Interop runtime — milestone 1

Status: experimental; not released. This is an additive prototype on the `interop` branch. Existing `jupy`, `jupip`, `juuv`, and `jupyup` commands remain unchanged.

## Objective

Provide native bidirectional calls between Python and Julia, with Julia initialized once per Python process and Python initialized once per Julia process. No source-to-source translation, per-call subprocesses, implicit shared heap, or automatic memory-conversion promises.

## Execution and lifecycle contracts

- A Python host uses `jupy.JuliaRuntime`, backed by JuliaCall; Julia is loaded lazily at first `start()` or `import_module()`.
- JuliaCall's `PYTHON_JULIACALL_EXE` and `PYTHON_JULIACALL_PROJECT` must both reference the existing Julia project before importing `juliacall`. This explicitly disables JuliaPkg's separate project selection.
- The Python process retains one embedded Julia runtime for its lifetime. `JuliaRuntime` caches loaded module handles; JuliaCall governs interpreter lifetime. Runtime shutdown/reinitialization is not supported.
- A Julia host uses `Jupy.pyimport`, backed by PythonCall and its existing `.venv` binding. Imported Python modules are cached per Julia process.
- Both directions preserve native module/function behavior and propagate underlying exceptions.
- Loading packages and compiling Julia methods can still incur first-use costs. The contract does not promise that every call is compilation-free.
- JuliaCall and PythonCall are alternative **host directions** of the same underlying PythonCall ecosystem, not separate concurrently managed runtimes. In particular, this prototype does not promise safe independent initialization in a process that already embeds the other language.

## Installation and example — Python host

From a project already initialized with `juuv` or `jupy`, and from the cloned `jupy-cli` repository on the `interop` branch:

```bash
uv add --editable /absolute/path/to/jupy-cli/python
```

For pip-backed projects use `jupip install -e /absolute/path/to/jupy-cli/python`. Importing `jupy` does not initialize Julia. The module file below must define `module LatticeSolver ... end` and expose a function named `solve`.

```python
from jupy import julia

solver = julia.import_module("LatticeSolver", path="LatticeSolver.jl")
first = solver.solve(1)
second = solver.solve(2)
assert julia.initialized
assert solver is julia.import_module("LatticeSolver")
```

`import_module("LinearAlgebra")` imports a Julia package available to the active project without an explicit source path. This experimental API only accepts a single Julia module identifier.

## Installation and example — Julia host

Register the local Julia package in the active project:

```julia
using Pkg
Pkg.develop(path="/absolute/path/to/jupy-cli/julia/Jupy")
```

Then:

```julia
using Jupy
np = Jupy.pyimport("numpy")
a = np.arange(5)
@assert np === Jupy.pyimport("numpy")
```

The `juuv`/`jupy` launcher already binds PythonCall to the project's `.venv`. When running Julia outside those launchers, configure the PythonCall interpreter explicitly before loading PythonCall.

## Deferred contracts

The next milestone specifies cross-language types, array shape/strides, shared vs copied storage, ownership, mutation, lifetime, and structured error propagation. Nothing in milestone 1 silently guarantees zero-copy conversion or automatic type mapping.

## Scope and failure modes

- Python host: start only after validating project and interpreter; do not switch Julia project after initialization.
- Importing `juliacall` before Jupy owns the runtime is rejected to avoid silently promising project selection that cannot be enforced.
- The Julia module cache is not a hot-reloading system; editing a loaded source file does not automatically replace its methods.
- This does not implement a persistent Julia *daemon*: separate Python processes still initialize their own Julia runtimes.
- Platform-specific package installation, ABI compatibility, and Julia/Python threading require integration tests on each supported operating system.
- A Python package dependency on `juliacall` is necessary for Python-hosted execution; `PythonCall.jl` alone is insufficient for `from jupy import julia` in an ordinary Python process.
