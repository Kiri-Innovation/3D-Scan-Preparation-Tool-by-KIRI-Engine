# 3D Scan Prep Tool

<img width="1899" height="1060" alt="image" src="https://github.com/user-attachments/assets/57c30b38-c91a-440d-89d2-14f3708012dd" />


3D Scan Prep Tool is an open-source desktop app for preparing image and video
datasets for photogrammetry and 3D scanning workflows.

It is designed for 3D scan enthusiasts who want an advanced but approachable
tool for sorting, extracting, masking, and processing scan source material before
sending it to reconstruction software.

## What It Does

- Sort image sets into scan sessions.
- Optionally preserve originals or move originals during cleanup workflows.
- Detect blurry/weak images and isolate them for review.
- Extract frames from normal videos.
- Extract perspective views from 360/equirectangular video.
- Create AI masks for subjects, skies/clouds, people/crowds, vehicles, and related distractions.
- Preview masks and processing before running a full batch.
- Apply scan-focused image processing such as contrast adjustment, local contrast boost, exposure-fusion look, and feature sharpening.
- Read RAW and HEIC inputs for preview/processing workflows.
- Use NVIDIA GPU acceleration on supported Windows systems, with CPU fallback.

## Installers

Normal users should download installers from the GitHub Releases page.

Release assets:

```text
3D Scan Prep Tool.exe
3D Scan Prep Tool-1.bin
3D Scan Prep Tool-2.bin
3D-Scan-Prep-Tool-macOS-arm64-vX.Y.Z.dmg
_AI_Models-vX.Y.Z.zip
```

The installers include the app, Electron interface, Python
backend, and AI models.

**Windows Split Installer**

The Windows CUDA installer is split into one setup `.exe` plus one or more
`.bin` data files because the full GPU-enabled build is large. Download all
Windows installer parts into the same folder, then run `3D Scan Prep Tool.exe`.


**macOS Security Warning**



## Important Safety Note

Always work from a copy or backup of your scan data.

Some workflows can move source images into sorting or review folders when the
user enables those options. This is useful for cleaning large, unorganized
datasets, but it should not be run on the only copy of an SD card dump or an
important shoot.

## Hardware Support

### Windows

The Windows GPU build uses PyTorch CUDA 12.8.

Expected behavior:

- NVIDIA RTX 20 / 30 / 40 / 50 class cards should use GPU acceleration when the driver supports it.
- Older NVIDIA GTX 10-series / Pascal cards should fall back to CPU.
- AMD GPUs, Intel GPUs, unsupported NVIDIA GPUs, and systems without a GPU should fall back to CPU.
- CPU fallback is slower, especially for AI masking, but should keep the app usable.

### macOS

A fully working Mac build and installers is not yet available.
Some in-progress scripts for mac exist but likely have bugs, or UI scaling errors.
We may continue working on a fully installer and tested mac build in the future when avilable.


## Building From Source

Public build notes live in:

```text
windows/
mac/
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

See `MODEL_LICENSES.md` before redistributing model files.

## License

This project is released under the GNU Affero General Public License v3.0.

See `license.txt`, `MODEL_LICENSES.md`, and `THIRD_PARTY_NOTICES.md`.
