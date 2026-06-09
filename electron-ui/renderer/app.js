const inputPath = document.querySelector("#inputPath");
const outputPath = document.querySelector("#outputPath");
const previewPanel = document.querySelector(".preview-panel");
const previewFrame = document.querySelector("#previewFrame");
const logLines = document.querySelector("#logLines");
const hoverHelp = document.querySelector("#hoverHelp");
const runButton = document.querySelector("#runButton");
const runStatus = document.querySelector("#runStatus");
const runProgress = document.querySelector("#runProgress");
const zoomFitButton = document.querySelector("#zoomFitButton");
const zoomOutButton = document.querySelector("#zoomOutButton");
const zoomInButton = document.querySelector("#zoomInButton");
const zoomReadout = document.querySelector("#zoomReadout");
const inputModeButtons = document.querySelectorAll("[data-input-mode]");
const sortSessionsToggle = document.querySelector("#sortSessionsToggle");
const sortSettings = document.querySelector("#sortSettings");
const mask360BottomOption = document.querySelector("#mask360BottomOption");
const videoSettings = document.querySelector("#videoSettings");
const videoFrameMode = document.querySelector("#videoFrameMode");
const videoFrameTarget = document.querySelector("#videoFrameTarget");
const videoFrameLabel = document.querySelector("#videoFrameLabel");
const videoFrameHint = document.querySelector("#videoFrameHint");
const videoExtractMethodBlock = document.querySelector("#videoExtractMethodBlock");
const videoExtractMethod = document.querySelector("#videoExtractMethod");
const previewVideoPositionBlock = document.querySelector("#previewVideoPositionBlock");
const videoPreviewPosition = document.querySelector("#videoPreviewPosition");
const sceneSplitBlock = document.querySelector("#sceneSplitBlock");
const sceneSplitToggle = document.querySelector("#sceneSplitToggle");
const sceneSplitSettings = document.querySelector("#sceneSplitSettings");
const sceneSplitHint = document.querySelector("#sceneSplitHint");
const settings360 = document.querySelector("#settings360");
const include360BottomViews = document.querySelector("#include360BottomViews");
const view360Mode = document.querySelector("#view360Mode");
const views360Hint = document.querySelector("#views360Hint");
const imageOnlySourceControls = [
  document.querySelector("#subfolderModeLabel"),
  document.querySelector("#subfolderMode"),
  document.querySelector("#fileTypeGrid"),
  document.querySelector("#preserveOriginalsOption"),
  document.querySelector("#sortSessionsOption")
];
const folderDepthControls = [
  document.querySelector("#folderDepthLabel"),
  document.querySelector("#folderSearchDepth")
];
const adjustContrastToggle = document.querySelector("#adjustContrastToggle");
const contrastControls = document.querySelector("#contrastControls");
const featureSharpening = document.querySelector("#featureSharpening");
const sharpenControls = document.querySelector("#sharpenControls");
const sharpnessMode = document.querySelector("#sharpnessMode");
const sharpnessPreviewResult = document.querySelector("#sharpnessPreviewResult");
const previewMaskButton = document.querySelector("#previewMaskButton");
const previewContrastButton = document.querySelector("#previewContrastButton");
const blurSensitivityBlock = document.querySelector("#blurSensitivityBlock");
const sharpestCountBlock = document.querySelector("#sharpestCountBlock");
const clusterSizeBlock = document.querySelector("#clusterSizeBlock");
const processedOutputControls = document.querySelector("#processedOutputControls");
const processedFormatLabel = document.querySelector("#processedFormatLabel");
const jpgQualityRow = document.querySelector("#jpgQualityRow");
const noProcessedOutputNote = document.querySelector("#noProcessedOutputNote");
const diagnosticsOverlay = document.querySelector("#diagnosticsOverlay");
const diagnosticsCards = document.querySelector("#diagnosticsCards");
const diagnosticsLogText = document.querySelector("#diagnosticsLogText");
const diagnosticsLogPath = document.querySelector("#diagnosticsLogPath");
const refreshDiagnosticsButton = document.querySelector("#refreshDiagnosticsButton");
const closeDiagnosticsButton = document.querySelector("#closeDiagnosticsButton");
const openOutputFolderButton = document.querySelector("#openOutputFolderButton");
const openDebugLogButton = document.querySelector("#openDebugLogButton");
const openEngineLogButton = document.querySelector("#openEngineLogButton");
const workerMode = document.querySelector("#workerMode");
const workersSummary = document.querySelector("#workersSummary");

let currentInputMode = "images";
let isBackendRunning = false;
let sawDoneEvent = false;
let selectedPreviewImage = "";
let selectedPreviewDisplayImage = "";
let lastDiagnostics = null;
let lastDebugLogPath = "";
let previewZoom = 1;
let previewPanX = 0;
let previewPanY = 0;
let isPreviewPanning = false;
let previewPanStart = { x: 0, y: 0, panX: 0, panY: 0 };
const runtimeLogHistory = [];
const defaultHelpText = "Hover over a setting to see what it does.";

const bridge = window.scanprep || {
  chooseFolder: async () => null,
  chooseFile: async () => null,
  chooseFiles: async () => [],
  defaultOutputFor: async (input) => `${input}\\_ScanPrep_Output`,
  getDiagnostics: async () => ({ diagnostics: {}, logs: {} }),
  testGpu: async () => ({ code: 0 }),
  runConfig: async () => ({ code: 0 }),
  prepareDisplayPreview: async () => ({ code: 0 }),
  prepareSourcePreview: async () => ({ code: 0 }),
  previewSharpness: async () => ({ code: 0 }),
  previewMask: async () => ({ code: 0 }),
  previewContrast: async () => ({ code: 0 }),
  cancelBackend: async () => ({ cancelled: false }),
  openPath: async () => ({ opened: false }),
  onBackendEvent: () => () => {}
};

function log(message, kind = "") {
  const p = document.createElement("p");
  p.textContent = message;
  if (kind) p.classList.add(`is-${kind}`);
  logLines.append(p);
  logLines.scrollTop = logLines.scrollHeight;
  runtimeLogHistory.push(message);
  if (runtimeLogHistory.length > 600) runtimeLogHistory.shift();
  updateDiagnosticsLogText();
}

