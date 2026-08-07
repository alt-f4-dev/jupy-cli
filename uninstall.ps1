# Remove the user-level Windows jupy installation.

[CmdletBinding()]
param(
    [string]$InstallRoot = $(if ($env:JUPY_INSTALL_ROOT) { $env:JUPY_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA "Jupy" }),
    [switch]$KeepPathEntry
)

$ErrorActionPreference = "Stop"
$BinDirectory = Join-Path $InstallRoot "bin"

if (-not $KeepPathEntry) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $entries = @($userPath -split ";" | Where-Object { $_ -and $_ -ne $BinDirectory })
    [Environment]::SetEnvironmentVariable("Path", ($entries -join ";"), "User")
}

if (Test-Path -LiteralPath $InstallRoot) {
    Remove-Item -LiteralPath $InstallRoot -Recurse -Force
}

Write-Host "Removed jupy from $InstallRoot"
