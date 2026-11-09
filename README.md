# jupy-cli

**One command to run Julia and Python in the same project environment.**

`jupy-cli` sets up a Julia project, connects [PythonCall.jl](https://github.com/JuliaPy/PythonCall.jl) to a project-local Python environment, and runs Julia (`.jl`) or Python (`.py`) scripts. Choose **pip** or **uv** for Python dependency management; Julia dependencies continue to use Julia's `Pkg`.

Works on Linux, macOS, and native Windows.

## Quick start

Choose **one** Python backend for each project.

### Option A — pip (`jupy`)

```bash
mkdir calculation
cd calculation
jupy
jupip install numpy scipy
jupy analysis.py
jupy simulation.jl
```

`jupy` creates `.venv/`, initializes the Julia project and PythonCall, and uses `requirements.txt` to record the installed Python packages. `jupip` runs pip inside that environment.

### Option B — uv (`juuv`)

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) separately before using this option.

```bash
mkdir calculation
cd calculation
juuv
uv add numpy scipy
juuv analysis.py
juuv simulation.jl
```

`juuv` initializes a native uv project when needed and runs `uv sync` before execution. Python dependencies are managed by uv through `pyproject.toml` and `uv.lock`. It does **not** call pip or maintain `requirements.txt`. **uv is optional for jupy-cli**: neither `jupy` nor `jupip` requires it.

Both options run Julia with the same Julia project and configure PythonCall to use the project's `.venv`.

## Experimental bidirectional runtime (`interop` branch)

The `interop` branch adds an opt-in runtime facade backed by **JuliaCall** (Python → Julia) and **PythonCall** (Julia → Python), with process-local runtime reuse, deterministic Julia project ownership, and module caching. It does **not** translate source code or implement a replacement low-level bridge. This feature is not included in the v0.0.3 release.

After cloning and installing the `interop` branch, initialize a project using `jupy` or `juuv`, then run exactly one of:

```bash
juuv --jupy-interop-setup  # uv project
jupy --jupy-interop-setup  # pip project
```

Setup vendors the interface packages into the project at `.jupy-interop/`, registers Julia package `Jupy`, and installs Python package `jupy-interop`. Both Julia and Python dependencies become part of the project lock/configuration files. The command is explicit because it modifies project files.

Python calling Julia:

```python
from jupy import julia
solver = julia.import_module("LatticeSolver", path="LatticeSolver.jl")
result = solver.solve(x)
```

Julia calling Python:

```julia
using Jupy
numpy = Jupy.pyimport("numpy")
result = numpy.asarray([1, 2, 3])
```

An embedded Julia runtime is initialized **once per Python process** and reused for subsequent calls. A new shell invocation starts a new process; no persistent cross-process daemon is created. The Julia project/executable cannot be switched once the process has initialized Julia. See [runtime contracts and test instructions](docs/interop-runtime.md).

## Commands

| Command | Purpose | Examples |
| --- | --- | --- |
| `jupy` | Set up/run Julia or Python using the pip/venv backend | `jupy analysis.jl`, `jupy analysis.py` |
| `jupip` | Run pip in the project environment; refresh `requirements.txt` after successful install/uninstall | `jupip install numpy` |
| `juuv` | Set up/sync a native uv project, then run Julia or Python | `juuv analysis.jl`, `juuv analysis.py` |
| `jupyup` | Check for or install a published jupy-cli release | `jupyup --check`, `jupyup` |

Use `jupy` or `juuv` without arguments to launch Julia after project setup. Julia arguments pass through unchanged:

```bash
jupy -t auto simulation.jl
juuv -e 'using PythonCall; println(pyimport("sys").executable)'
juuv analysis.py input.dat --output result.dat
```

Only a **first argument ending in `.py`** selects direct Python-script execution; otherwise arguments go to Julia.

## Installation

### Requirements

- Julia available as `julia` on `PATH` (or set `JUPY_JULIA`).
- Python **3.11 or newer** for the jupy-cli launchers and core.
- For `jupy`/`jupip`: Python virtual-environment and pip support. On some Debian, Ubuntu, or Linux Mint installations, run `sudo apt install python3-venv`.
- For `juuv` only: an installed `uv` executable on `PATH` (or set `JUPY_UV`).

The installer does not install Julia, Python, or uv.

### Linux / macOS

To install the latest source checkout:

```bash
git clone https://github.com/alt-f4-dev/jupy-cli.git
cd jupy-cli
./install.sh
```

By default, application files go to `~/.local/share/jupy/` and commands are linked into `~/.local/bin/`. If `~/.local/bin` is not on your `PATH`, add this to your shell configuration:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Restart the terminal or reload the shell configuration. The installer backs up pre-existing regular command files with a `.pre-shared-core` suffix; reinstallation replaces its managed symlinks.

To use custom locations:

```bash
JUPY_INSTALL_ROOT=/custom/data/jupy JUPY_BIN_DIR=/custom/bin ./install.sh
```

To uninstall from the repository directory:

```bash
./uninstall.sh
```

### Windows

Clone the repository, open PowerShell in the repository directory, and run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

The installation lives in `%LOCALAPPDATA%\Jupy\`. Its `bin` directory is added to your **user** `PATH`; open a new terminal after installation. The `.cmd` launchers support PowerShell, Command Prompt, Windows Terminal, and editor terminals.

To uninstall from the repository directory:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1
```