function setProgress(percent) {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(percent) ? percent : 0));
  runProgress.style.width = `${clamped}%`;
}

function setUiLocked(locked) {
  document.querySelectorAll("button, input, select").forEach((control) => {
    if (control === runButton) return;
    control.disabled = locked;
  });
  if (!locked) updatePreviewButtonStates();
}

function setBackendRunning(running, label = running ? "Running..." : "Ready") {
  isBackendRunning = running;
  setUiLocked(running);
  runButton.textContent = running ? "Stop" : "Run";
  runButton.classList.toggle("stop-button", running);
  runStatus.textContent = label;
  if (running) setProgress(0);
}

bridge.onBackendEvent((event) => {
  if (!event) return;
  if (event.type === "progress") {
    const total = Math.max(1, Number(event.total || 1));
    const current = Math.max(0, Number(event.current || 0));
    const pct = (current / total) * 100;
    setProgress(pct);
    runStatus.textContent = event.message || "Working...";
    log(`${event.message} ${current}/${total}`);
  } else if (event.type === "status") {
    if (isBackendRunning) runStatus.textContent = event.message || "Working...";
    log(event.message || "Status update.");
  } else if (event.type === "done") {
    sawDoneEvent = true;
    setProgress(100);
    runStatus.textContent = "Complete";
    log(event.message || "Complete.", "done");
  } else if (event.type === "sharpness_preview") {
    const summary = `${event.preserved || 0} preserved, ${event.isolated || 0} isolated`;
    sharpnessPreviewResult.textContent = event.note ? `${summary}. ${event.note}` : summary;
    log(`Sharpness preview ready: ${summary}`, "done");
    if (event.note) log(event.note);
    if (event.preview_dir) bridge.openPath(event.preview_dir);
  } else if (event.type === "open_path" && event.path) {
    bridge.openPath(event.path);
  } else if (event.type === "image_preview") {
    selectedPreviewImage = event.original || selectedPreviewImage;
    selectedPreviewDisplayImage = event.display || event.original || "";
    renderSinglePreview(selectedPreviewDisplayImage);
    log(event.converted ? "Preview display JPG created." : "Preview image loaded.", "done");
  } else if (event.type === "mask_preview") {
    const masks = Array.isArray(event.masks) && event.masks.length
      ? event.masks
      : [{ label: "Mask", path: event.mask }];
    renderMaskPreviewSet(event.original, masks);
    log(`Mask preview ready: ${masks.length} view${masks.length === 1 ? "" : "s"}.`, "done");
  } else if (event.type === "contrast_preview") {
    const previousPreviewImage = selectedPreviewImage;
    const previousPreviewDisplayImage = selectedPreviewDisplayImage;
    selectedPreviewImage = event.original || selectedPreviewImage;
    if (event.display) {
      selectedPreviewDisplayImage = event.display;
    } else if (event.original && samePath(event.original, previousPreviewImage)) {
      selectedPreviewDisplayImage = previousPreviewDisplayImage;
    }
    const label = event.label || "Processing Preview";
    renderPreviewComparison(event.original || selectedPreviewImage, event.processed, label);
    log(label.toLowerCase().includes("preview") ? `${label} ready.` : `${label} preview ready.`, "done");
  } else if (event.type === "preview") {
    renderPreviewComparison(event.original, event.processed, "Preview");
  } else if (event.type === "error") {
    runStatus.textContent = "Needs attention";
    log(event.message || "Unknown error.", "error");
  } else if (event.type === "diagnostic") {
    log(event.message);
  } else if (event.type === "exit") {
    if (event.code === 0 && sawDoneEvent) {
      log("Finished.", "done");
      runStatus.textContent = "Complete";
      setProgress(100);
    } else if (event.code === null) {
      log("Stopped.");
      runStatus.textContent = "Stopped";
      setProgress(0);
    } else {
      log(event.message || `Process exited with code ${event.code}.`, event.code === 0 ? "" : "error");
      runStatus.textContent = event.code === 0 ? "Ready" : "Needs attention";
      if (event.code !== 0) setProgress(0);
    }
    sawDoneEvent = false;
    setBackendRunning(false, runStatus.textContent);
  } else if (event.message) {
    log(event.message);
  } else {
    log(JSON.stringify(event));
  }
});

function pathToFileUrl(filePath) {
  const normalized = String(filePath || "").replace(/\\/g, "/");
  if (!normalized) return "";

  const encodeParts = (value) => value.split("/").map((part) => encodeURIComponent(part)).join("/");

  if (normalized.startsWith("//")) {
    return `file://${encodeParts(normalized.replace(/^\/+/, ""))}`;
  }

  if (/^[A-Za-z]:\//.test(normalized)) {
    const drive = normalized.slice(0, 2);
    const rest = normalized.slice(3);
    return `file:///${drive}/${encodeParts(rest)}`;
  }

  if (normalized.startsWith("/")) {
    return `file://${normalized.split("/").map((part, index) => index === 0 ? "" : encodeURIComponent(part)).join("/")}`;
  }

  return encodeParts(normalized);
}

