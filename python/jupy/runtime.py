"""Process-global, lazy JuliaCall runtime bound to a single Julia project.

JuliaCall embeds one Julia runtime per Python process. This module deliberately
does not pretend that separate JuliaRuntime objects create separate interpreters.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import sys
import threading
from typing import Any

_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")
_LOCK = threading.RLock()
_MAIN: Any = None
_CONFIG: tuple[Path, Path] | None = None
_MODULES: dict[str, tuple[Any, Path | None]] = {}


class RuntimeConfigurationError(RuntimeError):
    """An interpreter or project conflicts with process-global Julia state."""


def find_project_root(start: Path | None = None) -> Path:
    """Return the nearest enclosing Julia project, or the start directory."""
    start = (start or Path.cwd()).resolve()
    for directory in (start, *start.parents):
        if (directory / "Project.toml").is_file() or (directory / "JuliaProject.toml").is_file():
            return directory
    return start


def _resolve_julia(candidate: str | None) -> Path:
    selected = candidate or os.environ.get("JUPY_JULIA") or shutil.which("julia")
    if not selected:
        raise RuntimeConfigurationError("Julia executable not found; set JUPY_JULIA")
    resolved = shutil.which(selected) or selected
    exe = Path(resolved).expanduser().resolve()
    if not exe.is_file():
        raise RuntimeConfigurationError(f"Julia executable not found: {selected}")
    return exe


class JuliaRuntime:
    """Lazy facade to the single embedded Julia runtime in the current process.

    Calls are serialized *during initialization and import bookkeeping*.
    This does not claim thread-safe concurrent execution of arbitrary Julia code.
    """

    def __init__(self, project: str | Path | None = None, executable: str | None = None) -> None:
        self._project = Path(project).expanduser().resolve() if project is not None else None
        self._executable = executable

    @property
    def initialized(self) -> bool:
        return _MAIN is not None

    def start(self) -> Any:
        global _MAIN, _CONFIG
        with _LOCK:
            # Config checks must run even for a previously initialized instance.
            project = self._project or (_CONFIG[0] if _CONFIG else find_project_root())
            if not (project / "Project.toml").is_file() and not (project / "JuliaProject.toml").is_file():
                raise RuntimeConfigurationError(f"no Julia project found at {project}; initialize with jupy or juuv first")
            executable = _resolve_julia(self._executable if self._executable is not None else (
                str(_CONFIG[1]) if _CONFIG is not None else None
            ))
            desired = (project, executable)
            if _CONFIG is not None:
                if desired != _CONFIG:
                    raise RuntimeConfigurationError(
                        f"Julia is bound to project={_CONFIG[0]}, executable={_CONFIG[1]}; "
                        f"cannot switch to project={project}, executable={executable} in this process"
                    )
                return _MAIN

            if "juliacall" in sys.modules:
                raise RuntimeConfigurationError(
                    "JuliaCall was imported before Jupy configured the runtime; "
                    "initialize Jupy before importing juliacall"
                )
            required = {
                "PYTHON_JULIACALL_EXE": str(executable),
                "PYTHON_JULIACALL_PROJECT": str(project),
            }
            for key, value in required.items():
                current = os.environ.get(key)
                if current and Path(current).expanduser().resolve() != Path(value):
                    raise RuntimeConfigurationError(f"{key} is {current}; expected {value}")

            old_values = {key: os.environ.get(key) for key in required}
            os.environ.update(required)
            try:
                from juliacall import Main
            except BaseException:
                # A failed runtime initialization may leave JuliaCall partly loaded.
                # Fail closed rather than promise safe reinitialization.
                for key, old in old_values.items():
                    if old is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = old
                raise
            _MAIN = Main
            _CONFIG = desired
            return Main

    def load(self, name: str, *, path: str | Path | None = None) -> Any:
        """Canonical cross-language module loader; reuse the Julia runtime."""
        return self.import_module(name, path=path)

    def import_module(self, name: str, *, path: str | Path | None = None) -> Any:
        """Load a Julia module once; reject ambiguous reimports or source changes."""
        if not _MODULE_NAME.fullmatch(name):
            raise ValueError("module name must be a single Julia identifier")
        with _LOCK:
            main = self.start()
            source = Path(path).expanduser().resolve() if path is not None else None
            cached = _MODULES.get(name)
            if cached is not None:
                if source is not None and source != cached[1]:
                    raise RuntimeConfigurationError(f"{name} already loaded from {cached[1]}; cannot change source")
                return cached[0]
            if source is not None:
                if not source.is_file():
                    raise FileNotFoundError(source)
                main.include(str(source))
            else:
                main.seval(f"import {name}")
            module = getattr(main, name)
            _MODULES[name] = (module, source)
            return module


julia = JuliaRuntime()
