# jupy / jupip shared-core commands

`jupy` and `jupip` provide one project-local Julia–Python environment workflow on Linux, macOS, and native Windows.

- `jupy` creates or discovers a Julia project, creates `.venv/`, adds or instantiates `PythonCall.jl`, binds PythonCall to the local virtual environment, and launches Julia.
- `jupip` runs pip through that same local environment and regenerates `requirements.txt` after successful `install` or `uninstall` operations.

The user-facing commands are:

```text
jupy
jupy analysis.jl
jupip install numpy
jupip uninstall numpy
```

## Package layout

```text
jupy-cli/
├── bin/
│   ├── jupy
│   ├── jupip
│   ├── jupy.ps1
│   ├── jupip.ps1
│   ├── jupy.cmd
│   └── jupip.cmd
├── core/
│   └── jupy_core.py
├── tests/
│   └── test_core.py
├── install.sh
├── uninstall.sh
├── install.ps1
├── uninstall.ps1
└── README.md
```

The Python file under `core/` contains all project-management logic. The files under `bin/` only locate Python and invoke the core in either `jupy` or `jupip` mode.

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

From the package directory:

```bash
chmod +x install.sh uninstall.sh bin/jupy bin/jupip
./install.sh
```

The default locations are:

```text
~/.local/share/jupy/
~/.local/bin/jupy
~/.local/bin/jupip
```

If `~/.local/bin/jupy` or `~/.local/bin/jupip` is already a regular file, the installer preserves it with a `.pre-shared-core` suffix before installing the new launcher. This protects the earlier Linux-only implementation during migration.

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
%LOCALAPPDATA%\Jupy\bin\jupy.cmd
%LOCALAPPDATA%\Jupy\bin\jupip.cmd
```

The installer adds `%LOCALAPPDATA%\Jupy\bin` to the current user’s `PATH`. Open a new terminal afterward.

The `.cmd` shims allow the same commands to work from PowerShell, Command Prompt, Windows Terminal, and the VS Code integrated terminal:

```powershell
jupy
jupip install numpy
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

8. Launches Julia with `--project=<resolved project root>`.

Examples:

```bash
jupy
jupy script.jl
jupy -t auto script.jl
jupy -e 'using PythonCall; println(pyimport("sys").executable)'
```

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

A portable `.vscode/tasks.json` entry can invoke `jupy`:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Jupy: Run current Julia file",
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

The Julia extension’s own Run and Debug buttons do not automatically route Julia through `jupy`; use the integrated terminal or an explicit VS Code task when this bootstrap behavior is required.

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

The unit tests validate project discovery, platform-specific virtual-environment paths, support-file preservation, PythonCall dependency detection, pip mutation detection, and Julia-state fingerprinting.

The Linux/macOS launchers and shared core can be syntax-checked with:

```bash
bash -n bin/jupy bin/jupip install.sh uninstall.sh
python3 -m py_compile core/jupy_core.py
```

Native Windows launchers should additionally be tested on a Windows host or Windows CI runner.

## Tool version

The shared core version can be queried without bootstrapping a project:

```bash
jupy --jupy-tool-version
jupip --jupy-tool-version
```

This package reports version `1.0.0`.
