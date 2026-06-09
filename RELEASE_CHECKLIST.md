# Release Checklist

Use this checklist before uploading a new public release.

## Source Upload Check

- Confirm private/local folders are not committed:
  - `_AI_Models/`
  - `.venv*/`
  - `electron-ui/node_modules/`
  - `electron-ui/.npm-cache/`
  - `build/`
  - `dist/`
  - `Packaged/`
  - `Test Folder/`
  - `dev_tools/`
  - `tests/`
  - `packaging/`
- Confirm public scripts do not contain personal computer paths.
- Confirm `README.md`, `MODEL_LICENSES.md`, and `THIRD_PARTY_NOTICES.md` are up to date.
- Confirm the app version/release notes describe any major changes.

## AI Models

The `_AI_Models/` folder is required to build and run the app, but it should not be committed to GitHub because it is large.

For a public release:

1. Zip the `_AI_Models/` folder.
2. Upload the zip as a GitHub Release asset.
3. Tell source-build users to unzip it into the repo root so the folder path is:

```text
_AI_Models/
```

Keep model license notes in `MODEL_LICENSES.md`.

## Windows Build

Run these from the repo root on Windows:

```powershell
.\windows\build_backend.ps1
.\windows\package_app.ps1
```

Then test:

```text
dist\3D Scan Prep Tool\3D Scan Prep Tool.exe
```

If the app works, build the installer:

```powershell
.\windows\build_inno_installer.ps1
```

Then test the installer from:

```text
Packaged\
```

The Windows CUDA installer is split into multiple files so each GitHub Release
asset stays under the upload limit. Upload every file produced in `Packaged\`
for the Windows installer:

```text
3D Scan Prep Tool.exe
3D Scan Prep Tool-1.bin
3D Scan Prep Tool-2.bin
...
```

Users must download all Windows installer parts into the same folder, then run
`3D Scan Prep Tool.exe`.

## macOS Build

Run these from the repo root on a Mac:

```bash
chmod +x mac/*.sh
./mac/setup_env.sh
./mac/create_icns.sh
./mac/build_backend.sh
./mac/package_app.sh
./mac/verify_macos_build.sh
./mac/build_dmg.sh
```

Then test:

```text
dist/3D Scan Prep Tool.app
```

And test the generated DMG from:

```text
Packaged/
```

## Basic Manual Tests

Before marking a release ready, test at least:

- Open the app.
- Pick an image folder.
- Preview an image.
- Preview masks.
- Run a small image set.
- Run a small video extraction.
- Run a 360 video extraction if possible.
- Confirm CPU fallback is available if GPU acceleration is not usable.
- Confirm output folders are created correctly.
- Confirm the app can be stopped during a long run.

## Release Assets

Recommended GitHub Release assets:

- Windows installer `.exe` plus all matching `.bin` parts
- macOS `.dmg`
- `_AI_Models` zip

Optional but useful:

- Checksums for each release asset.
- A short text note listing tested operating systems and hardware.

## Public Notes

Mention these points clearly on the GitHub release page:

- The app has not been tested on every operating system, GPU, CPU, camera format, or hardware setup.
- NVIDIA RTX 20/30/40/50 class GPUs should be the best-supported CUDA path on Windows when using the CUDA 12.8 build.
- Older NVIDIA GPUs, AMD GPUs, Intel GPUs, and unsupported CUDA setups should fall back to CPU.
- CPU fallback is slower but should keep the app usable.
- macOS uses CPU and Apple Silicon acceleration paths where available; NVIDIA CUDA is not used on macOS.
- Users should keep backups of important source images before running batch tools.
- Windows and macOS may warn about unsigned apps unless code signing is added later.
