# Third-Party Notices

3D Scan Prep Tool uses open-source libraries, tools, and model ecosystems.
This file summarizes the major third-party components that builders and
redistributors should be aware of.

This notice is not a complete legal review. Before public release, verify exact
dependency versions and licenses from the installed packages and upstream
projects.

## Major Runtime Components

- Electron - desktop app shell.
- Node.js packages used by Electron tooling.
- Python - backend runtime.
- PyInstaller - Python application bundling.
- Inno Setup - Windows installer creation.
- FFmpeg / imageio-ffmpeg - video frame extraction.
- PyTorch and torchvision - AI runtime.
- OpenCV - image and video processing.
- NumPy and SciPy - numeric processing.
- Pillow and pillow-heif - image loading and HEIC support.
- rawpy / LibRaw - RAW image loading.
- PySceneDetect - video scene detection.
- Ultralytics YOLO - object/segmentation masking.
- Hugging Face Transformers and safetensors - model loading.
- timm, einops, and kornia - AI model support libraries.

## Installer Notes

Windows installer builds may include:

- Electron runtime files.
- PyInstaller backend files.
- PyTorch CUDA runtime files.
- FFmpeg binary from imageio-ffmpeg.
- AI model weights from `_AI_Models`.

macOS builds may include equivalent platform-specific Electron, PyInstaller,
PyTorch, FFmpeg, and model files.

## Model Notices

See `MODEL_LICENSES.md` for model-specific notes.

## Source Availability

This project is released under AGPL-3.0. If you redistribute modified versions,
make sure you follow the source availability requirements of AGPL-3.0 and any
additional requirements from third-party components.

