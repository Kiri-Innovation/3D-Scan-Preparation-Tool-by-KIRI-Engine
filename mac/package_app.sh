#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="3D Scan Prep Tool"
BUNDLE_ID="app.kiriengine.scanprep"
BACKEND_NAME="ScanPrep Tool Backend"
ELECTRON_APP="$REPO_ROOT/electron-ui/node_modules/electron/dist/Electron.app"
BACKEND_DIR="$REPO_ROOT/dist/$BACKEND_NAME"
APP_DIR="$REPO_ROOT/dist/$APP_NAME.app"
TEMP_APP="$REPO_ROOT/dist/_electron_package_tmp.app"
ICON_ICNS="$REPO_ROOT/Images and Icons/KIRI Tools.icns"

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

plist_set_or_add() {
  local plist="$1"
  local key="$2"
  local type="$3"
  local value="$4"
  /usr/libexec/PlistBuddy -c "Set :$key $value" "$plist" 2>/dev/null || \
    /usr/libexec/PlistBuddy -c "Add :$key $type $value" "$plist"
}

echo "============================================================"
echo "  ScanPrep macOS Electron app package"
echo "============================================================"
echo
echo "Repository:"
echo "  $REPO_ROOT"
echo

if [[ ! -d "$ELECTRON_APP" ]]; then
  echo "ERROR: Electron runtime was not found."
  echo "Run ./mac/setup_env.sh first."
  exit 1
fi

if [[ ! -x "$BACKEND_DIR/$BACKEND_NAME" ]]; then
  echo "ERROR: backend build was not found."
  echo "Run ./mac/build_backend.sh first."
  exit 1
fi

echo "Preparing app bundle..."
remove_repo_child "$TEMP_APP"
remove_repo_child "$APP_DIR"
mkdir -p "$REPO_ROOT/dist"
cp -R "$ELECTRON_APP" "$TEMP_APP"

echo "Copying Electron UI..."
rm -f "$TEMP_APP/Contents/Resources/default_app.asar"
mkdir -p "$TEMP_APP/Contents/Resources/app"
cp "$REPO_ROOT/electron-ui/main.js" "$TEMP_APP/Contents/Resources/app/main.js"
cp "$REPO_ROOT/electron-ui/preload.js" "$TEMP_APP/Contents/Resources/app/preload.js"
cp "$REPO_ROOT/electron-ui/package.json" "$TEMP_APP/Contents/Resources/app/package.json"
cp -R "$REPO_ROOT/electron-ui/renderer" "$TEMP_APP/Contents/Resources/app/renderer"

echo "Copying brand assets..."
cp -R "$REPO_ROOT/Images and Icons" "$TEMP_APP/Contents/Resources/Images and Icons"
if [[ -f "$ICON_ICNS" ]]; then
  cp "$ICON_ICNS" "$TEMP_APP/Contents/Resources/KIRI Tools.icns"
else
  echo "NOTE: KIRI Tools.icns was not found. Run ./mac/create_icns.sh to create the Mac icon."
fi

echo "Copying backend tool..."
mkdir -p "$TEMP_APP/Contents/Resources/backend"
cp -R "$BACKEND_DIR/." "$TEMP_APP/Contents/Resources/backend/"

echo "Renaming Electron executable..."
if [[ -x "$TEMP_APP/Contents/MacOS/Electron" ]]; then
  mv "$TEMP_APP/Contents/MacOS/Electron" "$TEMP_APP/Contents/MacOS/$APP_NAME"
fi
chmod +x "$TEMP_APP/Contents/MacOS/$APP_NAME"

echo "Updating app metadata..."
PLIST="$TEMP_APP/Contents/Info.plist"
plist_set_or_add "$PLIST" "CFBundleName" "string" "$APP_NAME"
plist_set_or_add "$PLIST" "CFBundleDisplayName" "string" "$APP_NAME"
plist_set_or_add "$PLIST" "CFBundleExecutable" "string" "$APP_NAME"
plist_set_or_add "$PLIST" "CFBundleIdentifier" "string" "$BUNDLE_ID"
plist_set_or_add "$PLIST" "CFBundlePackageType" "string" "APPL"
if [[ -f "$ICON_ICNS" ]]; then
  plist_set_or_add "$PLIST" "CFBundleIconFile" "string" "KIRI Tools"
fi

echo "Moving final app bundle into dist..."
mv "$TEMP_APP" "$APP_DIR"

echo
echo "macOS app bundle complete:"
echo "  dist/$APP_NAME.app"
echo
echo "Open it to test the app, then run:"
echo "  ./mac/build_dmg.sh"

