$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvDir = Join-Path $RepoRoot ".venv-scanprep-cu128"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$PipCacheDir = Join-Path $RepoRoot ".pip-cache"
$BackendName = "ScanPrep Tool Backend"
$IconFile = Join-Path $RepoRoot "KIRI Logo ICO.ico"
$ModelsDir = Join-Path $RepoRoot "_AI_Models"
$SpecDir = Join-Path $RepoRoot "windows\pyinstaller"

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

Write-Host "============================================================"
Write-Host "  ScanPrep Windows backend build"
Write-Host "============================================================"
Write-Host ""
Write-Host "This builds the PyInstaller backend used by the Electron app."
Write-Host "All paths are relative to this repository:"
Write-Host "  $($RepoRoot.Path)"

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "scan_prep_engine.py"))) {
    throw "scan_prep_engine.py was not found in the repository root."
}
if (-not (Test-Path -LiteralPath $IconFile)) {
    throw "Icon file was not found: $IconFile"
}
if (-not (Test-Path -LiteralPath $ModelsDir)) {
    throw "_AI_Models was not found. Download _AI_Models from GitHub Releases and extract it into the repository root."
}

if (-not (Test-Path -LiteralPath $PythonExe)) {
    Invoke-Step "Creating Python 3.12 virtual environment" {
        & py -3.12 -m venv $VenvDir
    }
}

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "The virtual environment is incomplete: $PythonExe"
}

$env:PIP_NO_INDEX = $null
$env:PIP_INDEX_URL = $null
$env:PIP_EXTRA_INDEX_URL = $null
$env:HTTP_PROXY = $null
$env:HTTPS_PROXY = $null
$env:ALL_PROXY = $null

Invoke-Step "Checking Python version" {
    & $PythonExe -c "import sys; print(sys.version); raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
}

Invoke-Step "Installing build dependencies" {
    & $PythonExe -m ensurepip --upgrade --default-pip
    & $PythonExe -m pip install --cache-dir $PipCacheDir --retries 20 --timeout 120 --upgrade pip setuptools wheel
    & $PythonExe -m pip install --cache-dir $PipCacheDir --retries 20 --timeout 120 -r (Join-Path $RepoRoot "windows\requirements-torch-cu128.txt")
    & $PythonExe -m pip install --cache-dir $PipCacheDir --retries 20 --timeout 120 pyinstaller -r (Join-Path $RepoRoot "requirements.txt")
}

Invoke-Step "Checking installed packages" {
    & $PythonExe -m pip check
}

