"""Safe, cached Python callable discovery and optional annotation enforcement.

A discoverable declaration is metadata, not evidence that the function obeys
its annotation. Discovery deliberately never evaluates string annotations,
imports third-party annotation modules, or invokes inspected functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import inspect
import json
import re
import threading
import tomllib
import types
import weakref
from typing import Any, Callable

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")
_LOCK = threading.RLock()
_CACHE: weakref.WeakKeyDictionary[types.ModuleType, "ModuleManifest"] = weakref.WeakKeyDictionary()


@dataclass(frozen=True)
class ParameterInfo:
    name: str
    passing: str
    type_kind: str
    declared: bool


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    parameters: tuple[ParameterInfo, ...]
    returns: str
    return_declared: bool
    signature: str


@dataclass(frozen=True)
class ModuleManifest:
    module: str
    language: str
    functions: tuple[FunctionInfo, ...]
    source: str = "runtime_introspection"


def _annotation_kind(annotation: Any) -> tuple[str, bool]:
    if annotation is inspect.Signature.empty:
        return "any", False
    # A string annotation is parsed lexically; no eval or get_type_hints.
    mapping = {int: "integer", float: "float", bool: "boolean",
               "int": "integer", "float": "float", "bool": "boolean"}
    try:
        kind = mapping.get(annotation)
    except TypeError:
        kind = None
    if kind is not None:
        return kind, True
    return "any", annotation is not inspect.Signature.empty


def inspect_python(module: types.ModuleType) -> ModuleManifest:
    """Discover only locally defined Python functions via the module dictionary."""
    if not isinstance(module, types.ModuleType):
        raise TypeError("expected a native Python module")
    with _LOCK:
        cached = _CACHE.get(module)
        if cached is not None:
            return cached
        items: list[FunctionInfo] = []
        for name, value in sorted(vars(module).items()):
            if not _IDENTIFIER.fullmatch(name):
                continue
            if not inspect.isfunction(value) or getattr(value, "__module__", None) != module.__name__:
                continue
            try:
                signature = inspect.signature(value, eval_str=False)
            except (TypeError, ValueError):
                continue
            parameters = []
            for parameter in signature.parameters.values():
                kind, declared = _annotation_kind(parameter.annotation)
                parameters.append(ParameterInfo(
                    parameter.name, parameter.kind.name.lower(), kind, declared
                ))
            result, declared = _annotation_kind(signature.return_annotation)
            items.append(FunctionInfo(name, tuple(parameters), result, declared, str(signature)))
        manifest = ModuleManifest(module.__name__, "python", tuple(items))
        _CACHE[module] = manifest
        return manifest


def wire_python(module: types.ModuleType) -> str:
    """Restricted ASCII inventory for Julia; descriptive, never executable."""
    manifest = inspect_python(module)
    lines = []
    for info in manifest.functions:
        if not _IDENTIFIER.fullmatch(info.name):
            continue
        args = ",".join(p.type_kind for p in info.parameters)
        lines.append(f"{info.name}\t{args}\t{info.returns}")
    return "\n".join(lines)


def annotation_guard(function: Callable[..., Any]) -> Callable[..., Any]:
    """Compile supported type-annotation checks once; bypass unknown annotations."""
    signature = inspect.signature(function, eval_str=False)
    rules: list[tuple[str, str]] = []
    for parameter in signature.parameters.values():
        kind, _ = _annotation_kind(parameter.annotation)
        if kind != "any":
            rules.append((parameter.name, kind))
    result_kind, _ = _annotation_kind(signature.return_annotation)
    if not rules and result_kind == "any":
        return function

    def check(kind: str, value: Any, where: str) -> None:
        if kind == "integer":
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif kind == "boolean":
            valid = isinstance(value, bool)
        else:
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not valid:
            from .contracts import ContractViolation
            raise ContractViolation(f"{where}: inferred {kind} annotation violated")

    @wraps(function)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        for name, kind in rules:
            if name in bound.arguments:
                check(kind, bound.arguments[name], name)
        result = function(*args, **kwargs)
        if result_kind != "any":
            check(result_kind, result, "result")
        return result

    guarded.__jupy_annotation_guard__ = True
    return guarded


def checked_module(module: types.ModuleType) -> Any:
    """Explicit checked view. Does not mutate native modules or imported functions."""
    if not isinstance(module, types.ModuleType):
        raise TypeError("checked_module supports native Python modules")
    manifest = inspect_python(module)
    class CheckedView:
        __slots__ = ("_source", "_functions")
        def __init__(self):
            object.__setattr__(self, "_source", module)
            members = {}
            for info in manifest.functions:
                original = vars(module).get(info.name)
                if original is not None:
                    members[info.name] = annotation_guard(original)
            object.__setattr__(self, "_functions", members)
        def __getattr__(self, name: str) -> Any:
            functions = object.__getattribute__(self, "_functions")
            if name in functions:
                return functions[name]
            return getattr(object.__getattribute__(self, "_source"), name)
    return CheckedView()


def manifest_dict(manifest: ModuleManifest) -> dict[str, Any]:
    return {
        "module": manifest.module,
        "language": manifest.language,
        "source": manifest.source,
        "functions": [
            {"name": f.name, "signature": f.signature,
             "parameters": [{"name": p.name, "passing": p.passing,
                             "type": p.type_kind, "declared": p.declared}
                            for p in f.parameters],
             "returns": f.returns, "return_declared": f.return_declared}
            for f in manifest.functions
        ],
    }


def manifest_json(module: types.ModuleType) -> str:
    return json.dumps(manifest_dict(inspect_python(module)), sort_keys=True)



# Julia reflection uses only Base, not the Julia Jupy package or PythonCall.
# Loading the full package just to inspect function types would initialize
# a second bridge and impose significant avoidable cold-start overhead.
_JULIA: dict[str, dict[str, Any]] = {}
_JULIA_INSPECTOR: Any = None
_JULIA_INSPECTOR_CODE = r"""
mod -> begin
    lines = String[]
    for sym in Base.names(mod; all=true, imported=false)
        Base.isdefined(mod, sym) || continue
        f = Base.getfield(mod, sym)
        f isa Function || continue
        for meth in Base.methods(f)
            meth.module === mod || continue
            types = collect(Base.unwrap_unionall(meth.sig).parameters)
            args = String[]
            for t in types[2:end]
                kind = "any"
                if t isa Type
                    if t <: Bool
                        kind = "boolean"
                    elseif t <: Integer
                        kind = "integer"
                    elseif t <: AbstractFloat
                        kind = "float"
                    elseif t <: AbstractArray
                        kind = "array"
                    end
                end
                push!(args, kind)
            end
            signature = replace(string(meth.sig), '\t' => ' ', '\n' => ' ')
            push!(lines, string(sym, "\t", join(args, ","), "\t", signature))
        end
    end
    return join(lines, "\n")
