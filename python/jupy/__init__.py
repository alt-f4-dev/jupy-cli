"""Project-aware, persistent Python-to-Julia interoperability.

Use `jupy.load(name, path=...)` as the canonical import interface.
The legacy `jupy.julia.import_module(...)` remains supported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime import JuliaRuntime, RuntimeConfigurationError, julia
from .contracts import Contract, ContractError, ContractViolation, Registry, read_contract, bind, register, resolve, compatibility


def load(name: str, *, path: str | Path | None = None) -> Any:
    """Load a Julia module using the process-global Julia runtime."""
    return julia.load(name, path=path)


__all__ = ["JuliaRuntime", "RuntimeConfigurationError", "julia", "load", "Contract", "ContractError", "ContractViolation", "Registry", "read_contract", "bind", "register", "resolve", "compatibility"]