function samePath(a, b) {
  return String(a || "").replace(/\//g, "\\").toLowerCase() === String(b || "").replace(/\//g, "\\").toLowerCase();
}

function displayPathFor(filePath) {
  if (selectedPreviewDisplayImage && samePath(filePath, selectedPreviewImage)) {
    return selectedPreviewDisplayImage;
  }
  return filePath;
}

function applyPreviewZoom() {
  const zoomables = previewFrame.querySelectorAll(".preview-zoom-image");
  const isZoomed = previewZoom > 1.001;
  previewFrame.classList.toggle("is-zoomed", isZoomed);
  previewFrame.classList.toggle("is-panning", isPreviewPanning);
  if (!isZoomed) {
    previewPanX = 0;
    previewPanY = 0;
  }
  zoomables.forEach((image) => {
    image.style.transform = `translate(${previewPanX}px, ${previewPanY}px) scale(${previewZoom})`;
  });
  if (zoomReadout) {
    zoomReadout.textContent = isZoomed ? `${Math.round(previewZoom * 100)}%` : "Fit";
  }
}

function setPreviewZoom(nextZoom, options = {}) {
  const previousZoom = previewZoom;
  previewZoom = Math.max(1, Math.min(8, Number(nextZoom) || 1));
  if (previewZoom <= 1.001 || options.resetPan) {
    previewPanX = 0;
    previewPanY = 0;
  } else if (previousZoom <= 1.001) {
    previewPanX = 0;
    previewPanY = 0;
  }
  applyPreviewZoom();
}

function resetPreviewZoom() {
  setPreviewZoom(1, { resetPan: true });
}

function zoomPreviewBy(factor) {
  setPreviewZoom(previewZoom * factor);
}

function setPreviewActualSize() {
  const image = previewFrame.querySelector(".preview-zoom-image");
  if (!image || !image.naturalWidth || !image.naturalHeight) {
    setPreviewZoom(1, { resetPan: true });
    return;
  }
  const rect = image.getBoundingClientRect();
  const scaleX = rect.width > 0 ? image.naturalWidth / rect.width : 1;
  const scaleY = rect.height > 0 ? image.naturalHeight / rect.height : 1;
  setPreviewZoom(Math.max(1, Math.min(8, Math.min(scaleX, scaleY))), { resetPan: true });
}

function checked(id) {
  return Boolean(document.querySelector(`#${id}`)?.checked);
}

function value(id, fallback = "") {
  return document.querySelector(`#${id}`)?.value ?? fallback;
}

function intValue(id, fallback) {
  const parsed = parseInt(String(value(id, fallback)).replace(/[^0-9-]/g, ""), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function floatValue(id, fallback) {
  const parsed = parseFloat(String(value(id, fallback)).replace(/[^0-9.-]/g, ""));
  return Number.isFinite(parsed) ? parsed : fallback;
}

function autoWorkerCount() {
  return Math.max(1, (navigator.hardwareConcurrency || 4) - 1);
}

function selectedWorkerCount() {
  const label = value("workerMode", "Auto");
  if (label === "Auto") return autoWorkerCount();
  return Math.max(1, intValue("workerMode", autoWorkerCount()));
}

function updateWorkersSummary() {
  if (!workersSummary) return;
  const selected = value("workerMode", "Auto");
  const count = selectedWorkerCount();
  workersSummary.textContent = selected === "Auto"
    ? `Auto: ${count} worker${count === 1 ? "" : "s"}`
    : `${count} worker${count === 1 ? "" : "s"}`;
}

function selectedInputType() {
  if (currentInputMode === "360") return "folder_360";
  if (currentInputMode === "videoFolder") return "video_folder";
  if (currentInputMode === "video") return "video_file";
  return "image_folder";
}

function selectedSubfolderMode() {
  const label = value("subfolderMode", "Include all subfolders");
  if (label.includes("Top")) return "top";
  if (label.includes("sessions")) return "sessions";
  return "recursive";
}

function selectedFolderSearchDepth() {
  if (currentInputMode === "images") {
    const label = value("subfolderMode", "Include all subfolders");
    if (label.includes("Top")) return "0";
    if (label.includes("direct")) return "1";
    return "Unlimited";
  }
  return value("folderSearchDepth", "Unlimited");
}

function selectedMaskExport() {
  const label = value("maskExportType", "Unified black/white JPG masks");
  if (label.includes("Separate")) return "Separate Black & White Masks";
  if (label.includes("Transparent")) return "RGBA Transparent PNGs";
  return "Unified Black & White Masks";
}

function selectedToneMethod() {
  if (checked("localContrastBoost")) return "Local Contrast Boost";
  if (checked("exposureFusionLook")) return "Exposure Fusion Look";
  return "None (Original Lighting)";
}

function processingCreatesImageCopies() {
  return (
    selectedToneMethod() !== "None (Original Lighting)" ||
    checked("adjustContrastToggle") ||
    checked("featureSharpening")
  );
}

function hasMaskPreviewOptions() {
  return (
    checked("maskPeople") ||
    checked("maskAccessories") ||
    checked("maskVehicles") ||
    checked("maskSky") ||
    checked("maskSubject") ||
    (currentInputMode === "360" && checked("mask360Bottom"))
  );
}

function setPreviewButtonState(button, enabled, enabledHelp, disabledHelp) {
  if (!button) return;
  button.disabled = !enabled;
  button.dataset.help = enabled ? enabledHelp : disabledHelp;
  button.title = enabled ? "" : disabledHelp;
}

function updatePreviewButtonStates() {
  if (isBackendRunning) return;
  setPreviewButtonState(
    previewMaskButton,
    hasMaskPreviewOptions(),
    "Choose one image and preview the mask result before batch processing.",
    "Enable at least one mask type before previewing masks."
  );
  setPreviewButtonState(
    previewContrastButton,
    processingCreatesImageCopies(),
    "Previews contrast and processing settings on one image before batch processing.",
    "Enable Adjust Contrast, Local Contrast Boost, Exposure Fusion Look, or Feature Sharpening before previewing processing."
  );
}

function get360ViewCounts(modeLabel) {
  const label = String(modeLabel || "").toLowerCase();
  if (label.includes("dense") || label.includes("26")) return { withLower: 26, withoutLower: 19, lower: 7 };
  if (label.includes("balanced") || label.includes("18")) return { withLower: 18, withoutLower: 13, lower: 5 };
  if (label.includes("side") || label.includes("8")) return { withLower: 8, withoutLower: 8, lower: 0 };
  return { withLower: 14, withoutLower: 11, lower: 3 };
}

function update360ViewsHint() {
  const counts = get360ViewCounts(value("view360Mode", "Standard 14 views"));
  const includeLower = checked("include360BottomViews");
  const viewCount = includeLower ? counts.withLower : counts.withoutLower;
  if (views360Hint) {
    if (counts.lower === 0) {
      views360Hint.textContent = `${viewCount} side views per frame. No lower views in this preset.`;
    } else if (includeLower) {
      views360Hint.textContent = `${viewCount} views per frame, including ${counts.lower} lower view${counts.lower === 1 ? "" : "s"}.`;
    } else {
      views360Hint.textContent = `${viewCount} views per frame. Lower views skipped.`;
    }
  }
  update360MaskUi();
}

function updateVideoFrameText() {
  const frameValue = intValue("videoFrameTarget", 300);
  const isEveryNth = value("videoFrameMode", "Target frame count").includes("Every");
  const sceneSplit = checked("sceneSplitToggle") && (currentInputMode === "video" || currentInputMode === "videoFolder");
  videoExtractMethodBlock?.classList.toggle("hidden", isEveryNth);
  if (isEveryNth) {
    if (videoFrameLabel) videoFrameLabel.textContent = "Frame interval";
    if (videoFrameTarget) videoFrameTarget.dataset.help = "Frame interval. 10 means keep one frame, then skip the next 9 source frames.";
    if (videoFrameHint) {
      if (sceneSplit) {
        videoFrameHint.textContent = `Keep one frame every ${frameValue} source frame${frameValue === 1 ? "" : "s"} inside each detected scene.`;
      } else if (currentInputMode === "videoFolder") {
        videoFrameHint.textContent = `Keep one frame every ${frameValue} source frame${frameValue === 1 ? "" : "s"} from each video in the folder.`;
      } else if (currentInputMode === "360") {
        videoFrameHint.textContent = `Keep one 360 frame every ${frameValue} source frame${frameValue === 1 ? "" : "s"} before view extraction.`;
      } else {
        videoFrameHint.textContent = `Keep one frame every ${frameValue} source frame${frameValue === 1 ? "" : "s"} from the selected video.`;
      }
    }
  } else if (currentInputMode === "videoFolder") {
    if (videoFrameLabel) videoFrameLabel.textContent = "Target frames per video";
    if (videoFrameTarget) videoFrameTarget.dataset.help = "How many total frames to extract from each selected video before processing.";
    if (videoFrameHint) {
      videoFrameHint.textContent = sceneSplit
        ? `${frameValue} frame${frameValue === 1 ? "" : "s"} from each video, distributed across detected scenes.`
        : `${frameValue} frame${frameValue === 1 ? "" : "s"} from each video in the folder.`;
    }
  } else if (currentInputMode === "360") {
    if (videoFrameLabel) videoFrameLabel.textContent = "Target 360 frames";
    if (videoFrameTarget) videoFrameTarget.dataset.help = "How many 360 video frames to extract before ScanPrep creates perspective views.";
    if (videoFrameHint) videoFrameHint.textContent = `${frameValue} 360 frame${frameValue === 1 ? "" : "s"} before view extraction.`;
  } else {
    if (videoFrameLabel) videoFrameLabel.textContent = "Target frames";
    if (videoFrameTarget) videoFrameTarget.dataset.help = "How many total frames to extract from the selected video before processing.";
    if (videoFrameHint) {
      videoFrameHint.textContent = sceneSplit
        ? `${frameValue} frame${frameValue === 1 ? "" : "s"} distributed across detected scenes.`
        : `${frameValue} frame${frameValue === 1 ? "" : "s"} from the selected video.`;
    }
  }
}

function updateVideoPreviewPositionText(resetPreview = true) {
  if (resetPreview) {
    selectedPreviewImage = "";
    selectedPreviewDisplayImage = "";
  }
}

function updateSceneSplitUi() {
  const supportsSceneSplit = currentInputMode === "video" || currentInputMode === "videoFolder";
  sceneSplitBlock?.classList.toggle("hidden", !supportsSceneSplit);
  sceneSplitSettings?.classList.toggle("hidden", !(supportsSceneSplit && sceneSplitToggle?.checked));
  if (sceneSplitHint) {
    const seconds = Math.max(0.5, floatValue("sceneMinSeconds", 4));
    const secondsText = Number.isInteger(seconds) ? String(seconds) : seconds.toFixed(1);
    sceneSplitHint.textContent = `Minimum scene length: ${secondsText} seconds.`;
  }
  updateVideoFrameText();
}

function updateOutputVisibility() {
  const createsProcessed = processingCreatesImageCopies();
  const formatNeededForGeneratedSource = currentInputMode !== "images";
  processedOutputControls?.classList.toggle("hidden", !createsProcessed && !formatNeededForGeneratedSource);
  noProcessedOutputNote?.classList.toggle("hidden", createsProcessed);
  if (processedFormatLabel) {
    processedFormatLabel.textContent = createsProcessed ? "Processed format" : "Generated format";
  }
  jpgQualityRow?.classList.toggle("hidden", value("processedFormat", "JPG") !== "JPG");
  updatePreviewButtonStates();
}

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderDiagCard(label, value, detail = "", state = "") {
  const stateClass = state ? ` is-${state}` : "";
  return `
    <div class="diag-card${stateClass}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value || "Unknown")}</strong>
      ${detail ? `<small>${escapeHtml(detail)}</small>` : ""}
    </div>`;
}

function formatGpuSummary(torchInfo = {}) {
  if (!torchInfo.loaded) return { value: "AI libraries missing", state: "error", detail: "PyTorch/AI imports failed." };
  if (!torchInfo.cuda_available) return { value: "CPU fallback", state: "warning", detail: "CUDA GPU not available. AI masks can still run on CPU." };
  const devices = Array.isArray(torchInfo.devices) ? torchInfo.devices : [];
  const first = devices[0];
  return {
    value: first ? `${first.name}` : "CUDA available",
    detail: first ? `${first.capability}; CPU fallback remains available.` : "GPU detected; CPU fallback remains available.",
    state: ""
  };
}

function updateDiagnosticsLogText() {
  if (!diagnosticsLogText) return;
  const runtimeText = runtimeLogHistory.length
    ? runtimeLogHistory.slice(-180).join("\n")
    : "No runtime notes yet.";
  const fileText = lastDiagnostics?.logs?.debugLogText || "";
  diagnosticsLogText.textContent = fileText
    ? `--- Runtime Notes ---\n${runtimeText}\n\n--- Debug Log File ---\n${fileText}`
    : `--- Runtime Notes ---\n${runtimeText}\n\n--- Debug Log File ---\nNo debug log file found in the selected output folder yet.`;
  if (diagnosticsLogPath) {
    diagnosticsLogPath.textContent = lastDebugLogPath || "No debug log selected.";
  }
}

function renderDiagnostics(result) {
  lastDiagnostics = result || {};
  const diag = lastDiagnostics.diagnostics || {};
  const paths = diag.paths || {};
  const libraries = diag.libraries || {};
  const ai = diag.ai || {};
  const torchInfo = ai.torch || {};
  const platform = diag.platform || {};
  const python = diag.python || {};
  const appInfo = lastDiagnostics.app || {};
  const gpu = formatGpuSummary(torchInfo);
  lastDebugLogPath = lastDiagnostics.logs?.debugLogPath || paths.debug_log_path || "";

  const archList = Array.isArray(torchInfo.arch_list) && torchInfo.arch_list.length
    ? torchInfo.arch_list.join(", ")
    : "No CUDA arch list reported.";
  const modelStatus = ai.models
    ? [
        ai.models.yolo ? "YOLO OK" : "YOLO missing",
        ai.models.maskformer ? "Sky OK" : "Sky missing",
        ai.models.birefnet ? "Subject OK" : "Subject missing"
      ].join(" | ")
    : "Not checked";

  diagnosticsCards.innerHTML = [
    renderDiagCard("Acceleration", gpu.value, gpu.detail, gpu.state),
    renderDiagCard("PyTorch / CUDA", torchInfo.version || "Not loaded", `CUDA build: ${torchInfo.cuda_build || "none"} | ${archList}`, torchInfo.loaded ? "" : "error"),
    renderDiagCard("HEIC", libraries.heic_support ? "Available" : "Not available", libraries.heic_support ? "HEIC/HEIF files can be read." : "Install pillow-heif in the build env to read HEIC.", libraries.heic_support ? "" : "warning"),
    renderDiagCard("Video Extractor", libraries.ffmpeg_path ? "FFmpeg available" : "FFmpeg unavailable", libraries.ffmpeg_path || "Install imageio-ffmpeg to enable FFmpeg video extraction.", libraries.ffmpeg_path ? "" : "warning"),
    renderDiagCard("AI Models", modelStatus, "Used for people/object, sky, and subject masks.", modelStatus.includes("missing") ? "warning" : ""),
    renderDiagCard("Python", python.version || "Unknown", python.executable || appInfo.python || ""),
    renderDiagCard("System", platform.system || appInfo.platform || "Unknown", `${platform.release || ""} ${platform.machine || ""}`.trim()),
    renderDiagCard("Output", paths.output_dir || "Not selected", lastDiagnostics.logs?.debugLogExists ? "Debug log found." : "No debug log found yet.", lastDiagnostics.logs?.debugLogExists ? "" : "warning")
  ].join("");

  updateDiagnosticsLogText();
}

async function refreshDiagnostics() {
  if (!diagnosticsCards) return;
  diagnosticsCards.innerHTML = renderDiagCard("Status", "Checking...", "Reading Python, CUDA, HEIC, video, and log status.");
  const result = await bridge.getDiagnostics({
    input_path: inputPath.value,
    output_dir: outputPath.value,
    input_type: selectedInputType()
  });
  renderDiagnostics(result);
  log("Diagnostics refreshed.", result?.ok === false ? "error" : "");
}

async function openDiagnosticsPanel() {
  diagnosticsOverlay?.classList.remove("hidden");
  updateDiagnosticsLogText();
  await refreshDiagnostics();
}

function closeDiagnosticsPanel() {
  diagnosticsOverlay?.classList.add("hidden");
}

function collectRunConfig() {
  const inputType = selectedInputType();
  return {
    mode: "full",
    input_type: inputType,
    input_path: inputPath.value,
    output_dir: outputPath.value,
    do_sort: checked("sortSessionsToggle"),
    do_blur: checked("sharpnessToggle"),
    blur_mode: value("sharpnessMode", "Isolate Blurry Images"),
    tone_method: selectedToneMethod(),
    smart_bypass: false,
    out_fmt: value("processedFormat", "JPG"),
    denoise_method: "None",
    do_sharp: checked("featureSharpening"),
    mask_output_type: selectedMaskExport(),
    folder_dict: {
      proc: "_Processed",
      proc_blur: "_Processed_Blurry",
      mask: "_Masks_Environment",
      blur: "_Blurry_Originals",
      subj: "_Masks_Subject",
      trans_env: "_Transparent_Environment",
      trans_subj: "_Transparent_Subject"
    },
    max_threads: selectedWorkerCount(),
    subfolder_mode: selectedSubfolderMode(),
    folder_search_depth: selectedFolderSearchDepth(),
    preserve_originals: checked("preserveOriginals"),
    image_type_flags: {
      jpg: checked("fileJpg"),
      png: checked("filePng"),
      tiff: checked("fileTiff"),
      heic: checked("fileHeic"),
      raw: checked("fileRaw")
    },
    jpg_quality: intValue("jpgQuality", 100),
    vid_ext_mode: value("videoFrameMode", "Target frame count").includes("Every") ? "Every Nth Frame" : "Target Amount of Frames",
    vid_extract_method: value("videoExtractMethod", "Fast extraction"),
    vid_ext_val: String(intValue("videoFrameTarget", 300)),
    vid_split: (inputType === "video_file" || inputType === "video_folder") && checked("sceneSplitToggle"),
    scene_sensitivity: value("sceneSensitivity", "Normal"),
    scene_min_seconds: Math.max(0.5, floatValue("sceneMinSeconds", 4)),
    vid_res: value("videoResolution", "Native"),
    preview_seek_ratio: Math.max(0, Math.min(1, floatValue("videoPreviewPosition", 0.5))),
    view_360_mode: value("view360Mode", "Standard 14 views"),
    include_360_bottom_views: checked("include360BottomViews"),
    time_thresh: intValue("sessionTimeGap", 60),
    sim_check: checked("bridgeByImageMatch"),
    sim_thresh: 30,
    min_imgs: intValue("sessionMinImages", 50),
    blur_rel: intValue("blurSensitivity", 35),
    cluster_sz: intValue("sharpnessClusterSize", 5),
    target_frames: intValue("sharpestKeepCount", 300),
    ev_boost: 0.0,
    clahe_clip: 1.5,
    clahe_grid: 32,
    clahe_sat: false,
    yolo_people: checked("maskPeople"),
    yolo_acc: checked("maskAccessories"),
    yolo_vehicle: checked("maskVehicles"),
    do_sky: checked("maskSky"),
    do_subj: checked("maskSubject"),
    mask_360_bottom: currentInputMode === "360" && checked("mask360Bottom"),
    invert_masks: checked("invertMasks"),
    debug_log: checked("writeDebugLog"),
    del_cache: checked("autoDeleteCache"),
    output_exists_mode: value("ifOutputExists", "Auto-number"),
    keep_folder_structure: checked("keepFolderStructure"),
    contrast_controls: {
      enabled: checked("adjustContrastToggle"),
      shadows: intValue("contrastShadows", 0),
      highlights: intValue("contrastHighlights", 0),
      midtones: intValue("contrastMidtones", 0),
      strength: intValue("contrastStrength", 50),
      protect_highlights: checked("protectHighlights")
    },
    sharpen_controls: {
      enabled: checked("featureSharpening"),
      amount: intValue("sharpenAmount", 60),
      radius: floatValue("sharpenRadius", 0.9),
      threshold: intValue("sharpenThreshold", 4)
    }
  };
}

document.querySelector("#chooseInputButton").addEventListener("click", async () => {
  const selected = (currentInputMode === "images" || currentInputMode === "videoFolder")
    ? await bridge.chooseFolder({ title: currentInputMode === "videoFolder" ? "Choose Folder of Videos" : "Choose ScanPrep Input Folder" })
    : await bridge.chooseFile({
        title: currentInputMode === "360" ? "Choose 360 Video" : "Choose Video",
        filters: [
          { name: "Video", extensions: ["mp4", "mov", "avi", "mkv", "wmv", "flv"] },
          { name: "All Files", extensions: ["*"] }
        ]
      });
  if (!selected) return;
  inputPath.value = selected;
  outputPath.value = await bridge.defaultOutputFor(selected);
  selectedPreviewImage = "";
  selectedPreviewDisplayImage = "";
  log(`Input set: ${selected}`);
  log(`Output auto-filled: ${outputPath.value}`);
});

document.querySelector("#chooseOutputButton").addEventListener("click", async () => {
  const folder = await bridge.chooseFolder({ title: "Choose ScanPrep Output Folder" });
  if (!folder) return;
  outputPath.value = folder;
  selectedPreviewImage = "";
  selectedPreviewDisplayImage = "";
  log(`Output set: ${folder}`);
});

document.querySelector("#choosePreviewButton").addEventListener("click", async () => {
  const file = await bridge.chooseFile({ title: "Choose Preview Image" });
  if (!file) return;
  await preparePreviewForDisplay(file);
});

function renderSinglePreview(file) {
  previewFrame.classList.add("preview-loaded");
  previewFrame.innerHTML = `<img class="preview-image preview-zoom-image" src="${pathToFileUrl(file)}" alt="Preview image" />`;
  resetPreviewZoom();
}

function renderPreviewComparison(originalPath, resultPath, label) {
  if (!originalPath || !resultPath) return;
  const originalDisplayPath = displayPathFor(originalPath);
  previewFrame.classList.add("preview-loaded");
  previewFrame.innerHTML = `
    <div class="preview-comparison">
      <figure>
        <img class="preview-zoom-image" src="${pathToFileUrl(originalDisplayPath)}" alt="Original preview" />
        <figcaption>Original</figcaption>
      </figure>
      <figure>
        <img class="preview-zoom-image" src="${pathToFileUrl(resultPath)}" alt="${label}" />
        <figcaption>${label}</figcaption>
      </figure>
    </div>`;
  resetPreviewZoom();
}

function renderMaskPreviewSet(originalPath, masks) {
  if (!originalPath || !masks.length) return;
  const originalDisplayPath = displayPathFor(originalPath);
  const buttons = masks.map((item, index) => `
    <button class="mask-thumb ${index === 0 ? "active" : ""}" data-mask-index="${index}">
      <img src="${pathToFileUrl(item.path)}" alt="${item.label || "Mask"} thumbnail" />
      <span>${item.label || `Mask ${index + 1}`}</span>
    </button>`).join("");
  previewFrame.classList.add("preview-loaded");
  previewFrame.innerHTML = `
    <div class="mask-preview-browser">
      <div class="mask-preview-stage">
        <figure>
          <img class="preview-zoom-image" src="${pathToFileUrl(originalDisplayPath)}" alt="Original preview" />
          <figcaption>Original</figcaption>
        </figure>
        <figure>
          <img id="activeMaskPreviewImage" class="preview-zoom-image" src="${pathToFileUrl(masks[0].path)}" alt="Selected mask preview" />
          <figcaption id="activeMaskPreviewLabel">${masks[0].label || "Mask"}</figcaption>
        </figure>
      </div>
      <div class="mask-thumb-strip">${buttons}</div>
    </div>`;
  const activeImage = document.querySelector("#activeMaskPreviewImage");
  const activeLabel = document.querySelector("#activeMaskPreviewLabel");
  document.querySelectorAll(".mask-thumb").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.dataset.maskIndex || 0);
      const item = masks[index];
      if (!item) return;
      activeImage.src = pathToFileUrl(item.path);
      activeLabel.textContent = item.label || `Mask ${index + 1}`;
      document.querySelectorAll(".mask-thumb").forEach((itemButton) => itemButton.classList.remove("active"));
      button.classList.add("active");
      applyPreviewZoom();
    });
  });
  resetPreviewZoom();
}