### Verify installation

```bash
jupy --jupy-tool-version
juuv --jupy-tool-version
jupip --jupy-tool-version
jupyup --version
```

These version queries do not initialize a project.

## Working with projects

### What is created?

The first `jupy` invocation in a new directory typically produces:

```text
calculation/
├── .venv/             # Local Python environment
├── .gitignore
├── Project.toml       # Julia dependencies
├── Manifest.toml      # Julia resolved environment
└── requirements.txt   # Pip environment snapshot
```

The first `juuv` invocation instead creates the native uv metadata:

```text
calculation/
├── .venv/
├── .gitignore
├── Project.toml
├── Manifest.toml
├── pyproject.toml     # Python project/dependencies
└── uv.lock            # Locked Python resolution
```

`Project.toml` and `Manifest.toml` are Julia-managed in both workflows. `juuv` uses `uv init --bare --no-workspace` when no `pyproject.toml` exists, then `uv sync`. Both commands add `PythonCall.jl` if absent, or instantiate existing Julia dependencies.

### Existing projects and subdirectories

The launcher searches upward from the working directory for the nearest `Project.toml` or `JuliaProject.toml`. If it finds neither, it uses the current directory as a new Julia project root.

Run the chosen command from the project directory or one of its subdirectories. For a new project, initialize at the intended root.

### Do not silently mix pip and uv environments

Both backends conventionally use the same `.venv/` directory. `uv sync` may remove packages that are not declared in the uv project. For safety, `juuv` refuses to synchronize an existing `.venv/` without recognizable uv ownership metadata (the uv marker in `pyvenv.cfg` or `.jupy-backend`).

**Choose `jupy` or `juuv` per project.** If you need to change backend, migrate Python dependencies intentionally; do not assume that invoking the other command converts an existing environment. The existing `jupy` and `jupip` paths are preserved, but they do not enforce the same uv ownership check.

### Sharing a project

Commit the appropriate dependency metadata, **not** the local `.venv/`:

| Backend | Commit |
| --- | --- |
| pip | `Project.toml`, `Manifest.toml`, `requirements.txt` |
| uv | `Project.toml`, `Manifest.toml`, `pyproject.toml`, `uv.lock` |

After cloning a pip-based project:

```bash
jupy
jupip install -r requirements.txt
```

After cloning a uv-based project:

```bash
juuv
```

`juuv` runs `uv sync` as part of project setup.

## Updating the CLI

```bash
jupyup --check     # Check without installing
jupyup             # Install the latest published release, if newer
jupyup --version   # Installed CLI version
jupyup --force     # Reinstall the latest release
```

`jupyup` updates **the CLI installation**, not the Python or Julia dependencies in your projects. It uses published GitHub releases; a development branch is not automatically installed through `jupyup`. To install the current `juuv-ext` checkout, rerun its installer.

## Configuration and troubleshooting

| Setting | Meaning |
| --- | --- |
| `JUPY_JULIA` | Julia executable or command |
| `JUPY_PYTHON` | Python interpreter used to launch the CLI and create pip-backed environments |
| `JUPY_UV` | uv executable or command for `juuv` |
| `JUPY_CORE` | Override path to `jupy_core.py` |
| `JUPY_VERBOSE=1` | Show resolved project and interpreter paths |
| `JUPY_FORCE_SETUP=1` | Repeat Julia dependency setup even when the cached state matches |
| `JUPY_INSTALL_ROOT` | Override installation data directory |
| `JUPY_BIN_DIR` | Override POSIX executable link directory |
| `JUPY_GITHUB_REPOSITORY` | Repository checked by `jupyup` |
| `JUPY_GITHUB_API_VERSION` | GitHub API version header for `jupyup` |

**Command not found?** Check that the installer completed and its command directory is on `PATH`; restart the terminal after editing `PATH`.

**Julia not found?** Install Julia or set `JUPY_JULIA` to its executable.

**uv not found?** Install uv separately or set `JUPY_UV`. This is needed only for `juuv`.

**Python virtual environment fails with `jupy`?** Check Python 3.11+ and virtual-environment support. On Debian-based systems, `python3-venv` may be required.

**`juuv` rejects an existing `.venv`?** It detected an environment it cannot safely identify as uv-managed. Preserve the environment and explicitly migrate or use a separate project directory.

**Which Python is Julia using?** Inspect the binding:

```bash
juuv -e 'using PythonCall; println(pyimport("sys").executable)'
```

The CLI configures `JULIA_CONDAPKG_BACKEND=Null` and `JULIA_PYTHONCALL_EXE=@venv` for Julia execution. This keeps PythonCall pointed toward the project-local environment.

## Development

The shared Python core is `core/jupy_core.py`; `core/jupy_update.py` manages CLI updates. Launchers live in `bin/` and unit tests in `tests/`.

Run tests:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile core/jupy_core.py core/jupy_update.py
bash -n bin/jupy bin/jupip bin/juuv bin/jupyup install.sh uninstall.sh
```

The Bash syntax check applies to Linux/macOS. CI runs Python tests across Linux, macOS, and Windows. Unit tests do not replace end-to-end validation with real Julia, PythonCall, and uv installations.

CLI version is stored in `VERSION` and mirrored in `TOOL_VERSION` inside `core/jupy_core.py`; published release tags use `v<VERSION>`.

See [LICENSE](LICENSE) for licensing information.
