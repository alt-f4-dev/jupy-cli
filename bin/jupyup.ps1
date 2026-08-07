# Native Windows PowerShell launcher for the shared jupyup updater core.
$ErrorActionPreference = "Stop"

function Resolve-JupyUpdateCore {
    if ($env:JUPY_UPDATE_CORE) {
        if (-not (Test-Path -LiteralPath $env:JUPY_UPDATE_CORE -PathType Leaf)) {
            throw "JUPY_UPDATE_CORE does not exist: $($env:JUPY_UPDATE_CORE)"
        }
        return (Resolve-Path -LiteralPath $env:JUPY_UPDATE_CORE).Path
    }

    $candidates = @(
        (Join-Path $PSScriptRoot "..\core\jupy_update.py")
    )

    if ($env:JUPY_INSTALL_ROOT) {
        $candidates += (Join-Path $env:JUPY_INSTALL_ROOT "core\jupy_update.py")
    }

    $candidates += (Join-Path $env:LOCALAPPDATA "Jupy\core\jupy_update.py")

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "Could not locate jupy_update.py. Reinstall jupy or set JUPY_UPDATE_CORE."
}

function Resolve-JupyPython {
    if ($env:JUPY_PYTHON) {
        if (Test-Path -LiteralPath $env:JUPY_PYTHON -PathType Leaf) {
            return [PSCustomObject]@{
                Executable = (Resolve-Path -LiteralPath $env:JUPY_PYTHON).Path
                Prefix = @()
            }
        }

        $configured = Get-Command $env:JUPY_PYTHON -ErrorAction SilentlyContinue
        if ($configured) {
            return [PSCustomObject]@{ Executable = $configured.Source; Prefix = @() }
        }
        throw "JUPY_PYTHON is not executable: $($env:JUPY_PYTHON)"
    }

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        return [PSCustomObject]@{ Executable = $py.Source; Prefix = @("-3") }
    }

    foreach ($name in @("python.exe", "python3.exe")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            return [PSCustomObject]@{ Executable = $command.Source; Prefix = @() }
        }
    }

    throw "Python 3 was not found in PATH."
}

try {
    $core = Resolve-JupyUpdateCore
    $python = Resolve-JupyPython
    $arguments = @($python.Prefix) + @($core) + @($args)
    & $python.Executable @arguments
    exit $LASTEXITCODE
}
catch {
    [Console]::Error.WriteLine("jupyup: $($_.Exception.Message)")
    exit 1
}
