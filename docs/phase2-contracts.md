# Phase 2 — Static-first computational contracts

Branch: `interop-contract`. Phase 2 is additive to the validated Phase 1
runtime; it neither replaces JuliaCall/PythonCall nor translates source code.

## Design and performance contract

The contract is parsed once and all symbolic dimension expressions are
compiled to integer coefficients and variable names at binding. Repeated
invocations **never reparse TOML, evaluate expressions, or perform module
discovery**. A bound callable captures an immutable validation plan and its
already-resolved native bridge function.

The validation modes are deliberately explicit:

- `trusted`: The developer takes responsibility for all runtime obligations.
  `bind(f, contract, mode="trusted") is f` in Python, and
  `bind(f, contract; mode=:trusted) === f` in Julia. **This gives exactly zero
  added callable-wrapper overhead.** It is not a claim that values were checked.
- `structural`: Verify fixed argument count, scalar types, array dtype,
  array rank, shape, symbolic dimension relationships, and output metadata.
  O(argument count + rank), independent of array element count. Fixed schema
  sizes make this O(1) in the number of numerical elements.
- `strict`: Structural checks plus all declared finite/symmetric value
  predicates. Finiteness necessarily reads O(number of elements). Symmetry
  necessarily reads O(n²) entries in the worst case for a dense n×n matrix.
  No sampling shortcuts or unverified labels are used.
- `static`: Reserved for actual statically established runtime guarantees.
  A developer-supplied TOML schema alone cannot prove properties of arbitrary
  mutable arguments or outputs; this mode currently **fails closed**. Use
  `trusted` to explicitly bypass validation. This distinction prevents false
  claims of static proof.

A tuple of fixed argument count and bounded tensor rank gives deterministic
constant-metadata work, but **does not guarantee zero nanoseconds**:
Python/Julia wrapper dispatch, dictionaries for symbolic dimensions, and
function calls consume real time. See the CI benchmark JSON/CSV files for
observed timings, not optimization claims.

## Portable TOML schema v1

The same TOML file is consumed without translation by Python's `tomllib`
and Julia's standard-library `TOML`. Strictly allowlisted keys are used.
Unknown fields and unsafe symbolic expressions are rejected.

```toml
schema_version = 1

[function]
id = "phonons.eigenvalues"
version = "1.0.0"
language = "julia"
module = "PhononSolver"
symbol = "eigenvalues"

[[inputs]]
name = "N"
kind = "integer"

[[inputs]]
name = "force_constants"
kind = "array"
dtype = "float64"
shape = ["3*N", "3*N"]
finite = true
symmetric = true

[output]
name = "result"
kind = "array"
dtype = "float64"
shape = ["3*N"]
finite = true

[execution]
purity = "unknown"
```

The allowed value kinds are `integer`, `float`, `boolean`, and `array`.
Supported declared numeric dtypes are float32, float64, int32, int64, and bool.
Dimensions are nonnegative integer literals, symbolic identifiers `N`, or
multiplicative expressions `3*N`. **General code evaluation is forbidden**.
Bindings are inferred from integer inputs or earlier encountered dimensions.
The logical contract uses one positional output and positional inputs.
Multiple results can be returned through an explicitly defined object
adapter in a future schema version; the v1 implementation does not silently
guess tuple semantics.

Numeric predicates `finite` and `symmetric` require strict mode.
Symmetry compares corresponding matrix entries exactly; approximate
symmetry/tolerance is not yet part of the portable schema. No sparse-specific
or GPU-specific transfer is performed to check the predicate. The Julia
validator accepts `AbstractArray`; the Python validator accepts native
arrays exposing `shape`, `dtype`, indexing, and/or a flat iterator.
For foreign opaque array wrappers, use the direct bridge or an explicit
conversion; do not assume an arbitrary PythonCall.Py or JuliaCall wrapper
has a validated native array layout.

`purity` is *declared metadata*, not automatically established or
enforced by the runtime.


## Automatic interface discovery and ordinary use

Most applications should continue loading modules directly:

