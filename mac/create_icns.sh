#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_PNG="${1:-$REPO_ROOT/Images and Icons/KIRI Tools logo.png}"
OUTPUT_ICNS="${2:-$REPO_ROOT/Images and Icons/KIRI Tools.icns}"
ICONSET_DIR="$REPO_ROOT/.tmp/KIRI Tools.iconset"

echo "============================================================"
echo "  ScanPrep macOS icon creation"
echo "============================================================"
echo

if [[ ! -f "$SOURCE_PNG" ]]; then
  echo "ERROR: source PNG was not found:"
  echo "  $SOURCE_PNG"
  exit 1
fi

if ! command -v sips >/dev/null 2>&1 || ! command -v iconutil >/dev/null 2>&1; then
  echo "ERROR: sips/iconutil were not found. This script must run on macOS."
  exit 1
fi

echo "Source PNG:"
echo "  $SOURCE_PNG"
echo "Output ICNS:"
echo "  $OUTPUT_ICNS"
echo
echo "Best results come from a square transparent PNG, ideally 1024x1024."

rm -rf "$ICONSET_DIR"
mkdir -p "$ICONSET_DIR"

sips -z 16 16     "$SOURCE_PNG" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
sips -z 32 32     "$SOURCE_PNG" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
sips -z 32 32     "$SOURCE_PNG" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
sips -z 64 64     "$SOURCE_PNG" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
sips -z 128 128   "$SOURCE_PNG" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
sips -z 256 256   "$SOURCE_PNG" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
sips -z 256 256   "$SOURCE_PNG" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
sips -z 512 512   "$SOURCE_PNG" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
sips -z 512 512   "$SOURCE_PNG" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$SOURCE_PNG" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null

iconutil -c icns "$ICONSET_DIR" -o "$OUTPUT_ICNS"

echo
echo "Mac icon created:"
echo "  $OUTPUT_ICNS"

