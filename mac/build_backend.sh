#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="${SCANPREP_VENV:-$REPO_ROOT/.venv-scanprep-macos}"
PYTHON_EXE="$VENV_DIR/bin/python"
BACKEND_NAME="ScanPrep Tool Backend"
MODELS_DIR="$REPO_ROOT/_AI_Models"
SPEC_DIR="$REPO_ROOT/mac/pyinstaller"

remove_repo_child() {
  local target="$1"
  [[ -e "$target" ]] || return 0
  local resolved
  resolved="$(cd "$(dirname "$target")" && pwd)/$(basename "$target")"
  case "$resolved" in
    "$REPO_ROOT"/*) rm -rf "$resolved" ;;
    *) echo "ERROR: refusing to remove path outside repo: $resolved"; exit 1 ;;
  esac
}

echo "============================================================"
echo "  ScanPrep macOS backend build"
echo "============================================================"
echo
echo "Repository:"
echo "  $REPO_ROOT"
echo

if [[ ! -x "$PYTHON_EXE" ]]; then
  echo "ERROR: build environment was not found."
  echo "Run ./mac/setup_env.sh first."
  exit 1
fi

if [[ ! -d "$MODELS_DIR" ]]; then
  echo "ERROR: _AI_Models was not found."
  echo "Download _AI_Models-vX.Y.Z.zip from GitHub Releases and extract it into the repository root."
  exit 1
fi

echo "Checking Python, PyTorch, and acceleration support..."
"$PYTHON_EXE" - <<'PY'
import sys
import torch
import torchvision
print(sys.version)
print("torch", torch.__version__)
print("torchvision", torchvision.__version__)
print("mps available", bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()))
print("cuda available", torch.cuda.is_available())
if sys.version_info[:2] != (3, 12):
    raise SystemExit("ERROR: Python 3.12 is required for the release build.")
PY

echo
echo "Checking video extractor..."
"$PYTHON_EXE" - <<'PY'
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
PY

echo
echo "Cleaning previous PyInstaller outputs..."
remove_repo_child "$REPO_ROOT/build"
remove_repo_child "$REPO_ROOT/dist"
mkdir -p "$SPEC_DIR"

echo
echo "Building backend with PyInstaller..."
"$PYTHON_EXE" -m PyInstaller \
  --name "$BACKEND_NAME" \
  --specpath "$SPEC_DIR" \
  --clean \
  --noconfirm \
  --onedir \
  --exclude-module pytest \
  --exclude-module tensorboard \
  --exclude-module IPython \
  --hidden-import kornia \
  --hidden-import einops \
  --hidden-import timm \
  --hidden-import imageio_ffmpeg \
  --copy-metadata scipy \
  --copy-metadata imageio_ffmpeg \
  --collect-all torch \
  --collect-all torchvision \
  --collect-all imageio_ffmpeg \
  --add-data "$MODELS_DIR:_AI_Models" \
  "$REPO_ROOT/scan_prep_engine.py"

echo
echo "Backend build complete:"
echo "  dist/$BACKEND_NAME/$BACKEND_NAME"
echo
echo "Next run:"
echo "  ./mac/package_app.sh"