```python
import jupy
solver = jupy.load("LatticeSolver")  # native JuliaCall module, unchanged
results = solver.solve(matrix)
```

```julia
using Jupy
solver = Jupy.load("lattice_solver") # native PythonCall module, unchanged
results = solver.solve(matrix)
```

A first successful canonical load now **prepares a cached descriptive module
inventory** without requiring a TOML contract, per-function registration, or
a separate initialization command:

- Python-hosted Julia: Jupy asks Julia's native method reflection for
  exported, locally declared functions. Each inventory records the method
  signature and known argument categories; Julia's existing multiple-dispatch
  machinery independently enforces applicable method argument types.
- Julia-hosted Python: a lightweight Python inspector examines the module
  dictionary and ordinary function signatures. It recognizes safely
  interpretable built-in type annotations; missing or unsupported annotations
  remain `any` (unknown). String annotations are **never evaluated**.
- Results are cached at module load. No contract metadata lookup or parsing
  occurs inside subsequent native function calls. The module handle and
  original callable objects remain unchanged.
- Julia modules with more than 128 visible names are marked
  `deferred_large_module` instead of exhaustively enumerating all methods
  during interpreter startup. For large standard-library modules, eager
  method enumeration can significantly increase cold-start cost without
  improving native Julia dispatch. Jupy records the symbol count and deferred
  status explicitly rather than incorrectly presenting an empty inventory
  as evidence that no callable functions exist. The threshold limits eager
  metadata work, **not** function availability; all native Julia functions
  remain callable. Smaller application modules are introspected fully.

Users who want to inspect the automatically discovered facts can call
`jupy.inspect_module("LatticeSolver")` or
`Jupy.inspect_module("lattice_solver")`. Introspection is advisory:
a missing inspector, unsupported signature, or a function without
annotations is **not** silently promoted to a verified contract.
Python-hosted Julia discovery uses a small Julia Base reflection function;
it deliberately does **not** load Julia-side Jupy or PythonCall solely for
introspection, avoiding unnecessary initialization of a second bridge.
If reflection is unsupported, loading still works and the inventory reports
that discovery was unavailable.

### Enforcement without application-side setup

Package authors can instrument Python functions where correctness checks
are appropriate:

```python
import jupy

@jupy.enforce_annotations
def increment(value: int) -> int:
    return value + 1
```

The decorator compiles the supported checks once at function definition.
Downstream Julia and Python applications call `increment` normally; no
TOML file, `bind_contract()`, or application-side registration is required.
An unannotated function receives no wrapper. Unknown annotations add **no
invented checks**. Ordinary Python annotations have no enforcement by
themselves; the author must opt into instrumentation to enforce them.

For an existing Python module whose author did not instrument functions,
`Jupy.checked_module("module_name")` returns a *separate* annotation-aware
view, and Python exposes `jupy.checked_module(native_python_module)`.
These views may impose wrapper and Python signature-binding overhead.
They are not the default, because replacing native module objects would
break existing Phase 1 identity and dispatch guarantees.

### What automatic discovery does not prove

**Automatic introspection does not secure arbitrary cross-language computation.**
It cannot prove that a Python function obeys its annotations; it does not
verify numerical finiteness, symmetry, acoustic sum rules, safe memory
ownership, or valid scientific results. Julia dispatch validates declared
method applicability, not the semantic correctness of the computation.
No runtime should execute untrusted third-party Python/Julia modules
merely to inspect their contracts: loading an untrusted module can itself
execute arbitrary initialization code.

Declared `purity`, type annotations, and native method signatures are
metadata unless the relevant runtime or an explicit checked callable
enforces them. Numerical guarantees require the existing strict contract
engine or trusted construction paths. Automatic discovery must never be
described as a security sandbox or mathematical proof.

The Python inspector's module inventory can be refreshed explicitly after
intentional external reloads via `jupy.discovery.invalidate(module)`.
Julia method metadata is cached by native module identity; its inspector
supports `refresh=true`. Ordinary Jupy module loading still does not
support implicit hot reload or cross-process registry persistence.

