# Windows Build Notes

This folder is for public Windows build instructions and files.

Normal users should download the Windows installer from GitHub Releases.
These notes are for developers who want to build the app themselves.

## Current Release Build Shape

The Windows app is built in three parts:

1. Build the Python backend with PyInstaller.
2. Package the Electron interface around that backend.
3. Build the Windows installer with Inno Setup.

## Prerequisites

- Windows 10/11, 64-bit.
- Python 3.12 installed with the Python Launcher (`py`).
- Node.js and npm installed.
- Inno Setup 6 installed if you want to build the installer wizard.
- `_AI_Models` extracted into the repository root.

## Build Commands

Open PowerShell in the repository root.

If PowerShell blocks scripts on your machine, allow scripts for this one
terminal session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then run:

```powershell
.\windows\build_backend.ps1
.\windows\package_app.ps1
.\windows\build_inno_installer.ps1
```

Outputs:

```text
dist\ScanPrep Tool Backend\ScanPrep Tool Backend.exe
dist\3D Scan Prep Tool\3D Scan Prep Tool.exe
Packaged\3D Scan Prep Tool.exe
Packaged\3D Scan Prep Tool-*.bin
```

The full Windows CUDA build is large, so the Inno installer is split into
multiple release files:

```text
3D Scan Prep Tool.exe
3D Scan Prep Tool-1.bin
3D Scan Prep Tool-2.bin
...
```

Upload all Windows installer parts to the GitHub Release. Users should download
every Windows installer part into the same folder, then run
`3D Scan Prep Tool.exe`.

## Hardware Notes

The Windows GPU build uses PyTorch CUDA 12.8.

Expected GPU behavior:

- NVIDIA RTX 20 / 30 / 40 / 50 class cards should use GPU acceleration when the driver supports it.
- Unsupported NVIDIA cards, AMD GPUs, Intel GPUs, and systems without a GPU should fall back to CPU.
- CPU fallback is slower but should keep the app usable.

The app has been tested on a limited number of Windows systems. It has not
undergone extensive testing on every Windows version, GPU, driver, CPU, or
folder/path combination. More user testing may reveal bugs on specific machines,
drivers, or unusual paths.
