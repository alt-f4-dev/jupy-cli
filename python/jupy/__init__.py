"""Project-aware, persistent Python-to-Julia interoperability.

Use `jupy.load(name, path=...)` as the canonical import interface.
The legacy `jupy.julia.import_module(...)` remains supported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime import JuliaRuntime, RuntimeConfigurationError, julia
from .contracts import Contract, ContractError, ContractViolation, Registry, read_contract, bind, register, resolve, compatibility, register_validator



def bind_contract(contract: Contract | str | Path, *,
                  path: str | Path | None = None, mode: str = "structural") -> Any:
    """Resolve the declared Julia callable, register it, and return a bound callable."""
    specification = contract if isinstance(contract, Contract) else read_contract(contract)
    if specification.language != "julia":
        raise ContractError("Python-hosted Jupy contracts must target Julia")
    module = load(specification.module, path=path)
    target = getattr(module, specification.symbol)
    return register(specification.identity, target, contract=specification, mode=mode)


def load(name: str, *, path: str | Path | None = None) -> Any:
    """Load a Julia module using the process-global Julia runtime."""
    return julia.load(name, path=path)


__all__ = ["JuliaRuntime", "RuntimeConfigurationError", "julia", "load", "Contract", "ContractError", "ContractViolation", "Registry", "read_contract", "bind", "register", "resolve", "compatibility", "register_validator", "bind_contract"]
