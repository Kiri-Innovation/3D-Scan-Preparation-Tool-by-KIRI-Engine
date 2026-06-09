$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$AppName = "3D Scan Prep Tool"
$BackendName = "ScanPrep Tool Backend"
$ElectronUiDir = Join-Path $RepoRoot "electron-ui"
$ElectronDist = Join-Path $ElectronUiDir "node_modules\electron\dist"
$BackendDir = Join-Path $RepoRoot "dist\$BackendName"
$AppDir = Join-Path $RepoRoot "dist\$AppName"
$TempDir = Join-Path $RepoRoot "dist\_electron_package_tmp"
$AppIcon = Join-Path $RepoRoot "KIRI Logo ICO.ico"
$RceditExe = Join-Path $ElectronUiDir "node_modules\rcedit\bin\rcedit-x64.exe"

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Host ""
    Write-Host "== $Label =="
    & $Command
}

function Remove-RepoChild {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $resolved = Resolve-Path -LiteralPath $Path
    if (-not $resolved.Path.StartsWith($RepoRoot.Path, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside the repository: $($resolved.Path)"
    }
    Remove-Item -LiteralPath $resolved.Path -Recurse -Force
}

function Copy-DirectoryContents {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Source folder was not found: $Source"
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
    }
}

Write-Host "============================================================"
Write-Host "  ScanPrep Windows Electron app package"
Write-Host "============================================================"
Write-Host ""
Write-Host "This wraps the Electron UI around the PyInstaller backend."
Write-Host "All paths are relative to this repository:"
Write-Host "  $($RepoRoot.Path)"

if (-not (Test-Path -LiteralPath (Join-Path $BackendDir "$BackendName.exe"))) {
    throw "Backend build was not found. Run .\windows\build_backend.ps1 first."
}
if (-not (Test-Path -LiteralPath $AppIcon)) {
    throw "App icon was not found: $AppIcon"
}

if (-not (Test-Path -LiteralPath (Join-Path $ElectronDist "electron.exe"))) {
    Invoke-Step "Installing Electron dependencies" {
        Push-Location $ElectronUiDir
        try {
            & npm install
        } finally {
            Pop-Location
        }
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $ElectronDist "electron.exe"))) {
    throw "Electron runtime was not found after npm install."
}
if (-not (Test-Path -LiteralPath $RceditExe)) {
    throw "rcedit was not found after npm install. It is needed to apply the Windows app icon."
}

Invoke-Step "Preparing app folder" {
    Remove-RepoChild $TempDir
    Remove-RepoChild $AppDir
    New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
}

Invoke-Step "Copying Electron runtime" {
    Copy-DirectoryContents $ElectronDist $TempDir
    $defaultAsar = Join-Path $TempDir "resources\default_app.asar"
    if (Test-Path -LiteralPath $defaultAsar) {
        Remove-Item -LiteralPath $defaultAsar -Force
    }
}

Invoke-Step "Copying Electron UI" {
    $appResources = Join-Path $TempDir "resources\app"
    New-Item -ItemType Directory -Force -Path $appResources | Out-Null
    Copy-Item -LiteralPath (Join-Path $ElectronUiDir "main.js") -Destination (Join-Path $appResources "main.js") -Force
    Copy-Item -LiteralPath (Join-Path $ElectronUiDir "preload.js") -Destination (Join-Path $appResources "preload.js") -Force
    Copy-Item -LiteralPath (Join-Path $ElectronUiDir "package.json") -Destination (Join-Path $appResources "package.json") -Force
    Copy-DirectoryContents (Join-Path $ElectronUiDir "renderer") (Join-Path $appResources "renderer")
}

Invoke-Step "Copying brand assets" {
    Copy-DirectoryContents (Join-Path $RepoRoot "Images and Icons") (Join-Path $TempDir "resources\Images and Icons")
    Copy-Item -LiteralPath $AppIcon -Destination (Join-Path $TempDir "KIRI Logo ICO.ico") -Force
}

Invoke-Step "Copying backend tool" {
    Copy-DirectoryContents $BackendDir (Join-Path $TempDir "resources\backend")
}

Invoke-Step "Creating user-facing app executable" {
    $electronExe = Join-Path $TempDir "electron.exe"
    $appExe = Join-Path $TempDir "$AppName.exe"
    if (Test-Path -LiteralPath $electronExe) {
        Rename-Item -LiteralPath $electronExe -NewName "$AppName.exe"
    }
    if (-not (Test-Path -LiteralPath $appExe)) {
        throw "Could not create $AppName.exe"
    }
    & $RceditExe $appExe --set-icon $AppIcon
}

Invoke-Step "Moving final app folder into dist" {
    Move-Item -LiteralPath $TempDir -Destination $AppDir
}

Write-Host ""
Write-Host "Electron app folder complete:"
Write-Host "  dist\$AppName\$AppName.exe"
Write-Host ""
Write-Host "Open that EXE to test the user-facing app."
Write-Host "Then run:"
Write-Host "  .\windows\build_inno_installer.ps1"