end
"""


def discover_julia(name: str, module: Any, runtime: Any) -> dict[str, Any]:
    """Inspect local Julia methods without importing PythonCall into Julia."""
    global _JULIA_INSPECTOR
    with _LOCK:
        if name in _JULIA:
            return _JULIA[name]
        metadata: dict[str, Any] = {
            "module": name, "language": "julia",
            "source": "unavailable", "functions": [],
        }
        try:
            main = runtime.start()
            if _JULIA_INSPECTOR is None:
                _JULIA_INSPECTOR = main.seval(_JULIA_INSPECTOR_CODE)
            wire = str(_JULIA_INSPECTOR(module))
            if wire.startswith("__JUPY_DEFERRED__\\t"):
                metadata = {
                    "module": name, "language": "julia",
                    "source": "deferred_large_module",
                    "functions": [],
                    "symbol_count": int(wire.split("\\t", 1)[1]),
                    "reason": "full signature enumeration deferred to protect cold-start latency",
                }
                _JULIA[name] = metadata
                return metadata
            entries: dict[str, list[dict[str, Any]]] = {}
            for record in wire.splitlines():
                fields = record.split("\t", 2)
                if len(fields) != 3:
                    continue
                symbol, raw_args, signature = fields
                args = raw_args.split(",") if raw_args else []
                entries.setdefault(symbol, []).append({
                    "arguments": args, "signature": signature,
                    "returns": "any", "provenance": "julia_method_dispatch",
                })
            metadata = {
                "module": name, "language": "julia",
                "source": "runtime_method_reflection",
                "functions": [
                    {"name": symbol, "methods": methods}
                    for symbol, methods in sorted(entries.items())
                ],
            }
        except Exception as exc:
            # A failure in advisory reflection must not change module identity
            # or suppress a working native JuliaCall import.
            metadata["reason"] = type(exc).__name__
        _JULIA[name] = metadata
        return metadata


def julia_manifest(name: str) -> dict[str, Any] | None:
    """Read cached Julia signatures without invoking Julia again."""
    with _LOCK:
        return _JULIA.get(name)


def invalidate(module: types.ModuleType) -> None:
    """Explicit cache invalidation for intentional external Python reloads."""
    with _LOCK:
        _CACHE.pop(module, None)