async function preparePreviewForDisplay(file) {
  if (isBackendRunning) return "";
  selectedPreviewImage = file;
  selectedPreviewDisplayImage = "";
  sawDoneEvent = false;
  setBackendRunning(true, "Preparing preview...");
  log(`Preparing preview: ${file}`);
  await bridge.prepareDisplayPreview({
    preview_image: file,
    output_dir: outputPath.value,
    jpg_quality: 92,
    max_edge: 2200,
    del_cache: checked("autoDeleteCache")
  });
  return file;
}

async function ensurePreviewImage() {
  if (selectedPreviewImage && selectedPreviewDisplayImage) return selectedPreviewImage;
  if (currentInputMode !== "images") {
    if (!inputPath.value || !outputPath.value) {
      log("Choose an input and output before previewing.");
      return "";
    }
    const config = collectRunConfig();
    config.max_edge = 2200;
    config.jpg_quality = Math.min(95, intValue("jpgQuality", 92));
    sawDoneEvent = false;
    setBackendRunning(true, "Preparing preview...");
    log(currentInputMode === "360" ? "Creating a 360 preview view..." : "Creating a video preview frame...");
    await bridge.prepareSourcePreview(config);
    return selectedPreviewImage;
  }
  const file = await bridge.chooseFile({ title: "Choose Preview Image" });
  if (!file) return "";
  return preparePreviewForDisplay(file);
}

