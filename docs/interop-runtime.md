# Interop runtime — milestone 1

Status: experimental; not released. This is an additive prototype on the `interop` branch. Existing `jupy`, `jupip`, `juuv`, and `jupyup` commands remain unchanged.

## Canonical API

Python hosts use `import jupy; module = jupy.load("JuliaModule", path="source.jl")`. Julia hosts use `using Jupy; module = Jupy.load("python.module"; path="source.py")`. The optional path is for a local module; omit it for an installed package. Modules are cached per embedded runtime, and the previous `jupy.julia.import_module` and `Jupy.pyimport` entry points are retained for compatibility. Native-language `import` syntax is not overloaded. Runtime and dependency configuration remain distinct from module loading.

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

## Phase 1B/1C: opt-in project setup

From an existing project that has been initialized with `jupy` or `juuv`, run:

```sh
juuv --jupy-interop-setup   # uv-backed projects
# or
jupy --jupy-interop-setup   # pip-backed projects
```

This explicitly vendors the experimental interop Python and Julia packages into `.jupy-interop/`, records the Python dependency (uv or pip), and registers the local Julia package with `Pkg.develop`. It does not translate source code. The directory should be committed with the project for portability; only the virtual environment and local machine settings are transient.

The setup command is experimental on the `interop` branch and is **not available in the published v0.0.3 release**. Install this branch's CLI to test it. The command modifies the current project's `pyproject.toml`/`uv.lock` or pip requirements and Julia `Project.toml`/`Manifest.toml`; review the changes before committing.

Running the setup command again reuses existing vendored sources, including user modifications; it does not automatically upgrade them. Use a new project or explicitly manage the vendored package version to upgrade.

The Python host obtains an embedded Julia runtime once per Python process. Distinct command invocations do not share process state. The Julia host similarly reuses one embedded Python interpreter through PythonCall. The interpreter/project binding is immutable after initialization. Run with the project's interpreter through `jupy <script.py>` or `juuv <script.py>`, and run Julia scripts with `jupy <script.jl>` or `juuv <script.jl>`.

## Installation and example — Python host

From a project already initialized with `juuv` or `jupy`, and from the cloned `jupy-cli` repository on the `interop` branch:

```bash
uv add --editable /absolute/path/to/jupy-cli/python
```

For pip-backed projects use `jupip install -e /absolute/path/to/jupy-cli/python`. Importing `jupy` does not initialize Julia. The module file below must define `module LatticeSolver ... end` and expose a function named `solve`.

```python
import jupy

solver = jupy.load("LatticeSolver", path="LatticeSolver.jl")
first = solver.solve(1)
second = solver.solve(2)
assert jupy.julia.initialized
assert solver is jupy.load("LatticeSolver")
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
np = Jupy.load("numpy")
a = np.arange(5)
@assert np === Jupy.load("numpy")
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
