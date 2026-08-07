# jupy / jupip / jupyup shared-core commands

`jupy`, `jupip`, and `jupyup` provide one project-local Julia–Python environment workflow on Linux, macOS, and native Windows, together with a self-updater for the CLI itself.

- `jupy` creates or discovers a Julia project, creates `.venv/`, adds or instantiates `PythonCall.jl`, binds PythonCall to the local virtual environment, and dispatches Julia or Python scripts through the project environment.
- `jupip` runs pip through that same local Python environment and regenerates `requirements.txt` after successful `install` or `uninstall` operations.
- `jupyup` checks the latest published GitHub release of `jupy-cli` and updates the installed CLI without modifying project-local environments.

The user-facing commands are:

```text
jupy
jupy analysis.jl
jupy analysis.py
jupip install numpy
jupip uninstall numpy
jupyup
```

## Package layout

```text
jupy-cli/
├── bin/
│   ├── jupy
│   ├── jupip
│   ├── jupyup
│   ├── jupy.ps1
│   ├── jupip.ps1
│   ├── jupyup.ps1
│   ├── jupy.cmd
│   ├── jupip.cmd
│   └── jupyup.cmd
├── core/
│   ├── jupy_core.py
│   └── jupy_update.py
├── tests/
│   ├── test_core.py
│   └── test_update.py
├── install.sh
├── uninstall.sh
├── install.ps1
├── uninstall.ps1
├── LICENSE
├── README.md
└── VERSION
```

`core/jupy_core.py` contains the project-management and execution logic used by `jupy` and `jupip`. `core/jupy_update.py` contains the self-update logic used by `jupyup`. The files under `bin/` are thin platform-specific launchers.

## Requirements

Each system needs:

1. Julia available through `julia`, or specified with `JUPY_JULIA`.
2. Python 3.8 or newer.
3. Python virtual-environment support.

On Debian, Ubuntu, or Linux Mint, virtual-environment support may require:

```bash
sudo apt install python3-venv
```

## Linux and macOS installation
Clone the repository:
```bash
git clone https://github.com/alt-f4-dev/jupy-cli
```
From the inside the package directory:

```bash
chmod +x install.sh uninstall.sh bin/jupy bin/jupip bin/jupyup
./install.sh
```

The default locations are:

```text
~/.local/share/jupy/
~/.local/bin/jupy
~/.local/bin/jupip
~/.local/bin/jupyup
```

If `~/.local/bin/jupy`, `~/.local/bin/jupip`, or `~/.local/bin/jupyup` is already a regular file, the installer preserves it with a `.pre-shared-core` suffix before installing the new launcher. This protects the earlier Linux-only implementation during migration.

If `~/.local/bin` is not already on `PATH`, add this to `~/.bashrc`, `~/.zshrc`, or the applicable shell profile:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then open a new terminal or reload the shell profile.

Custom installation locations may be supplied with:

```bash
JUPY_INSTALL_ROOT=/custom/data/jupy \
JUPY_BIN_DIR=/custom/bin \
./install.sh
```

Uninstall with:

```bash
./uninstall.sh
```

## Native Windows installation

Open PowerShell in the package directory and run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

The default installation is:

```text
%LOCALAPPDATA%\Jupy\core\jupy_core.py
%LOCALAPPDATA%\Jupy\core\jupy_update.py
%LOCALAPPDATA%\Jupy\bin\jupy.cmd
%LOCALAPPDATA%\Jupy\bin\jupip.cmd
%LOCALAPPDATA%\Jupy\bin\jupyup.cmd
```

The installer adds `%LOCALAPPDATA%\Jupy\bin` to the current user’s `PATH`. Open a new terminal afterward.

The `.cmd` shims allow the same commands to work from PowerShell, Command Prompt, Windows Terminal, and the VS Code integrated terminal:

```powershell
jupy
jupy analysis.py
jupip install numpy
jupyup --check
```

