$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$AppName = "3D Scan Prep Tool"
$AppExe = Join-Path $RepoRoot "dist\$AppName\$AppName.exe"
$InnoScript = Join-Path $PSScriptRoot "inno\ScanPrepTool.iss"

function Find-InnoCompiler {
    $candidates = @()
    if ($env:ProgramFiles) { $candidates += Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe" }
    if (${env:ProgramFiles(x86)}) { $candidates += Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe" }
    if ($env:LocalAppData) { $candidates += Join-Path $env:LocalAppData "Programs\Inno Setup 6\ISCC.exe" }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }

    $cmd = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

Write-Host "============================================================"
Write-Host "  ScanPrep Windows installer build"
Write-Host "============================================================"
Write-Host ""
Write-Host "This turns the packaged app folder into a Windows setup wizard."
Write-Host "All paths are relative to this repository:"
Write-Host "  $($RepoRoot.Path)"

if (-not (Test-Path -LiteralPath $AppExe)) {
    throw "Built app was not found. Run .\windows\build_backend.ps1 and .\windows\package_app.ps1 first."
}
if (-not (Test-Path -LiteralPath $InnoScript)) {
    throw "Inno script was not found: $InnoScript"
}

$IsccExe = Find-InnoCompiler
if (-not $IsccExe) {
    throw "Inno Setup compiler was not found. Install Inno Setup 6 from https://jrsoftware.org/isdl.php and run this script again."
}

$OutputDir = Join-Path $RepoRoot "Packaged"
if (Test-Path -LiteralPath $OutputDir) {
    Get-ChildItem -LiteralPath $OutputDir -Filter "$AppName*" -File |
        Remove-Item -Force
} else {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

Write-Host ""
Write-Host "Using Inno compiler:"
Write-Host "  $IsccExe"
Write-Host ""
Write-Host "Building installer..."
& $IsccExe $InnoScript

Write-Host ""
Write-Host "Installer build complete."
Write-Host "Output folder:"
Write-Host "  $OutputDir"
Write-Host ""
Write-Host "Upload the setup EXE and all matching BIN parts from that folder."
