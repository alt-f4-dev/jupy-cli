"""Portable, static-first Julia/Python callable contracts.

Schema is TOML v1. Parsing, dimensional-expression compilation, and binding are
one-time operations. Trusted mode returns the original callable (zero wrapper).
Structural/strict modes use precompiled plans with fixed overhead per argument
and tensor axis, independent of element count except required value predicates.

No source translation, dynamic eval, or implicit data transfer is performed.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import math
from pathlib import Path
import re
import threading
import tomllib
from typing import Any, Callable, Mapping

_ID = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*$")
_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")
_SCALE = re.compile(r"^([1-9]\d*)\*([A-Za-z_][A-Za-z_0-9]*)$")
_TYPES = {"integer", "float", "boolean", "array"}
_DTYPES = {"float32", "float64", "int32", "int64", "bool"}
_MODES = {"static", "structural", "strict", "trusted"}


class ContractError(ValueError):
    """Malformed or conflicting portable contract."""


class ContractViolation(TypeError):
    """Arguments or results violate an executable contract."""


@dataclass(frozen=True)
class Dimension:
    coefficient: int = 1
    symbol: str | None = None
    constant: int | None = None

    @classmethod
    def parse(cls, value: Any) -> "Dimension":
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return cls(constant=value)
        if not isinstance(value, str):
            raise ContractError("dimensions must be nonnegative integers, identifiers, or 'k*N'")
        if _SYMBOL.fullmatch(value):
            return cls(symbol=value)
        match = _SCALE.fullmatch(value)
        if match:
            return cls(coefficient=int(match[1]), symbol=match[2])
        raise ContractError(f"unsupported dimension expression {value!r}")

    def check(self, actual: int, symbols: dict[str, int], where: str) -> None:
        if self.constant is not None:
            if actual != self.constant:
                raise ContractViolation(f"{where}: expected dimension {self.constant}, got {actual}")
            return
        assert self.symbol is not None
        if self.symbol not in symbols:
            if actual % self.coefficient:
                raise ContractViolation(f"{where}: dimension {actual} not divisible by {self.coefficient}")
            symbols[self.symbol] = actual // self.coefficient
        elif actual != self.coefficient * symbols[self.symbol]:
            raise ContractViolation(
                f"{where}: expected {self.coefficient}*{self.symbol}="
                f"{self.coefficient * symbols[self.symbol]}, got {actual}"
            )


@dataclass(frozen=True)
class Spec:
    name: str
    kind: str
    dtype: str | None
    shape: tuple[Dimension, ...]
    finite: bool
    symmetric: bool

    @classmethod
    def parse(cls, raw: Mapping[str, Any], *, index: int, output: bool = False) -> "Spec":
        allowed = {"name", "kind", "dtype", "shape", "finite", "symmetric"}
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ContractError("invalid contract input/output fields")
        name = raw.get("name", "result" if output else None)
        kind = raw.get("kind")
        if not isinstance(name, str) or not _SYMBOL.fullmatch(name):
            raise ContractError(f"invalid argument name at index {index}")
        if kind not in _TYPES:
            raise ContractError(f"unsupported kind {kind!r}")
        dtype = raw.get("dtype")
        if dtype is not None and (kind != "array" or dtype not in _DTYPES):
            raise ContractError("dtype is only available for arrays and must be supported")
        shape_raw = raw.get("shape", [])
        if not isinstance(shape_raw, list):
            raise ContractError("shape must be a list")
        if kind != "array" and ("shape" in raw or dtype is not None):
            raise ContractError("non-array values cannot have shape or dtype")
        if kind == "array" and "shape" not in raw:
            raise ContractError("array shapes must be explicitly declared")
        shape = tuple(Dimension.parse(dim) for dim in shape_raw)
        finite, symmetric = raw.get("finite", False), raw.get("symmetric", False)
        if not isinstance(finite, bool) or not isinstance(symmetric, bool):
            raise ContractError("finite and symmetric must be boolean")
        if finite and kind not in {"integer", "float", "array"}:
            raise ContractError("finiteness only applies to numeric values")
        if symmetric and (kind != "array" or len(shape) != 2):
            raise ContractError("symmetry requires a rank-2 array")
        return cls(name, kind, dtype, shape, finite, symmetric)


@dataclass(frozen=True)
class Contract:
    identity: str
    version: str
    language: str
    module: str
    symbol: str
    inputs: tuple[Spec, ...]
    output: Spec
    purity: str = "unknown"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Contract":
        if not isinstance(data, dict) or set(data) - {
            "schema_version", "function", "inputs", "output", "execution"
        }:
            raise ContractError("invalid contract root fields")
        if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise ContractError("unsupported contract schema version")
        function = data.get("function")
        if not isinstance(function, dict) or set(function) != {
            "id", "version", "language", "module", "symbol"
        }:
            raise ContractError("function requires exactly id, version, language, module, symbol")
        identity, version = function["id"], function["version"]
        language, module, symbol = function["language"], function["module"], function["symbol"]
        if not isinstance(identity, str) or not _ID.fullmatch(identity):
            raise ContractError("invalid function identity")
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            raise ContractError("version must have major.minor.patch format")
        if language not in {"python", "julia"}:
            raise ContractError("language must be python or julia")
        if not isinstance(module, str) or not _ID.fullmatch(module):
            raise ContractError("invalid module name")
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            raise ContractError("invalid callable symbol")
        arguments = data.get("inputs")
        if not isinstance(arguments, list):
            raise ContractError("inputs must be a list")
        inputs = tuple(Spec.parse(item, index=i) for i, item in enumerate(arguments))
        if len({item.name for item in inputs}) != len(inputs):
            raise ContractError("argument names must be unique")
        output = Spec.parse(data.get("output"), index=0, output=True)
        execution = data.get("execution", {"purity": "unknown"})
        if not isinstance(execution, dict) or set(execution) != {"purity"}:
            raise ContractError("execution only supports purity")
        purity = execution["purity"]
        if purity not in {"unknown", "pure", "impure"}:
            raise ContractError("unsupported purity")
        return cls(identity, version, language, module, symbol, inputs, output, purity)

    @property
    def numeric(self) -> bool:
        return any(s.finite or s.symmetric for s in (*self.inputs, self.output))

    @property
    def structural(self) -> bool:
        return bool(self.inputs) or self.output.kind != "boolean" or bool(self.output.shape)

    def signature(self) -> tuple[Any, ...]:
        def spec_key(s: Spec) -> tuple[Any, ...]:
            return (s.kind, s.dtype, s.shape, s.finite, s.symmetric)
        return (tuple(spec_key(s) for s in self.inputs), spec_key(self.output), self.purity)


def read_contract(path: str | Path) -> Contract:
    with Path(path).open("rb") as handle:
        return Contract.from_mapping(tomllib.load(handle))


def _shape_and_dtype(value: Any, where: str) -> tuple[tuple[int, ...], str]:
    shape = getattr(value, "shape", None)
    dtype = getattr(value, "dtype", None)
    if shape is None or dtype is None:
        raise ContractViolation(f"{where}: expected an array with shape and dtype")
    try:
        dims = tuple(int(d) for d in shape)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractViolation(f"{where}: invalid array shape") from exc
    if any(d < 0 for d in dims):
        raise ContractViolation(f"{where}: negative dimension")
    dtype_name = str(dtype).lower()
    # No conversion, synchronization, or copy is permitted by validation.
    return dims, dtype_name


def _elements(value: Any, dims: tuple[int, ...]):
    # Flat array iterator where available, otherwise index in row-major
    # logical order. All elements must be visited for sound finiteness checks.
    flat = getattr(value, "flat", None)
    if flat is not None:
        yield from flat
        return
    if not dims:
        yield value[()]
        return
    def recurse(prefix: tuple[int, ...], axis: int):
        if axis == len(dims):
            yield value[prefix]
        else:
            for i in range(dims[axis]):
                yield from recurse(prefix + (i,), axis + 1)
    yield from recurse((), 0)


def _check(spec: Spec, value: Any, dimensions: dict[str, int],
           where: str, strict: bool) -> None:
    if spec.kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ContractViolation(f"{where}: expected integer")
        dimensions[spec.name] = value
    elif spec.kind == "boolean":
        if not isinstance(value, bool):
            raise ContractViolation(f"{where}: expected boolean")
    elif spec.kind == "float":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ContractViolation(f"{where}: expected float")
    else:
        actual, dtype = _shape_and_dtype(value, where)
        if spec.dtype is not None and dtype != spec.dtype:
            raise ContractViolation(f"{where}: expected dtype {spec.dtype}, got {dtype}")
        if len(actual) != len(spec.shape):
            raise ContractViolation(f"{where}: rank {len(actual)} != expected {len(spec.shape)}")
        for i, (dim, observed) in enumerate(zip(spec.shape, actual)):
            dim.check(observed, dimensions, f"{where}.shape[{i}]")
        if strict and spec.symmetric:
            if actual[0] != actual[1]:
                raise ContractViolation(f"{where}: symmetry requires square matrix")
            for i in range(actual[0]):
                for j in range(i):
                    if value[i, j] != value[j, i]:
                        raise ContractViolation(f"{where}: matrix not symmetric at ({i}, {j})")
        if strict and spec.finite:
            for item in _elements(value, actual):
                try:
                    valid = math.isfinite(item)
                except (TypeError, ValueError) as exc:
                    raise ContractViolation(f"{where}: nonnumeric array element") from exc
                if not valid:
                    raise ContractViolation(f"{where}: nonfinite array element")
        return
    if strict and spec.finite and not math.isfinite(value):
        raise ContractViolation(f"{where}: nonfinite value")


def bind(function: Callable[..., Any], contract: Contract | str | Path,
         *, mode: str = "structural") -> Callable[..., Any]:
    """One-time specialization; trusted/static modes return the original callable.

    static mode can only eliminate checks for input-free, unobservable-output
    contracts; otherwise no runtime proof is possible. trusted explicitly
    delegates runtime obligations to the caller without claiming verification.
    """
    if not callable(function):
        raise ContractError("target is not callable")
    if not isinstance(contract, Contract):
        contract = read_contract(contract)
    if mode not in _MODES:
        raise ContractError(f"unsupported validation mode {mode!r}")
    if mode == "trusted":
        return function
    if mode == "static":
        raise ContractError(
            "static verification of runtime arguments/outputs is unavailable; "
            "use structural, strict, or explicitly trusted mode"
        )
    if mode == "structural" and contract.numeric:
        raise ContractError(
            "contract requires numerical predicates; use strict to enforce "
            "them or trusted to explicitly delegate all runtime guarantees"
        )
    # Capture immutable, pre-parsed specifications. No TOML, regex, or
    # expression evaluation is performed in the hot path.
    inputs, output, strict = contract.inputs, contract.output, mode == "strict"
    count = len(inputs)

    @wraps(function)
    def bound(*args: Any, **kwargs: Any) -> Any:
        if kwargs or len(args) != count:
            raise ContractViolation(f"{contract.identity}: expected {count} positional arguments")
        dimensions: dict[str, int] = {}
        for spec, value in zip(inputs, args):
            _check(spec, value, dimensions, f"argument {spec.name}", strict)
        result = function(*args)
        _check(output, result, dimensions, "result", strict)
        return result

    bound.__jupy_contract__ = contract
    bound.__jupy_mode__ = mode
    return bound


class Registry:
    """Deterministic process-local registry; no implicit cross-process sharing."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str], Callable[..., Any]] = {}
        self._contracts: dict[tuple[str, str], Contract] = {}

    def register(self, identity: str, function: Callable[..., Any],
                 *, contract: Contract | str | Path, mode: str = "structural") -> Callable[..., Any]:
        definition = contract if isinstance(contract, Contract) else read_contract(contract)
        if identity != definition.identity:
            raise ContractError("registered identity does not match contract identity")
        target = bind(function, definition, mode=mode)
        key = (identity, definition.version)
        with self._lock:
            if key in self._entries:
                raise ContractError(f"contract registration already exists: {key}")
            self._entries[key] = target
            self._contracts[key] = definition
        return target

    def resolve(self, identity: str, *, version: str | None = None) -> Callable[..., Any]:
        with self._lock:
            matched = [key for key in self._entries
                       if key[0] == identity and (version is None or key[1] == version)]
            if len(matched) != 1:
                raise ContractError(f"expected one registered callable for {identity} {version}; found {len(matched)}")
            return self._entries[matched[0]]

    def describe(self, identity: str, *, version: str | None = None) -> Contract:
        with self._lock:
            matched = [key for key in self._contracts
                       if key[0] == identity and (version is None or key[1] == version)]
            if len(matched) != 1:
                raise ContractError(f"expected one contract for {identity} {version}; found {len(matched)}")
            return self._contracts[matched[0]]


registry = Registry()


def register(identity: str, function: Callable[..., Any], *,
             contract: Contract | str | Path, mode: str = "structural") -> Callable[..., Any]:
    return registry.register(identity, function, contract=contract, mode=mode)


def resolve(identity: str, *, version: str | None = None) -> Callable[..., Any]:
    return registry.resolve(identity, version=version)


def compatibility(a: Contract, b: Contract) -> bool:
    """Conservative structural compatibility, not mathematical equivalence."""
    return a.identity == b.identity and a.signature() == b.signature()