previewMaskButton?.addEventListener("click", async () => {
  if (isBackendRunning) return;
  if (!hasMaskPreviewOptions()) return;
  const previewImage = await ensurePreviewImage();
  if (!previewImage) return;
  if (!outputPath.value) {
    log("Choose an output folder before previewing masks.");
    return;
  }
  const config = collectRunConfig();
  config.preview_image = previewImage;
  sawDoneEvent = false;
  setBackendRunning(true, "Previewing mask...");
  log("Creating mask preview...");
  await bridge.previewMask(config);
});

previewContrastButton?.addEventListener("click", async () => {
  if (isBackendRunning) return;
  if (!processingCreatesImageCopies()) return;
  const canCreateVideoPreviewInline = currentInputMode !== "images" && !(selectedPreviewImage && selectedPreviewDisplayImage);
  const previewImage = canCreateVideoPreviewInline ? "" : await ensurePreviewImage();
  if (!canCreateVideoPreviewInline && !previewImage) return;
  if (!outputPath.value) {
    log("Choose an output folder before previewing contrast.");
    return;
  }
  const config = collectRunConfig();
  config.preview_image = previewImage;
  config.preview_label = "Processing Preview";
  sawDoneEvent = false;
  setBackendRunning(true, "Previewing contrast...");
  log(canCreateVideoPreviewInline ? "Grabbing video frame and creating processing preview..." : "Creating contrast preview...");
  await bridge.previewContrast(config);
});