Uninstall with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1
```

## What happens in a new directory

Starting from an empty directory:

```bash
mkdir calculation
cd calculation
jupy
```

or, on PowerShell:

```powershell
mkdir calculation
cd calculation
jupy
```

creates or initializes:

```text
calculation/
├── .gitignore
├── .venv/
├── Manifest.toml
├── Project.toml
└── requirements.txt
```

When `.gitignore` does not exist, it is created with:

```text
.venv/
LocalPreferences.toml
.CondaPkg/
```

Existing `.gitignore` and `requirements.txt` files are not overwritten during bootstrap.

## `jupy` behavior

`jupy` performs these operations:

1. Searches upward from the working directory for `JuliaProject.toml` or `Project.toml`.
2. Uses the nearest enclosing Julia project when one exists.
3. Otherwise treats the current directory as a new project root.
4. Creates `.gitignore` and `requirements.txt` when absent.
5. Creates `.venv/` with the platform-appropriate layout:
   - Linux/macOS: `.venv/bin/python`
   - Windows: `.venv\Scripts\python.exe`
6. Adds `PythonCall.jl` if absent, or instantiates the Julia environment if present.
7. Sets:

   ```text
   JULIA_CONDAPKG_BACKEND=Null
   JULIA_PYTHONCALL_EXE=@venv
   ```

8. Dispatches execution according to the first argument:
   - No script or a non-`.py` first argument is passed through to Julia with `--project=<resolved project root>`.
   - A first argument ending in `.py` is executed directly with the resolved project's `.venv` Python interpreter.

Examples:

```bash
jupy
jupy script.jl
jupy -t auto script.jl
jupy -e 'using PythonCall; println(pyimport("sys").executable)'
jupy script.py
jupy script.py input.dat --output result.dat
```

For Python scripts, `jupy` runs the equivalent of:

```text
<project>/.venv/bin/python script.py ...              # Linux/macOS
<project>\.venv\Scripts\python.exe script.py ...   # Windows
```

This lets standalone Python scripts and Julia scripts using `PythonCall.jl` share the same project-local Python environment. The `.py` dispatch is intentionally determined by the first argument; Julia command-line options continue to pass through unchanged.

## `jupip` behavior

`jupip` routes all pip operations through the local environment:

```text
<project>/.venv/bin/python -m pip              # Linux/macOS
<project>\.venv\Scripts\python.exe -m pip     # Windows
```

Examples:

```bash
jupip install numpy scipy
jupip uninstall numpy
jupip install -r requirements.txt
jupip list
jupip show scipy
```

After a successful `install` or `uninstall`, the core runs `pip freeze` and atomically replaces `requirements.txt`. A failed pip operation leaves the existing file unchanged.

`requirements.txt` is therefore an exact environment snapshot, including transitive dependencies. Pip may leave orphaned dependencies after an uninstall; those packages remain in `requirements.txt` because they remain installed in `.venv/`.


## `jupyup` behavior

`jupyup` updates the installed `jupy` / `jupip` / `jupyup` CLI itself. It does not operate on the current Julia–Python project and does not modify `.venv/`, `Project.toml`, `Manifest.toml`, or `requirements.txt`.

The updater compares the installed CLI version with the latest published GitHub release of `alt-f4-dev/jupy-cli`.

Examples:

```bash
jupyup
jupyup --check
jupyup --version
jupyup --force
```

- `jupyup` checks for a newer published release and installs it when available.
- `jupyup --check` reports whether an update is available without changing the installation.
- `jupyup --version` prints the installed CLI version.
- `jupyup --force` reinstalls the latest release when the installed version already matches it.

Before installing an update, `jupyup` downloads the release archive to a temporary directory, validates the expected platform-specific file layout, verifies that the release tag agrees with `VERSION`, syntax-checks the Python cores, and then atomically replaces the installed CLI files. Existing POSIX launcher symlinks are preserved.

The first version that introduces `jupyup` must be installed through the normal installer. After that bootstrap installation, future published releases can be applied with:

```bash
jupyup
```

## Environment variables

| Variable | Purpose |
|---|---|
| `JUPY_PYTHON` | Python interpreter used to run the core and create `.venv/` |
| `JUPY_JULIA` | Julia executable or command name |
| `JUPY_CORE` | Explicit path to `jupy_core.py` |
| `JUPY_VERBOSE=1` | Print resolved project and interpreter information |
| `JUPY_FORCE_SETUP=1` | Force Julia dependency setup even when the cached state matches |
| `JUPY_INSTALL_ROOT` | Override installer data directory |
| `JUPY_BIN_DIR` | Override Linux/macOS command directory |
| `JUPY_GITHUB_REPOSITORY` | Override the GitHub repository queried by `jupyup` |
| `JUPY_GITHUB_API_VERSION` | Override the GitHub API version header used by `jupyup` |

Examples:

```bash
JUPY_PYTHON=/usr/bin/python3.12 jupy
JUPY_JULIA=$HOME/julia/bin/julia jupy
JUPY_VERBOSE=1 jupy analysis.jl
JUPY_FORCE_SETUP=1 jupy
```

PowerShell equivalents are:

```powershell
$env:JUPY_PYTHON = "C:\Python312\python.exe"
$env:JUPY_VERBOSE = "1"
jupy
```

## VS Code

These are terminal commands, not editor-specific commands. They work in the VS Code integrated terminal whenever they work in the selected shell:

- Linux: Bash or another POSIX terminal.
- macOS: Zsh or Bash.
- Native Windows: PowerShell or Command Prompt through the `.cmd` shims.
- Windows WSL: the Linux installation inside WSL.

A portable `.vscode/tasks.json` entry can invoke `jupy` for either a Julia (`.jl`) or Python (`.py`) file:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Jupy: Run current file",
      "type": "shell",
      "command": "jupy",
      "args": ["${file}"],
      "options": {
        "cwd": "${workspaceFolder}"
      },
      "problemMatcher": []
    }
  ]
}
```

