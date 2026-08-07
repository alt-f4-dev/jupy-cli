# Install jupy, jupip, and jupyup for the current Windows user.

[CmdletBinding()]
param(
    [string]$InstallRoot = $(if ($env:JUPY_INSTALL_ROOT) { $env:JUPY_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA "Jupy" }),
    [switch]$DoNotModifyPath
)

$ErrorActionPreference = "Stop"
$SourceRoot = $PSScriptRoot
$BinDirectory = Join-Path $InstallRoot "bin"
$CoreDirectory = Join-Path $InstallRoot "core"

New-Item -ItemType Directory -Force -Path $BinDirectory, $CoreDirectory | Out-Null

Copy-Item -Force (Join-Path $SourceRoot "VERSION") (Join-Path $InstallRoot "VERSION")
Copy-Item -Force (Join-Path $SourceRoot "core\jupy_core.py") (Join-Path $CoreDirectory "jupy_core.py")
Copy-Item -Force (Join-Path $SourceRoot "core\jupy_update.py") (Join-Path $CoreDirectory "jupy_update.py")

foreach ($file in @(
    "jupy.ps1", "jupip.ps1", "jupyup.ps1",
    "jupy.cmd", "jupip.cmd", "jupyup.cmd"
)) {
    Copy-Item -Force (Join-Path $SourceRoot "bin\$file") (Join-Path $BinDirectory $file)
}

if (-not $DoNotModifyPath) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $entries = @($userPath -split ";" | Where-Object { $_ })

    if ($entries -notcontains $BinDirectory) {
        $newPath = if ([string]::IsNullOrWhiteSpace($userPath)) {
            $BinDirectory
        } else {
            "$userPath;$BinDirectory"
        }

        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Host "Added $BinDirectory to the user PATH."
    }
}

Write-Host "Installed jupy core: $CoreDirectory\jupy_core.py"
Write-Host "Installed jupy updater: $CoreDirectory\jupy_update.py"
Write-Host "Installed commands: $BinDirectory\jupy.cmd, $BinDirectory\jupip.cmd, and $BinDirectory\jupyup.cmd"
Write-Host "Open a new terminal before invoking jupy, jupip, or jupyup."