document.querySelector("#previewSharpnessButton").addEventListener("click", async () => {
  if (isBackendRunning) return;
  if (!inputPath.value || !outputPath.value) {
    log("Choose an input and output before previewing sharpness.");
    return;
  }
  const config = collectRunConfig();
  config.do_blur = true;
  config.sample_limit = 50;
  sawDoneEvent = false;
  sharpnessPreviewResult.textContent = "Preview running...";
  setBackendRunning(true, "Previewing sharpness...");
  log("Previewing sharpness on a small sample...");
  await bridge.previewSharpness(config);
});

document.querySelector("#diagnosticsButton").addEventListener("click", () => {
  openDiagnosticsPanel();
});

openEngineLogButton?.addEventListener("click", () => {
  openDiagnosticsPanel();
});

refreshDiagnosticsButton?.addEventListener("click", () => {
  refreshDiagnostics();
});

closeDiagnosticsButton?.addEventListener("click", closeDiagnosticsPanel);

diagnosticsOverlay?.addEventListener("click", (event) => {
  if (event.target === diagnosticsOverlay) closeDiagnosticsPanel();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !diagnosticsOverlay?.classList.contains("hidden")) {
    closeDiagnosticsPanel();
  }
});

openOutputFolderButton?.addEventListener("click", () => {
  if (!outputPath.value) {
    log("Choose an output folder before opening it.");
    return;
  }
  bridge.openPath(outputPath.value);
});