Editor Run and Debug actions do not automatically route execution through `jupy`; use the integrated terminal or an explicit VS Code task when the shared project bootstrap and dispatch behavior is required.

## Sharing projects

Do not copy `.venv/` between users or operating systems. Commit the reproducibility files instead:

```text
Project.toml
Manifest.toml
requirements.txt
```

A collaborator can clone the repository and run:

```bash
jupy
```

for the Julia project requirements and then run:

```bash
jupip install -r requirements.txt
```

for the Python requirements. 

The local Julia and Python environments will then be recreated on that system.

## Validation

Run the platform-independent unit tests with:

```bash
python3 -m unittest discover -s tests -v
```

On Windows:

```powershell
py -3 -m unittest discover -s tests -v
```

The unit tests validate project discovery, platform-specific virtual-environment paths, support-file preservation, PythonCall dependency detection, pip mutation detection, Julia-state fingerprinting, semantic-version ordering, release-tree validation, platform-specific updater manifests, and updater installation behavior.

The Linux/macOS launchers and Python cores can be syntax-checked with:

```bash
bash -n bin/jupy bin/jupip bin/jupyup install.sh uninstall.sh
python3 -m py_compile core/jupy_core.py core/jupy_update.py
```

The GitHub Actions test matrix should run the unit tests on Linux, macOS, and Windows. Native Windows launchers should additionally be exercised on a Windows host or Windows CI runner.

## Tool version

The shared CLI version can be queried without bootstrapping a project:

```bash
jupy --jupy-tool-version
jupip --jupy-tool-version
jupyup --version
```

`VERSION` is the canonical release version. `TOOL_VERSION` in `core/jupy_core.py` should remain synchronized with it. Published release tags use the form `v<VERSION>`, for example `v0.0.2`.
