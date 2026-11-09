#!/usr/bin/env python3
"""Cross-platform core for the jupy, jupip, and juuv commands.

jupy bootstraps a Julia project and a project-local Python virtual environment,
then launches Julia with PythonCall bound to that environment.

jupip runs pip through the same project-local Python interpreter and refreshes
requirements.txt after successful install or uninstall operations.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

TOOL_VERSION = "0.0.3"
STATE_SCHEMA_VERSION = "jupy-state-v2"
GITIGNORE_CONTENT = ".venv/\nLocalPreferences.toml\n.CondaPkg/\n"


class JupyError(RuntimeError):
    """Expected user-facing failure."""


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def log(program: str, message: str) -> None:
    print(f"{program}: {message}", file=sys.stderr)


def verbose(program: str, message: str) -> None:
    if env_flag("JUPY_VERBOSE"):
        log(program, message)


def resolve_command(candidate: str, description: str) -> str:
    expanded = os.path.expandvars(os.path.expanduser(candidate))
    path = Path(expanded)
    if path.is_file():
        return str(path.resolve())

    resolved = shutil.which(candidate)
    if resolved:
        return resolved

    raise JupyError(f"{description} was not found or is not executable: {candidate}")


def find_julia() -> str:
    configured = os.environ.get("JUPY_JULIA")
    if configured:
        return resolve_command(configured, "JUPY_JULIA")

    resolved = shutil.which("julia")
    if not resolved:
        raise JupyError("julia was not found in PATH; install Julia or set JUPY_JULIA")
    return resolved


def find_project_root(start: Optional[Path] = None) -> Path:
    """Return the nearest enclosing Julia project, or the starting directory."""
    start = (start or Path.cwd()).resolve()
    if not start.is_dir():
        raise JupyError(f"working directory does not exist or is not a directory: {start}")

    current = start
    while True:
        if (current / "JuliaProject.toml").is_file() or (current / "Project.toml").is_file():
            return current
        if current.parent == current:
            return start
        current = current.parent


def project_file(root: Path) -> Optional[Path]:
    julia_project = root / "JuliaProject.toml"
    standard_project = root / "Project.toml"
    if julia_project.is_file():
        return julia_project
    if standard_project.is_file():
        return standard_project
    return None


def project_has_pythoncall(path: Path) -> bool:
    """Check for PythonCall specifically in the top-level [deps] table."""
    in_deps = False
    deps_header = re.compile(r"^\s*\[deps\]\s*(?:#.*)?$")
    any_header = re.compile(r"^\s*\[")
    pythoncall_entry = re.compile(r"^\s*PythonCall\s*=")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise JupyError(f"could not read {path}: {exc}") from exc

    for line in lines:
        if deps_header.match(line):
            in_deps = True
            continue
        if any_header.match(line):
            in_deps = False
        elif in_deps and pythoncall_entry.match(line):
            return True
    return False


def ensure_support_files(root: Path, program: str) -> None:
    gitignore = root / ".gitignore"
    requirements = root / "requirements.txt"

    if not gitignore.exists():
        try:
            with gitignore.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(GITIGNORE_CONTENT)
        except OSError as exc:
            raise JupyError(f"could not create {gitignore}: {exc}") from exc
        log(program, f"created {gitignore}")

    if not requirements.exists():
        try:
            requirements.touch(exist_ok=False)
        except OSError as exc:
            raise JupyError(f"could not create {requirements}: {exc}") from exc
        log(program, f"created {requirements}")


def venv_python_path(root: Path, platform_name: Optional[str] = None) -> Path:
    platform_name = platform_name or os.name
    if platform_name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def executable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    return os.name == "nt" or os.access(path, os.X_OK)


def bootstrap_python() -> str:
    configured = os.environ.get("JUPY_PYTHON")
    if configured:
        return resolve_command(configured, "JUPY_PYTHON")

    # The shared core is already running under Python, so this is the most
    # reliable interpreter with which to create the project-local environment.
    if sys.executable:
        executable = Path(sys.executable)
        if executable_file(executable):
            return str(executable.resolve())

    for name in ("python3", "python", "py"):
        resolved = shutil.which(name)
        if resolved:
            return resolved

    raise JupyError("no usable Python 3 interpreter was found")


def run_checked(
    command: Sequence[str],
    *,
    env: Optional[Mapping[str, str]] = None,
    cwd: Optional[Path] = None,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    stdout = subprocess.DEVNULL if quiet else None
    stderr = subprocess.DEVNULL if quiet else None
    return subprocess.run(
        list(command),
        env=dict(env) if env is not None else None,
        cwd=str(cwd) if cwd is not None else None,
        stdout=stdout,
        stderr=stderr,
        text=True,
        check=False,
    )


def ensure_virtual_environment(root: Path, program: str) -> Path:
    venv_dir = root / ".venv"
    python = venv_python_path(root)

    if executable_file(python):
        verbose(program, f"using existing Python environment at {venv_dir}")
    else:
        if venv_dir.exists():
            expected = ".venv\\Scripts\\python.exe" if os.name == "nt" else ".venv/bin/python"
            raise JupyError(
                f"{venv_dir} exists but does not contain {expected}; "
                "remove or repair it before continuing"
            )

        interpreter = bootstrap_python()
        log(program, f"creating Python virtual environment at {venv_dir}")
        result = run_checked([interpreter, "-m", "venv", str(venv_dir)])
        if result.returncode != 0:
            hint = ""
            if sys.platform.startswith("linux"):
                hint = "; on Debian/Ubuntu/Linux Mint, install the python3-venv package"
            raise JupyError(f"failed to create {venv_dir}{hint}")

    if not executable_file(python):
        raise JupyError(f"virtual-environment creation did not produce {python}")

    pip_check = run_checked([str(python), "-m", "pip", "--version"], quiet=True)
    if pip_check.returncode != 0:
        log(program, f"pip is missing from {venv_dir}; attempting ensurepip")
        ensurepip = run_checked([str(python), "-m", "ensurepip", "--upgrade"], quiet=True)
        if ensurepip.returncode != 0:
            raise JupyError(f"pip could not be initialized inside {venv_dir}")

    return python



def find_uv() -> str:
    configured = os.environ.get("JUPY_UV")
    if configured:
        return resolve_command(configured, "JUPY_UV")
    resolved = shutil.which("uv")
    if not resolved:
        raise JupyError("uv was not found in PATH; install uv or set JUPY_UV")
    return resolved


def ensure_uv_environment(root: Path, program: str) -> Path:
    """Synchronize a native uv project without adopting a pip-managed venv."""
    uv = find_uv()
    venv_dir = root / ".venv"
    marker = venv_dir / ".jupy-backend"
    python = venv_python_path(root)

    if venv_dir.exists():
        if not venv_dir.is_dir():
            raise JupyError(f"{venv_dir} exists and is not a directory")
        existing = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
        if existing and existing != "uv":
            raise JupyError(f"{venv_dir} is managed by {existing}; juuv refuses to replace it")
        if not existing:
            config = venv_dir / "pyvenv.cfg"
            config_text = config.read_text(encoding="utf-8") if config.is_file() else ""
            if not re.search(r"(?im)^uv\s*=", config_text):
                raise JupyError(
                    f"{venv_dir} exists without uv ownership metadata; "
                    "juuv refuses to synchronize a possibly pip-managed environment"
                )

    if not (root / "pyproject.toml").is_file():
        if (root / "uv.lock").exists():
            raise JupyError("uv.lock exists without pyproject.toml; repair the uv project first")
        log(program, f"initializing native uv project at {root}")
        result = run_checked([uv, "init", "--bare", "--no-workspace"], cwd=root)
        if result.returncode != 0:
            raise JupyError("uv init failed")

    log(program, f"synchronizing uv environment at {root}")
    result = run_checked([uv, "sync"], cwd=root)
    if result.returncode != 0:
        raise JupyError("uv sync failed; existing project files were preserved")
    if not executable_file(python):
        raise JupyError(f"uv sync did not produce the Python interpreter at {python}")
    atomic_write_text(marker, "uv\n")
    return python



def manifest_files(root: Path) -> List[Path]:
    files: List[Path] = []
    project = project_file(root)
    if project is not None:
        files.append(project)

    default_manifest = root / "Manifest.toml"
    if default_manifest.is_file():
        files.append(default_manifest)

    files.extend(sorted(path for path in root.glob("Manifest-v*.toml") if path.is_file()))
    return files


def julia_environment_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    digest.update(STATE_SCHEMA_VERSION.encode("utf-8"))
    digest.update(b"\0")

    files = manifest_files(root)
    if not files:
        digest.update(b"no-project\0")

    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError as exc:
            raise JupyError(f"could not fingerprint {path}: {exc}") from exc
        digest.update(b"\0")

    return digest.hexdigest()


def state_file(root: Path) -> Path:
    return root / ".venv" / ".jupy-julia-state"


def read_saved_state(root: Path) -> str:
    path = state_file(root)
    try:
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    except OSError:
        return ""


def atomic_write_text(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    except OSError as exc:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise JupyError(f"could not atomically write {target}: {exc}") from exc


def pythoncall_environment() -> Dict[str, str]:
    environment = os.environ.copy()
    environment["JULIA_CONDAPKG_BACKEND"] = "Null"
    environment["JULIA_PYTHONCALL_EXE"] = "@venv"
    return environment


def ensure_julia_project(root: Path, julia: str, program: str) -> None:
    current_project = project_file(root)
    has_pythoncall = bool(current_project and project_has_pythoncall(current_project))
    current_state = julia_environment_fingerprint(root)

    if (
        not env_flag("JUPY_FORCE_SETUP")
        and has_pythoncall
        and read_saved_state(root) == current_state
    ):
        verbose(program, "Julia environment is already initialized")
        return

    if current_project is None:
        log(program, f"creating Julia project at {root} and adding PythonCall")
    elif not has_pythoncall:
        log(program, f"adding PythonCall to {current_project}")
    else:
        log(program, f"instantiating Julia dependencies from {current_project}")

    julia_code = r'''
using Pkg
root = abspath(only(ARGS))
Pkg.activate(root)

if haskey(Pkg.project().dependencies, "PythonCall")
    Pkg.instantiate()
else
    Pkg.add(Pkg.PackageSpec(name = "PythonCall"))
end
'''.strip()

    result = run_checked(
        [
            julia,
            "--startup-file=no",
            "--history-file=no",
            "-e",
            julia_code,
            str(root),
        ],
        env=pythoncall_environment(),
    )
    if result.returncode != 0:
        raise JupyError("failed to initialize the Julia project or install PythonCall")

    atomic_write_text(state_file(root), julia_environment_fingerprint(root) + "\n")


def pip_command_mutates_environment(arguments: Iterable[str]) -> bool:
    return any(argument in {"install", "uninstall"} for argument in arguments)


def sync_requirements(root: Path, venv_python: Path, program: str) -> None:
    result = subprocess.run(
        [str(venv_python), "-m", "pip", "freeze"],
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise JupyError("pip freeze failed; requirements.txt was left unchanged")

    atomic_write_text(root / "requirements.txt", result.stdout)
    log(program, f"synchronized {root / 'requirements.txt'}")


def normalize_return_code(returncode: int) -> int:
    if returncode >= 0:
        return returncode
    return 128 + abs(returncode)


def run_jupip(root: Path, venv_python: Path, arguments: Sequence[str], program: str) -> int:
    command = [str(venv_python), "-m", "pip", *arguments]
    try:
        result = subprocess.run(command, check=False)
    except KeyboardInterrupt:
        return 130

    returncode = normalize_return_code(result.returncode)
    if returncode != 0:
        return returncode

    if pip_command_mutates_environment(arguments):
        sync_requirements(root, venv_python, program)
    return 0


def run_jupy(root: Path, julia: str, venv_python: Path, arguments: Sequence[str], program: str) -> int:
    verbose(program, f"project={root}")
    verbose(program, f"python={venv_python}")
    
    if arguments and Path(arguments[0]).suffix.lower() == ".py":
        command = [str(venv_python), *arguments]
        environment = os.environ.copy()
    else:
        command = [julia, f"--project={root}", *arguments]
        environment = pythoncall_environment()

    try:
        result = subprocess.run(command, env=environment, check=False)
    except KeyboardInterrupt:
        return 130
    return normalize_return_code(result.returncode)


def _interop_sources(source_root: Path) -> tuple[Path, Path]:
    python_src = source_root / "python"
    julia_src = source_root / "julia" / "Jupy"
    if not (python_src / "pyproject.toml").is_file() or not (julia_src / "Project.toml").is_file():
        raise JupyError(
            f"interop package sources are unavailable at {source_root}; "
            "install from the interop checkout or set JUPY_INTEROP_SOURCE"
        )
    return python_src, julia_src


def _interop_pythoncall_version(python_src: Path) -> str:
    """Read the JuliaCall pin from the Python package, not a second hardcoded pin."""
    try:
        data = tomllib.loads((python_src / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = data["project"]["dependencies"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise JupyError(f"invalid interop Python package metadata: {exc}") from exc
    pins = [item.split("==", 1)[1] for item in dependencies
            if isinstance(item, str) and item.lower().startswith("juliacall==")]
    if len(pins) != 1:
        raise JupyError("interop Python package must declare exactly one pinned juliacall== version")
    return pins[0]


def check_interop_dependencies(root: Path, python_src: Path) -> None:
    """Reject incompatible pre-existing Julia project resolutions before mutation."""
    expected = _interop_pythoncall_version(python_src)
    for manifest in (root / "Manifest.toml", *sorted(root.glob("Manifest-v*.toml"))):
        if not manifest.is_file():
            continue
        try:
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise JupyError(f"invalid Julia manifest {manifest}: {exc}") from exc
        resolved = data.get("deps", {}).get("PythonCall")
        if resolved is None:
            continue
        if isinstance(resolved, list):
            versions = {dep.get("version") for dep in resolved if isinstance(dep, dict)}
        elif isinstance(resolved, dict):
            versions = {resolved.get("version")}
        else:
            raise JupyError(f"invalid PythonCall entry in {manifest}")
        versions.discard(None)
        if versions and versions != {expected}:
            raise JupyError(
                f"{manifest} resolves PythonCall {sorted(versions)} but "
                f"jupy-interop requires {expected}; resolve the conflict explicitly"
            )


def _check_vendored_source(src: Path, dst: Path) -> None:
    """Refuse silent overwrites or upgrades of project-local interface sources."""
    if dst.is_symlink() or not dst.is_dir():
        raise JupyError(f"invalid vendored interop directory: {dst}")
    for original in src.rglob("*"):
        if not original.is_file():
            continue
        relative = original.relative_to(src)
        if "__pycache__" in relative.parts or any(part.endswith(".egg-info") for part in relative.parts):
            continue
        if original.suffix == ".pyc":
            continue
        candidate = dst / relative
        if candidate.is_symlink() or not candidate.is_file() or candidate.read_bytes() != original.read_bytes():
            raise JupyError(
                f"vendored interop source differs from installed version: {candidate}; "
                "preserve local edits and explicitly migrate the project before upgrading"
            )


def install_interop(root: Path, julia: str, python: Path, program: str) -> None:
    """Explicit, reproducible provisioning. No silent source or version updates."""
    source_root = Path(os.environ.get(
        "JUPY_INTEROP_SOURCE", str(Path(__file__).resolve().parent.parent)
    )).expanduser().resolve()
    python_src, julia_src = _interop_sources(source_root)
    destination = root / ".jupy-interop"
    py_dst = destination / "python"
    jl_dst = destination / "julia" / "Jupy"

    marker = root / ".venv" / ".jupy-backend"
    backend = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
    if program == "jupy" and backend == "uv":
        raise JupyError("cannot install pip-backed interop inside a uv-managed project")
    if program == "juuv" and backend not in {"", "uv"}:
        raise JupyError(f"cannot install uv-backed interop inside {backend}-managed project")

    # All possible file/manifest conflicts are checked before modifying a project.
    check_interop_dependencies(root, python_src)
    if destination.is_symlink():
        raise JupyError(f"interop project directory cannot be a symlink: {destination}")
    for src, dst in ((python_src, py_dst), (julia_src, jl_dst)):
        if dst.exists() or dst.is_symlink():
            _check_vendored_source(src, dst)

    destination.mkdir(parents=True, exist_ok=True)
    for src, dst in ((python_src, py_dst), (julia_src, jl_dst)):
        if not dst.exists():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".pytest_cache", "*.egg-info"
            ))

    if program == "juuv":
        command = [find_uv(), "add", "--editable", "./.jupy-interop/python"]
    else:
        command = [str(python), "-m", "pip", "install", "-e", str(py_dst)]
    if run_checked(command, cwd=root).returncode != 0:
        raise JupyError("failed to install the Python interoperability package")
    julia_code = (
        "using Pkg; "
        "Pkg.activate(ARGS[1]); "
        "Pkg.develop(path=ARGS[2]); "
        "Pkg.instantiate()"
    )
    if run_checked(
        [julia, "--startup-file=no", "--history-file=no", "-e",
         julia_code, str(root), ".jupy-interop/julia/Jupy"],
        cwd=root,
        env=pythoncall_environment(),
    ).returncode != 0:
        raise JupyError(
            "failed to install the Julia interoperability package; "
            "Python setup may have completed and should be inspected"
        )
    if program != "juuv":
        sync_requirements(root, python, program)
    atomic_write_text(state_file(root), julia_environment_fingerprint(root) + "\n")
    log(program, "interop runtime installed; Julia and Python project dependencies updated")


def usage() -> str:
    return (
        "usage: jupy_core.py {jupy|jupip|juuv} [arguments...]\n"
        "\n"
        "This file is normally called through the jupy, jupip, or juuv launcher."
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)

    if sys.version_info < (3, 11):
        print("jupy: Python 3.11 or newer is required", file=sys.stderr)
        return 2

    if not arguments or arguments[0] not in {"jupy", "jupip", "juuv"}:
        print(usage(), file=sys.stderr)
        return 2

    program = arguments.pop(0)

    # This variable is intentionally separate from Julia's and pip's own
    # --version options, which continue to pass through to those programs.
    if arguments == ["--jupy-tool-version"]:
        print(TOOL_VERSION)
        return 0

    try:
        root = find_project_root()
        verbose(program, f"resolved project root: {root}")

        if program == "juuv":
            # uv owns Python metadata; do not create requirements.txt or invoke pip.
            gitignore = root / ".gitignore"
            if not gitignore.exists():
                atomic_write_text(gitignore, GITIGNORE_CONTENT)
            venv_python = ensure_uv_environment(root, program)
        else:
            ensure_support_files(root, program)
            venv_python = ensure_virtual_environment(root, program)

        if program == "jupip":
            if not env_flag("JUPY_SKIP_JULIA_SETUP"):
                julia = find_julia()
                ensure_julia_project(root, julia, program)

            return run_jupip(root, venv_python, arguments, program)

        julia = find_julia()
        ensure_julia_project(root, julia, program)
        if arguments == ["--jupy-interop-setup"]:
            install_interop(root, julia, venv_python, program)
            return 0
        return run_jupy(root, julia, venv_python, arguments, program)
    except JupyError as exc:
        log(program, str(exc))
        return 1
    except OSError as exc:
        log(program, f"operating-system error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
