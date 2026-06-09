#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="3D Scan Prep Tool"
APP_DIR="$REPO_ROOT/dist/$APP_NAME.app"
OUTPUT_DIR="$REPO_ROOT/Packaged"
ARCH="$(uname -m)"
DMG_PATH="$OUTPUT_DIR/3D-Scan-Prep-Tool-macOS-$ARCH.dmg"

echo "============================================================"
echo "  ScanPrep macOS DMG build"
echo "============================================================"
echo
echo "Repository:"
echo "  $REPO_ROOT"
echo

if [[ ! -d "$APP_DIR" ]]; then
  echo "ERROR: macOS app bundle was not found."
  echo "Run ./mac/package_app.sh first."
  exit 1
fi

if ! command -v hdiutil >/dev/null 2>&1; then
  echo "ERROR: hdiutil was not found. This script must run on macOS."
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
rm -f "$DMG_PATH"

echo "Creating DMG:"
echo "  $DMG_PATH"
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$APP_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo
echo "DMG build complete:"
echo "  $DMG_PATH"