openDebugLogButton?.addEventListener("click", () => {
  if (!lastDebugLogPath) {
    log("No debug log path available yet.");
    return;
  }
  if (!lastDiagnostics?.logs?.debugLogExists) {
    log("No debug log file exists in the selected output folder yet.");
    return;
  }
  bridge.openPath(lastDebugLogPath);
});

zoomFitButton?.addEventListener("click", resetPreviewZoom);
zoomOutButton?.addEventListener("click", () => zoomPreviewBy(1 / 1.25));
zoomInButton?.addEventListener("click", () => zoomPreviewBy(1.25));

previewFrame.addEventListener("wheel", (event) => {
  if (!previewFrame.querySelector(".preview-zoom-image")) return;
  event.preventDefault();
  const direction = event.deltaY < 0 ? 1 : -1;
  zoomPreviewBy(direction > 0 ? 1.15 : 1 / 1.15);
}, { passive: false });

previewFrame.addEventListener("pointerdown", (event) => {
  if (previewZoom <= 1.001) return;
  if (event.target.closest("button, .mask-thumb-strip")) return;
  isPreviewPanning = true;
  previewPanStart = {
    x: event.clientX,
    y: event.clientY,
    panX: previewPanX,
    panY: previewPanY
  };
  previewFrame.setPointerCapture?.(event.pointerId);
  applyPreviewZoom();
});

previewFrame.addEventListener("pointermove", (event) => {
  if (!isPreviewPanning) return;
  previewPanX = previewPanStart.panX + event.clientX - previewPanStart.x;
  previewPanY = previewPanStart.panY + event.clientY - previewPanStart.y;
  applyPreviewZoom();
});

function endPreviewPan(event) {
  if (!isPreviewPanning) return;
  isPreviewPanning = false;
  previewFrame.releasePointerCapture?.(event.pointerId);
  applyPreviewZoom();
}

