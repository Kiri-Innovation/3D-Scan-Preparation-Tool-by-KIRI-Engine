# Inno Setup

This folder holds the public Windows installer recipe.

Build the installer from the repository root with:

```powershell
.\windows\build_inno_installer.ps1
```

The generated installer is written to the repository `Packaged` folder.

The full CUDA-enabled Windows build is large, so the installer is intentionally
split into one setup `.exe` plus one or more `.bin` data files.
