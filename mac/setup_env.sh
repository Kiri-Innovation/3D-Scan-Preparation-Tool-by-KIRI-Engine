#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="${SCANPREP_VENV:-$REPO_ROOT/.venv-scanprep-macos}"
PIP_CACHE_DIR="$REPO_ROOT/.pip-cache"

find_python() {
  if command -v python3.12 >/dev/null 2>&1; then
    command -v python3.12
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: Python was not found."
  echo "Install Python 3.12, then run this script again."
  exit 1
fi

echo "============================================================"
echo "  ScanPrep macOS build environment setup"
echo "============================================================"
echo
echo "Repository:"
echo "  $REPO_ROOT"
echo
echo "Python:"
echo "  $PYTHON_BIN"
echo

"$PYTHON_BIN" - <<'PY'
import sys
print(sys.version)
if sys.version_info[:2] != (3, 12):
    raise SystemExit("ERROR: Python 3.12 is required for the release build.")
PY

if [[ ! -d "$VENV_DIR" ]]; then
  echo
  echo "Creating virtual environment:"
  echo "  $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "ERROR: The virtual environment is incomplete:"
  echo "  $VENV_PY"
  exit 1
fi

unset PIP_NO_INDEX PIP_INDEX_URL PIP_EXTRA_INDEX_URL HTTP_PROXY HTTPS_PROXY ALL_PROXY

echo
echo "Upgrading pip tooling..."
"$VENV_PY" -m ensurepip --upgrade --default-pip
"$VENV_PY" -m pip install --cache-dir "$PIP_CACHE_DIR" --retries 20 --timeout 120 --upgrade pip setuptools wheel

echo
echo "Installing macOS PyTorch packages..."
"$VENV_PY" -m pip install --cache-dir "$PIP_CACHE_DIR" --retries 20 --timeout 120 -r "$REPO_ROOT/mac/requirements-torch-macos.txt"

echo
echo "Installing ScanPrep Python dependencies..."
"$VENV_PY" -m pip install --cache-dir "$PIP_CACHE_DIR" --retries 20 --timeout 120 pyinstaller -r "$REPO_ROOT/requirements.txt"

echo
echo "Checking Python packages..."
"$VENV_PY" -m pip check

if ! command -v npm >/dev/null 2>&1; then
  echo
  echo "ERROR: npm was not found."
  echo "Install Node.js, then run this script again."
  exit 1
fi

echo
echo "Installing Electron dependencies..."
(
  cd "$REPO_ROOT/electron-ui"
  npm install
)

if [[ ! -d "$REPO_ROOT/_AI_Models" ]]; then
  echo
  echo "NOTE: _AI_Models was not found."
  echo "Download _AI_Models-vX.Y.Z.zip from GitHub Releases and extract it into the repository root before building."
fi

echo
echo "macOS build environment is ready."
echo "Next run:"
echo "  ./mac/build_backend.sh"

