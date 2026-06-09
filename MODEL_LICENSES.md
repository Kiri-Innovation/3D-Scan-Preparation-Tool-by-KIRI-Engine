# Model Licenses

This project uses AI model weights for masking and segmentation features.

The `_AI_Models` folder is not committed to git because it is large. Release
builds may include the models, and source builders may download a model archive
from GitHub Releases.

## Included Model Folders

Expected model layout:

```text
_AI_Models/BiRefNet
_AI_Models/MaskFormer
_AI_Models/YOLO
```

## YOLO

The YOLO segmentation model is provided through the Ultralytics ecosystem.
Ultralytics YOLO is licensed under AGPL-3.0 for open-source use unless a separate
commercial license is obtained from Ultralytics.

Because this project uses AGPL-licensed YOLO components, this project is also
released as AGPL-3.0.

## BiRefNet

BiRefNet model files are used for subject/background masking.

Before redistributing BiRefNet weights in a release asset or installer, verify
the exact upstream model source and license terms for the model checkpoint being
included.

## MaskFormer

MaskFormer model files are used for sky/cloud masking.

Before redistributing MaskFormer weights in a release asset or installer, verify
the exact upstream model source and license terms for the model checkpoint being
included.

## Release Asset Guidance

Do not commit `_AI_Models` directly to git.

Recommended release asset name:

```text
_AI_Models-vX.Y.Z.zip
```

Source builders should download that zip from GitHub Releases and extract it
into the repository root.

This file is a project notice, not legal advice.

