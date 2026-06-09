#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="3D Scan Prep Tool"
BACKEND_NAME="ScanPrep Tool Backend"
APP_DIR="$REPO_ROOT/dist/$APP_NAME.app"
BACKEND_EXE="$APP_DIR/Contents/Resources/backend/$BACKEND_NAME"

echo "============================================================"
echo "  ScanPrep macOS build verification"
echo "============================================================"
echo
echo "Repository:"
echo "  $REPO_ROOT"
echo

fail() {
  echo "ERROR: $1"
  exit 1
}

[[ -d "$APP_DIR" ]] || fail "App bundle was not found: $APP_DIR"
[[ -x "$APP_DIR/Contents/MacOS/$APP_NAME" ]] || fail "App executable was not found inside the bundle."
[[ -f "$APP_DIR/Contents/Resources/app/main.js" ]] || fail "Electron main.js was not packaged."
[[ -f "$APP_DIR/Contents/Resources/app/renderer/index.html" ]] || fail "Electron renderer files were not packaged."
[[ -x "$BACKEND_EXE" ]] || fail "Backend executable was not packaged: $BACKEND_EXE"

if [[ -d "$APP_DIR/Contents/Resources/backend/_internal/_AI_Models" ]]; then
  echo "AI models found in backend _internal folder."
elif [[ -d "$APP_DIR/Contents/Resources/backend/_AI_Models" ]]; then
  echo "AI models found in backend folder."
else
  fail "AI models were not found inside the packaged backend."
fi

echo
echo "Running backend acceleration check..."
"$BACKEND_EXE" --gpu-test-json

echo
echo "Basic packaged-app checks passed."
echo
echo "Final manual check:"
echo "  Open dist/$APP_NAME.app and test a small image folder before uploading a macOS release."

