"""Process-global, lazy JuliaCall runtime with explicit module identity rules.

The embedded Julia interpreter is unique to the Python process. Jupy does not
support interpreter reset, implicit hot reload, or concurrent foreign calls.
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
_SOURCES: dict[Path, str] = {}
_FAILED = False


class RuntimeConfigurationError(RuntimeError):
    """Runtime configuration, lifecycle, or module identity is invalid."""


def find_project_root(start: Path | None = None) -> Path:
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
    """One process-global JuliaCall interpreter with serialized import bookkeeping.

    This does not claim general thread safety for invoking Julia functions.
    """

    def __init__(self, project: str | Path | None = None, executable: str | None = None) -> None:
        self._project = Path(project).expanduser().resolve() if project is not None else None
        self._executable = executable

    @property
    def initialized(self) -> bool:
        return _MAIN is not None

    def start(self) -> Any:
        global _MAIN, _CONFIG, _FAILED
        with _LOCK:
            if _FAILED:
                raise RuntimeConfigurationError(
                    "a previous JuliaCall initialization failed; restart the Python process"
                )
            # The process-global runtime cannot change configuration after startup.
            # Cached default-facade calls therefore need no disk, PATH, or project
            # discovery work. Explicitly configured facades still validate conflicts.
            if _CONFIG is not None and self._project is None and self._executable is None:
                return _MAIN
            project = self._project or (_CONFIG[0] if _CONFIG else find_project_root())
            if not (project / "Project.toml").is_file() and not (project / "JuliaProject.toml").is_file():
                raise RuntimeConfigurationError(
                    f"no Julia project found at {project}; initialize with jupy or juuv first"
                )
            executable = _resolve_julia(
                self._executable if self._executable is not None else
                (str(_CONFIG[1]) if _CONFIG is not None else None)
            )
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
                # A failed embedded-runtime import can leave native state partially
                # initialized. No retry is allowed in this Python process.
                _FAILED = True
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
        """Load and cache a package or a named local module without hot reloading."""
        return self.import_module(name, path=path)

    def import_module(self, name: str, *, path: str | Path | None = None) -> Any:
        """Compatibility alias for load; both interfaces share the same cache."""
        if not isinstance(name, str) or not _MODULE_NAME.fullmatch(name):
            raise ValueError("module name must be a single Julia identifier")
        with _LOCK:
            main = self.start()
            source = Path(path).expanduser().resolve() if path is not None else None
            cached = _MODULES.get(name)
            if cached is not None:
                if source is not None and source != cached[1]:
                    raise RuntimeConfigurationError(
                        f"{name} already loaded from {cached[1]}; cannot change source"
                    )
                return cached[0]
            if source is not None:
                if not source.is_file():
                    raise FileNotFoundError(source)
                previous = _SOURCES.get(source)
                if previous is not None and previous != name:
                    raise RuntimeConfigurationError(
                        f"source {source} already registered as {previous}; cannot alias as {name}"
                    )
                if hasattr(main, name):
                    raise RuntimeConfigurationError(
                        f"Julia module {name} already exists outside Jupy; refusing to redefine it"
                    )
                main.include(str(source))
            else:
                main.seval(f"import {name}")
            module = getattr(main, name)
            _MODULES[name] = (module, source)
            if source is not None:
                _SOURCES[source] = name
            return module


julia = JuliaRuntime()
