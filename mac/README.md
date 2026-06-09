# macOS Build Notes

This folder is for public macOS build instructions and scripts.

The macOS app must be built on a real Mac. A Windows machine cannot create the
final macOS app bundle or installer.

Public build scripts should use paths relative to the repository folder, not
paths from one developer's local machine. This lets other Mac builders place the
project wherever they want.

## Prerequisites

- A real Mac.
- Python 3.12.
- Node.js and npm.
- `_AI_Models` extracted into the repository root.

If the shell scripts are not executable after downloading the source, run:

```bash
chmod +x mac/*.sh
```

## Script Summary

- `setup_env.sh` creates the Python virtual environment and installs Python/Electron dependencies.
- `create_icns.sh` creates the macOS `.icns` app icon from a PNG logo.
- `build_backend.sh` builds the Python backend with PyInstaller.
- `package_app.sh` packages the Electron interface and backend into a `.app` bundle.
- `build_dmg.sh` creates a `.dmg` release file from the `.app` bundle.
- `verify_macos_build.sh` checks that the packaged app has the expected files and that the backend can run.
- `BUILD_STEPS.txt` is a short plain-text checklist.

## Intended Mac Build Flow

Open Terminal in the repository root and run:

```bash
./mac/setup_env.sh
./mac/create_icns.sh
./mac/build_backend.sh
./mac/package_app.sh
./mac/build_dmg.sh
./mac/verify_macos_build.sh
```

Outputs:

```text
dist/ScanPrep Tool Backend/ScanPrep Tool Backend
dist/3D Scan Prep Tool.app
Packaged/3D-Scan-Prep-Tool-macOS-<architecture>.dmg
```

## AI Models

The `_AI_Models` folder is not stored directly in git because it is large.

For source builds, download `_AI_Models-vX.Y.Z.zip` from GitHub Releases and
extract it into the repository root so the folder looks like this:

```text
_AI_Models/BiRefNet
_AI_Models/MaskFormer
_AI_Models/YOLO
```

## Hardware Notes

Expected macOS behavior:

- Apple Silicon Macs may use PyTorch MPS acceleration when supported.
- Intel Macs should use CPU fallback.
- Modern macOS does not use NVIDIA CUDA for this app.

macOS release builds are produced and tested on real Mac hardware before they
are uploaded.

The app has been tested on a limited number of systems. It has not undergone
extensive testing on every Mac model, macOS version, GPU/backend, CPU, or
folder/path combination, so bugs may appear as more users try it.

Unsigned macOS apps may show an Apple security warning. Users may need to
right-click the app and choose Open unless the app is code signed and notarized
with an Apple Developer account.