previewFrame.addEventListener("pointerup", endPreviewPan);
previewFrame.addEventListener("pointercancel", endPreviewPan);
previewFrame.addEventListener("pointerleave", (event) => {
  if (isPreviewPanning) endPreviewPan(event);
});

document.querySelector("#testGpuButton").addEventListener("click", async () => {
  if (isBackendRunning) return;
  sawDoneEvent = false;
  setBackendRunning(true, "Testing GPU...");
  log("Testing GPU support...");
  await bridge.testGpu();
});

runButton.addEventListener("click", async () => {
  if (isBackendRunning) {
    log("Stop requested. Closing the current Python task...");
    runStatus.textContent = "Stopping...";
    await bridge.cancelBackend();
    return;
  }
  if (!inputPath.value || !outputPath.value) {
    log("Choose an input and output before running.");
    return;
  }
  const config = collectRunConfig();
  sawDoneEvent = false;
  setBackendRunning(true, "Starting...");
  log("Starting ScanPrep run...");
  await bridge.runConfig(config);
});

function setInputMode(mode) {
  currentInputMode = mode;
  selectedPreviewImage = "";
  selectedPreviewDisplayImage = "";
  inputModeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.inputMode === mode);
  });
  videoSettings.classList.toggle("hidden", mode === "images");
  previewVideoPositionBlock?.classList.toggle("hidden", mode === "images");
  previewPanel?.classList.toggle("has-preview-position", mode !== "images");
  settings360.classList.toggle("hidden", mode !== "360");
  imageOnlySourceControls.forEach((element) => element?.classList.toggle("hidden", mode !== "images"));
  folderDepthControls.forEach((element) => element?.classList.toggle("hidden", mode !== "videoFolder"));
  if (mode !== "images") sortSettings.classList.add("hidden");
  else sortSettings.classList.toggle("hidden", !sortSessionsToggle.checked);
  inputPath.placeholder = mode === "images" ? "Choose folder..." : (mode === "videoFolder" ? "Choose video folder..." : "Choose video file...");
  update360ViewsHint();
  updateVideoFrameText();
  updateSceneSplitUi();
  updateOutputVisibility();
}

function update360MaskUi() {
  const counts = get360ViewCounts(value("view360Mode", "Standard 14 views"));
  const canMaskBottom = currentInputMode === "360" && include360BottomViews?.checked && counts.lower > 0;
  mask360BottomOption.classList.toggle("hidden", !canMaskBottom);
  if (!canMaskBottom) {
    const maskToggle = document.querySelector("#mask360Bottom");
    if (maskToggle) maskToggle.checked = false;
  }
  updatePreviewButtonStates();
}

function wireConditionalToggle(toggle, block) {
  if (!toggle || !block) return;
  const update = () => {
    block.classList.toggle("hidden", !toggle.checked);
    updateOutputVisibility();
  };
  toggle.addEventListener("change", update);
  update();
}

function updateSharpnessControls() {
  const mode = sharpnessMode.value;
  blurSensitivityBlock.classList.toggle("hidden", mode !== "Isolate Blurry Images");
  sharpestCountBlock.classList.toggle("hidden", mode !== "Isolate Sharpest Images");
  clusterSizeBlock.classList.toggle("hidden", mode !== "Isolate Weakest in Cluster");
}

inputModeButtons.forEach((button) => {
  button.addEventListener("click", () => setInputMode(button.dataset.inputMode));
});

sharpnessMode.addEventListener("change", updateSharpnessControls);
include360BottomViews?.addEventListener("change", () => {
  selectedPreviewImage = "";
  selectedPreviewDisplayImage = "";
  update360ViewsHint();
});
view360Mode?.addEventListener("change", () => {
  selectedPreviewImage = "";
  selectedPreviewDisplayImage = "";
  update360ViewsHint();
});
videoFrameMode?.addEventListener("change", updateVideoFrameText);
document.querySelector("#videoFrameTarget")?.addEventListener("input", updateVideoFrameText);
videoPreviewPosition?.addEventListener("input", () => updateVideoPreviewPositionText(true));
workerMode?.addEventListener("change", updateWorkersSummary);
sceneSplitToggle?.addEventListener("change", updateSceneSplitUi);
document.querySelector("#sceneMinSeconds")?.addEventListener("input", updateSceneSplitUi);
["adjustContrastToggle", "localContrastBoost", "exposureFusionLook", "featureSharpening"].forEach((id) => {
  document.querySelector(`#${id}`)?.addEventListener("change", updateOutputVisibility);
});
["maskPeople", "maskAccessories", "maskVehicles", "maskSky", "maskSubject", "mask360Bottom"].forEach((id) => {
  document.querySelector(`#${id}`)?.addEventListener("change", updatePreviewButtonStates);
});
document.querySelector("#processedFormat")?.addEventListener("change", updateOutputVisibility);
updateSharpnessControls();

wireConditionalToggle(sortSessionsToggle, sortSettings);
wireConditionalToggle(adjustContrastToggle, contrastControls);
wireConditionalToggle(featureSharpening, sharpenControls);
setInputMode(currentInputMode);
updateOutputVisibility();
updateVideoPreviewPositionText(false);
updateWorkersSummary();
updateSceneSplitUi();
updatePreviewButtonStates();

document.querySelectorAll("[data-help]").forEach((element) => {
  element.addEventListener("mouseenter", () => {
    hoverHelp.textContent = element.dataset.help;
  });
  element.addEventListener("focusin", () => {
    hoverHelp.textContent = element.dataset.help;
  });
  element.addEventListener("mouseleave", () => {
    hoverHelp.textContent = defaultHelpText;
  });
  element.addEventListener("focusout", () => {
    hoverHelp.textContent = defaultHelpText;
  });
});

document.querySelectorAll(".stage-card").forEach((card) => {
  card.addEventListener("click", () => {
    document.querySelectorAll(".stage-card").forEach((item) => item.classList.remove("active"));
    card.classList.add("active");
  });
});
