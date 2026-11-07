"""Lazy, process-local Julia runtime using JuliaCall without per-call startup."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any

_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")


class RuntimeConfigurationError(RuntimeError):
    """Invalid or inconsistent Julia runtime configuration."""


def find_project_root(start: Path | None = None) -> Path:
    """Find the nearest Julia project, or use the starting directory."""
    start = (start or Path.cwd()).resolve()
    for directory in (start, *start.parents):
        if (directory / "Project.toml").is_file() or (directory / "JuliaProject.toml").is_file():
            return directory
    return start


class JuliaRuntime:
    """One JuliaCall runtime per Python process, with cached module handles.

    JuliaCall embeds one Julia runtime in the hosting Python process. This object
    never starts a new Julia subprocess for each function invocation.
    """

    def __init__(self, project: str | Path | None = None, executable: str | None = None) -> None:
        self._project = Path(project).expanduser().resolve() if project is not None else None
        self._executable = executable
        self._main: Any = None
        self._modules: dict[str, Any] = {}

    @property
    def initialized(self) -> bool:
        return self._main is not None

    def start(self) -> Any:
        """Start Julia lazily, then return the persistent Julia Main module."""
        if self._main is not None:
            return self._main
        project = self._project or find_project_root()
        if not (project / "Project.toml").is_file() and not (project / "JuliaProject.toml").is_file():
            raise RuntimeConfigurationError(f"no Julia project found at {project}; initialize with jupy or juuv first")
        executable = self._executable or os.environ.get("JUPY_JULIA") or shutil.which("julia")
        if not executable:
            raise RuntimeConfigurationError("Julia executable not found; set JUPY_JULIA or install Julia")
        executable_path = shutil.which(executable) or str(Path(executable).expanduser().resolve())
        if not Path(executable_path).is_file():
            raise RuntimeConfigurationError(f"Julia executable not found: {executable}")
        required = {
            "PYTHON_JULIACALL_EXE": str(Path(executable_path).resolve()),
            "PYTHON_JULIACALL_PROJECT": str(project),
        }
        if "juliacall" in sys.modules and self._main is None:
            raise RuntimeConfigurationError("JuliaCall was initialized outside Jupy; import 'from jupy import julia' before importing juliacall")
        for key, value in required.items():
            current = os.environ.get(key)
            if current and Path(current).expanduser().resolve() != Path(value):
                raise RuntimeConfigurationError(f"{key} already selects {current}; expected {value}")
            os.environ[key] = value
        from juliacall import Main
        self._main = Main
        return Main

    def import_module(self, name: str, *, path: str | Path | None = None) -> Any:
        """Import a Julia module by name, optionally including its source once."""
        if not _MODULE_NAME.fullmatch(name):
            raise ValueError("module name must be a single Julia identifier")
        main = self.start()
        if name in self._modules:
            if path is not None:
                raise RuntimeConfigurationError(f"{name} is already loaded; cannot change its source path")
            return self._modules[name]
        if path is not None:
            source = Path(path).expanduser().resolve()
            if not source.is_file():
                raise FileNotFoundError(source)
            main.include(str(source))
        else:
            main.seval(f"import {name}")
        module = getattr(main, name)
        self._modules[name] = module
        return module


julia = JuliaRuntime()
