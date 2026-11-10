# Phase 1 runtime stabilization and API freeze

Status: experimental `interop` branch; these guarantees are scoped to the
tested JuliaCall/PythonCall 0.9.37 stack, not to arbitrary native-ABI environments.

## Stable Phase 1 surface

The canonical API is `import jupy; jupy.load(name, path=None)` from Python
and `using Jupy; Jupy.load(name; path=nothing)` from Julia. A missing path
means an installed Julia or Python module; a path names a local source file.
The legacy Python `jupy.julia.import_module` and Julia `Jupy.pyimport`
remain compatibility aliases. The Python `JuliaRuntime` constructor supports
an explicit Julia project and executable. Neither `load` supports source
translation, auto-compilation of foreign syntax, contract validation, data
transfer modes, or automatic differentiation.

These interfaces and their meanings are frozen for Phase 2. Function contracts
must use separate APIs and must not make ordinary module loading depend on a
contract registry. Existing native bridge objects remain accessible.

## Module identity and lifetime

- Module names are unique for the lifetime of the interpreter; loading the
  same name again returns Jupy's cached module handle.
- Local module source paths are canonicalized. One source cannot be loaded as
  two module names, and one name cannot be reassigned to a different source.
- A package imported by name cannot later be replaced by a local file of
  the same name. An existing untracked Julia module or Python `sys.modules`
  entry cannot be silently redefined by a Jupy local source import.
- Failed imports are not committed to the Jupy cache. A failed Python source
  execution also removes the temporary `sys.modules` registration. Side
  effects of executed imports cannot be rolled back.
- Hot reloading, cache invalidation, and tracking external reloads are not
  supported. If external code reloads a module outside Jupy, previously
  returned Jupy references are not guaranteed to reflect the new state.
  Restart the host process to obtain a clean namespace.

## Runtime failure and concurrency

- The embedded Julia runtime is process-global. JuliaCall is initialized
  lazily and only once per Python process. The Julia project and executable
  are immutable after initialization, including across different
  `JuliaRuntime` facade instances.
- Invalid configuration found *before* JuliaCall import raises without
  poisoning the process. If JuliaCall initialization raises, the process is
  marked failed, the previous environment variables are restored, and later
  Jupy initialization attempts are rejected. Restart the Python process.
- Jupy serializes initialization and module-import bookkeeping; it does NOT
  guarantee thread-safe execution of arbitrary Julia and Python functions.
  Cross-language calls from multiple threads need application-level
  synchronization and native-runtime constraints.
- In-process persistence ends when the host exits. The project does not
  provide a cross-process resident daemon. Repeated shell invocations incur
  ordinary interpreter startup.

## Installation, relocation and upgrades

`jupy --jupy-interop-setup` and `juuv --jupy-interop-setup` explicitly
copy interface sources into the current project's `.jupy-interop/` directory
and register the Python and Julia packages. The invocation is not a
transaction: a Python dependency installation may succeed even if subsequent
Julia dependency resolution fails. Inspect the project and rerun after
correcting the cause.

- Repeating setup with unchanged local sources is supported; incompatible or
  edited vendored sources are never silently replaced.
- The Python `juliacall` pin determines the required `PythonCall` version.
  Incompatible existing Julia manifest resolutions fail before package copying.
  Intentional upgrades require migration and review of the vendor tree and
  both language dependency manifests. `jupyup` updates the launcher, not
  vendored project dependencies.
- `juuv` must use a uv-owned environment; pip setup rejects a uv-owned
  project. Do not mix dependency backends in the same virtual environment.
- `.venv` is not relocatable. Moving a project requires deleting/recreating
  the virtual environment and rerunning the appropriate setup command.
  Julia packages must also resolve successfully after relocation.
- In pip projects, frozen editable-install paths in `requirements.txt` can
  be absolute. Rerun setup after moving the project and regenerate the
  requirements snapshot. uv projects should use a relative editable path.
- Changing from one released vendored interface version to another is not
  performed automatically. Use a controlled source upgrade and rerun CI.
- The implementation explicitly checks known incompatibilities and files,
  but does not yet promise compatibility with every hand-edited project,
  system Python embedding, or Julia package registry configuration.

## Performance methodology and acceptance

`benchmarks/interop_baseline.py` and
`benchmarks/interop_baseline.jl` compare direct JuliaCall/PythonCall usage
with the equivalent Jupy facade in the same project. Python records separate
cold-process startup samples, cached module access, and warmed native calls;
Julia records cached imports and warmed native Python function calls.

Each operation uses warmups and repeated wall-clock samples, reporting median
and approximate 90th percentile. Results are environment-dependent; CI
uploads raw JSON and CSV artifacts. No speedup is asserted or used as a
functional pass criterion. Phase 3 will require controlled, larger-scale
allocation, copy, and workload studies before making optimization claims.

## Transition boundary to Phase 2

Phase 1 owns project creation, interpreter binding, module resolution and
identity, and process-local runtime lifecycle. Phase 2 may introduce a
language-neutral function contract format, callable registration, and
pre/postcondition checks **without changing the meaning of `load()`**.
Memory policies, transfer-path selection, and performance optimizations remain
Phase 3 concerns.

Phase 2 begins only after the targeted CI tests, native integration jobs,
setup/relocation tests, and baseline artifact job all succeed for the final
Phase 1 commit. CI success is evidence for the tested configurations, not a
claim of exhaustive production readiness.