## Symmetric public API

Python loading and binding Julia:

```python
import jupy
solver = jupy.load("PhononSolver")
contract = jupy.read_contract("contracts/eigenvalues.toml")
fn = jupy.register("phonons.eigenvalues", solver.eigenvalues,
                   contract=contract, mode="strict")
result = jupy.resolve("phonons.eigenvalues")(N, phi)
```

Alternatively, resolve, register, and specialize using one operation:

```python
import jupy
fn = jupy.bind_contract("tests/contracts/increment.toml",
                        path="tests/interop/ExampleInterop.jl",
                        mode="structural")
assert fn(4) == 5
```

Julia loading and binding Python:

```julia
using Jupy
fn = Jupy.bind_contract("tests/contracts/float.toml"; mode=:strict)
result = fn(9.0)
```

For advanced use, `jupy.bind(f, contract, mode=...)` and
`Jupy.bind(f, contract; mode=...)` specialize an existing native or
foreign function. The public registries use (identity, version) keys.
Colliding registrations fail; resolving without an explicit version fails
when multiple versions exist. Registries are **process-local**, not remote.

## Named domain-specific validators

An input or output spec may declare `validators = ["myproject.acoustic_sum_rule"]`.
Both languages expose `register_validator(identity, predicate)`. Named
predicates must be registered before binding, return a native boolean, and
are resolved once into the compiled validation plan. Missing names reject
binding, and duplicate registration is rejected. Validation requires
`strict` mode; a `trusted` binding delegates all checks instead.
Application-specific predicates may be O(N) or more expensive and must not
be represented as constant-time metadata checks. A shared contract identifier
does not prove that two independently implemented validators have identical
semantics; conformance testing is required.

The contract registry uses exact (identity, version) dictionary keys.
With an explicit version, lookup is expected O(1). Omitting the version
requires a unique registered version and is also resolved from a per-ID
index rather than scanning every registration.

## Compatibility and reproducibility

`compatibility(a, b)` compares the same function identity, the exact
ordered input/output shape/dtype/predicate signature, and declared purity.
It is a *conservative interface comparison*, not proof of implementation
equivalence or physical semantics. Minor/patch version changes do not
automatically imply compatibility and semantic versioning is not inferred
from arbitrary code.

The contract files in `tests/contracts/` form a cross-language conformance
corpus. Python and Julia independently parse the same source, reject malformed
symbolic expressions, validate shape and numerical predicates, and check
registry behavior.

## Scope limitations and future extensions

- The schema v1 accepts positional calls only and one logical output;
  keyword and multiple-output schemas require an explicit revision.
- The initial Julia numeric validation supports native `AbstractArray`
  and Python scalar wrappers. Unsupported foreign tensor representations
  are rejected instead of materialized implicitly.
- Proof-carrying mutable arrays cannot be implemented safely without
  constraining mutation aliases and object lifetime; Phase 2 does **not**
  treat unchecked metadata as a verified mathematical invariant.
- Zero additional wrapper overhead is available via explicit `trusted` mode,
  **not** via automatic inference. Runtime structural checks have nonzero but
  fixed-rank constant work. Numerical scans are necessarily data-dependent.
- GPU transfer and storage ownership policies, copy/view selection, remote
  workers, and arbitrary autograd remain outside this phase.
- `load()` and all Phase 1 APIs remain available and independent of contracts.

## Acceptance and benchmarking

`python -m unittest discover -s tests/interop -p 'test_*.py' -v` runs
the portable Python contract conformance suite.
`julia --project=tests/interop/julia-project tests/interop/test_contracts.jl`
runs equivalent Julia conformance and PythonCall bridge tests after
provisioning the Julia project.

`benchmarks/contract_baseline.py` and
`benchmarks/contract_baseline.jl` record direct, trusted, and structural
call timings. CI does **not** fail on arbitrary speed ratios.
Performance claims require multiple controlled repetitions; conformance
requires all supported platform/version jobs to pass.