Invoke-Step "Checking packaged GPU architecture coverage" {
    $archCheck = @'
import sys
try:
    import torch
    import torchvision
except Exception as exc:
    raise SystemExit(f"ERROR: Could not import torch/torchvision: {exc}")

targets = [("RTX 20 / Turing", "sm_75"), ("RTX 30 / Ampere", "sm_86"), ("RTX 40 / Ada", "sm_89"), ("RTX 50 / Blackwell", "sm_120")]

def parse_arch(tag):
    for prefix in ("sm_", "compute_"):
        if isinstance(tag, str) and tag.startswith(prefix):
            raw = tag[len(prefix):]
            if raw.isdigit() and len(raw) >= 2:
                return int(raw[:-1]), int(raw[-1])
    return None

def arch_coverage(target, arch_list):
    if target in arch_list or target.replace("sm_", "compute_") in arch_list:
        return True, f"direct {target}"
    requested = parse_arch(target)
    if requested is None:
        return False, "not recognized"
    req_major, req_minor = requested
    compatible = []
    for arch in arch_list:
        parsed = parse_arch(arch)
        if parsed is None:
            continue
        arch_major, arch_minor = parsed
        if arch_major == req_major and arch_minor <= req_minor:
            compatible.append((arch_minor, arch))
    if compatible:
        _, arch = max(compatible)
        return True, f"compatible via {arch}"
    return False, "missing"

print(f"python: {sys.version.split()[0]}")
print(f"torch: {torch.__version__}")
print(f"torch cuda build: {torch.version.cuda}")
print(f"torchvision: {torchvision.__version__}")
arch_list = torch.cuda.get_arch_list() if hasattr(torch.cuda, "get_arch_list") else []
print(f"compiled GPU arch list: {arch_list if arch_list else 'none'}")
missing = []
for label, target in targets:
    ok, note = arch_coverage(target, arch_list)
    print(f"  {'OK' if ok else 'MISSING'}: {label} ({target}) - {note}")
    if not ok:
        missing.append(target)
if "sm_89" not in arch_list and "sm_86" in arch_list:
    print("Note: RTX 40/Ada may be covered through compatible sm_86 kernels.")
print(f"cuda available on this computer: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    for i in range(torch.cuda.device_count()):
        cap = torch.cuda.get_device_capability(i)
        print(f"gpu {i}: {torch.cuda.get_device_name(i)}, capability sm_{cap[0]}{cap[1]}")
    with torch.no_grad():
        x = torch.ones((16, 16), device="cuda:0")
        y = x @ x
        _ = float(y[0, 0].detach().cpu())
    torch.cuda.synchronize(0)
    print("current GPU tiny CUDA smoke test: OK")
if not torch.version.cuda:
    raise SystemExit("ERROR: This is not a CUDA-enabled PyTorch build.")
if missing:
    raise SystemExit("ERROR: This build is missing required GPU coverage.")
print("GPU coverage check passed.")
'@
    $archCheck | & $PythonExe -
    if ($LASTEXITCODE -ne 0) {
        throw "PyTorch GPU coverage check failed."
    }
}

Invoke-Step "Checking bundled video extractor" {
    $ffmpegCheck = @'
import os
import subprocess
try:
    import imageio_ffmpeg
except Exception as exc:
    raise SystemExit(f"ERROR: imageio-ffmpeg is not installed: {exc}")
exe = imageio_ffmpeg.get_ffmpeg_exe()
if not exe or not os.path.exists(exe):
    raise SystemExit(f"ERROR: ffmpeg binary was not found: {exe}")
print(f"video extractor: {exe}")
proc = subprocess.run([exe, "-version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
if proc.returncode != 0:
    raise SystemExit("ERROR: ffmpeg version check failed.\n" + (proc.stderr or proc.stdout))
print((proc.stdout or "ffmpeg version unknown").splitlines()[0])
print("Video extraction check passed.")
'@
    $ffmpegCheck | & $PythonExe -
    if ($LASTEXITCODE -ne 0) {
        throw "Video extraction support is not installed in the build environment."
    }
}

Invoke-Step "Cleaning previous PyInstaller outputs" {
    Remove-RepoChild (Join-Path $RepoRoot "build")
    Remove-RepoChild (Join-Path $RepoRoot "dist")
    New-Item -ItemType Directory -Force -Path $SpecDir | Out-Null
}

Invoke-Step "Building backend with PyInstaller" {
    & $PythonExe -m PyInstaller `
        --name $BackendName `
        --specpath $SpecDir `
        --clean `
        --noconfirm `
        --onedir `
        --icon $IconFile `
        --exclude-module pytest `
        --exclude-module tensorboard `
        --exclude-module IPython `
        --hidden-import kornia `
        --hidden-import einops `
        --hidden-import timm `
        --hidden-import imageio_ffmpeg `
        --copy-metadata scipy `
        --copy-metadata imageio_ffmpeg `
        --collect-all torch `
        --collect-all torchvision `
        --collect-all imageio_ffmpeg `
        --add-data "$ModelsDir;_AI_Models" `
        (Join-Path $RepoRoot "scan_prep_engine.py")
}

Write-Host ""
Write-Host "Backend build complete:"
Write-Host "  dist\$BackendName\$BackendName.exe"
Write-Host ""
Write-Host "Next run:"
Write-Host "  .\windows\package_app.ps1"
