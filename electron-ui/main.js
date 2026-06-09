const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn } = require("child_process");

const rootDir = path.resolve(__dirname, "..");
let activeBackend = null;
let cancelRequested = false;
let cancelEscalationTimer = null;

function getBackendTarget() {
  if (process.env.SCANPREP_BACKEND_EXE && fs.existsSync(process.env.SCANPREP_BACKEND_EXE)) {
    return {
      executable: process.env.SCANPREP_BACKEND_EXE,
      argsPrefix: [],
      cwd: path.dirname(process.env.SCANPREP_BACKEND_EXE)
    };
  }

  const packagedBackendNames = process.platform === "win32"
    ? ["ScanPrep Tool Backend.exe", "ScanPrep Engine Backend.exe", "3D Scan Prep Tool.exe"]
    : ["ScanPrep Tool Backend", "ScanPrep Engine Backend", "3D Scan Prep Tool"];
  for (const backendName of packagedBackendNames) {
    const backendExe = path.join(rootDir, "backend", backendName);
    if (fs.existsSync(backendExe)) {
      return {
        executable: backendExe,
        argsPrefix: [],
        cwd: path.dirname(backendExe)
      };
    }
  }

  let pythonExe = null;
  if (process.env.SCANPREP_PYTHON && fs.existsSync(process.env.SCANPREP_PYTHON)) {
    pythonExe = process.env.SCANPREP_PYTHON;
  }

  const venvPythonCandidates = process.platform === "win32"
    ? [path.join(rootDir, ".venv-scanprep-cu128", "Scripts", "python.exe")]
    : [
        path.join(rootDir, ".venv-scanprep-macos", "bin", "python"),
        path.join(rootDir, ".venv-scanprep-cu128", "bin", "python"),
        path.join(rootDir, ".venv", "bin", "python")
      ];
  for (const venvPython of venvPythonCandidates) {
    if (!pythonExe && fs.existsSync(venvPython)) pythonExe = venvPython;
  }
  if (!pythonExe) pythonExe = process.platform === "win32" ? "python" : "python3";

  return {
    executable: pythonExe,
    argsPrefix: [path.join(rootDir, "scan_prep_engine.py")],
    cwd: rootDir
  };
}

function sendBackendLine(webContents, line, stream = "stdout") {
  const trimmed = line.trim();
  if (!trimmed) return;
  try {
    webContents.send("backend-event", JSON.parse(trimmed));
  } catch (_error) {
    webContents.send("backend-event", { type: stream, message: trimmed });
  }
}

function streamProcessLines(stream, webContents, streamName) {
  let buffer = "";
  stream.on("data", (chunk) => {
    buffer += chunk.toString();
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() || "";
    lines.forEach((line) => sendBackendLine(webContents, line, streamName));
  });
  stream.on("end", () => {
    if (buffer) sendBackendLine(webContents, buffer, streamName);
  });
}

function runPythonBackend(webContents, args) {
  if (activeBackend) {
    webContents.send("backend-event", { type: "error", message: "A ScanPrep task is already running." });
    return Promise.resolve({ code: 1 });
  }

  const backend = getBackendTarget();
  const child = spawn(backend.executable, [...backend.argsPrefix, ...args], {
    cwd: backend.cwd,
    env: {
      ...process.env,
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
      PYTHONDONTWRITEBYTECODE: "1"
    },
    windowsHide: true
  });

  activeBackend = child;
  cancelRequested = false;
  webContents.send("backend-event", { type: "status", message: `Started ScanPrep tool: ${path.basename(backend.executable)}` });
  streamProcessLines(child.stdout, webContents, "stdout");
  streamProcessLines(child.stderr, webContents, "stderr");

  return new Promise((resolve) => {
    child.on("error", (error) => {
      webContents.send("backend-event", { type: "error", message: error.message });
      if (cancelEscalationTimer) clearTimeout(cancelEscalationTimer);
      cancelEscalationTimer = null;
      activeBackend = null;
      resolve({ code: 1 });
    });
    child.on("close", (code) => {
      const wasCancelled = cancelRequested;
      if (cancelEscalationTimer) clearTimeout(cancelEscalationTimer);
      cancelEscalationTimer = null;
      webContents.send("backend-event", {
        type: "exit",
        code: wasCancelled ? null : code,
        message: wasCancelled ? "Stopped." : `Python tool exited with code ${code}.`
      });
      activeBackend = null;
      cancelRequested = false;
      resolve({ code });
    });
  });
}

function runPythonJson(args) {
  const backend = getBackendTarget();
  return new Promise((resolve) => {
    const child = spawn(backend.executable, [...backend.argsPrefix, ...args], {
      cwd: backend.cwd,
      env: {
        ...process.env,
        PYTHONUTF8: "1",
        PYTHONIOENCODING: "utf-8",
        PYTHONDONTWRITEBYTECODE: "1"
      },
      windowsHide: true
    });

    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    child.on("error", (error) => resolve({ ok: false, error: error.message }));
    child.on("close", (code) => {
      const events = [];
      for (const line of stdout.split(/\r?\n/)) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          events.push(JSON.parse(trimmed));
        } catch (_error) {
          events.push({ type: "text", message: trimmed });
        }
      }
      resolve({ ok: code === 0, code, events, stderr: stderr.trim(), python: backend.executable });
    });
  });
}

function readTextTail(filePath, maxChars = 24000) {
  if (!filePath || !fs.existsSync(filePath)) return "";
  const text = fs.readFileSync(filePath, "utf-8");
  return text.length > maxChars ? text.slice(text.length - maxChars) : text;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1760,
    height: 990,
    minWidth: 1366,
    minHeight: 768,
    backgroundColor: "#061114",
    title: "KIRI Tools - ScanPrep",
    icon: path.join(rootDir, "Images and Icons", "KIRI Logo ICO.ico"),
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  win.once("ready-to-show", () => {
    win.show();
  });

  win.loadFile(path.join(__dirname, "renderer", "index.html"));
}

app.whenReady().then(() => {
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

ipcMain.handle("choose-folder", async (_event, options = {}) => {
  const result = await dialog.showOpenDialog({
    title: options.title || "Choose Folder",
    properties: ["openDirectory"]
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

ipcMain.handle("choose-file", async (_event, options = {}) => {
  const result = await dialog.showOpenDialog({
    title: options.title || "Choose File",
    properties: ["openFile"],
    filters: options.filters || [
      { name: "Images", extensions: ["jpg", "jpeg", "png", "tif", "tiff", "heic", "heif", "dng", "cr2", "nef", "arw", "orf", "rw2"] },
      { name: "All Files", extensions: ["*"] }
    ]
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

ipcMain.handle("choose-files", async (_event, options = {}) => {
  const result = await dialog.showOpenDialog({
    title: options.title || "Choose Files",
    properties: ["openFile", "multiSelections"],
    filters: options.filters || [
      { name: "Images", extensions: ["jpg", "jpeg", "png", "tif", "tiff", "heic", "heif", "dng", "cr2", "nef", "arw", "orf", "rw2"] },
      { name: "All Files", extensions: ["*"] }
    ]
  });
  if (result.canceled || result.filePaths.length === 0) return [];
  return result.filePaths;
});

ipcMain.handle("default-output-for", (_event, inputPath) => {
  if (!inputPath) return "";
  try {
    if (fs.existsSync(inputPath) && fs.statSync(inputPath).isFile()) {
      return path.join(path.dirname(inputPath), "_ScanPrep_Output");
    }
  } catch (_error) {
    return path.join(path.dirname(inputPath), "_ScanPrep_Output");
  }
  return path.join(inputPath, "_ScanPrep_Output");
});

ipcMain.handle("get-diagnostics", async (_event, cfg = {}) => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "scanprep-diagnostics-"));
  const configPath = path.join(tmpDir, "config.json");
  fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2), "utf-8");
  const result = await runPythonJson(["--system-diagnostics-json", configPath]);
  const diagnosticEvent = result.events?.find((event) => event.type === "system_diagnostics");
  const diagnostics = diagnosticEvent?.diagnostics || {};
  const outputDir = cfg.output_dir || diagnostics.paths?.output_dir || "";
  const debugLogPath = outputDir ? path.join(outputDir, "_debug_timing_log.txt") : "";
  return {
    ok: result.ok,
    code: result.code,
    error: result.error || result.stderr || "",
    diagnostics,
    app: {
      rootDir,
      electron: process.versions.electron,
      node: process.versions.node,
      platform: process.platform,
      python: result.python || getBackendTarget().executable
    },
    logs: {
      debugLogPath,
      debugLogExists: Boolean(debugLogPath && fs.existsSync(debugLogPath)),
      debugLogText: readTextTail(debugLogPath)
    }
  };
});

ipcMain.handle("backend-test-gpu", async (event) => {
  return runPythonBackend(event.sender, ["--gpu-test-json"]);
});

ipcMain.handle("backend-run-config", async (event, cfg) => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "scanprep-config-"));
  const configPath = path.join(tmpDir, "config.json");
  fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2), "utf-8");
  return runPythonBackend(event.sender, ["--run-config", configPath]);
});

ipcMain.handle("backend-sharpness-preview", async (event, cfg) => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "scanprep-sharpness-preview-"));
  const configPath = path.join(tmpDir, "config.json");
  fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2), "utf-8");
  return runPythonBackend(event.sender, ["--sharpness-preview-config", configPath]);
});

ipcMain.handle("backend-display-preview", async (event, cfg) => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "scanprep-display-preview-"));
  const configPath = path.join(tmpDir, "config.json");
  fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2), "utf-8");
  return runPythonBackend(event.sender, ["--display-preview-config", configPath]);
});

ipcMain.handle("backend-source-preview", async (event, cfg) => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "scanprep-source-preview-"));
  const configPath = path.join(tmpDir, "config.json");
  fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2), "utf-8");
  return runPythonBackend(event.sender, ["--source-preview-config", configPath]);
});

ipcMain.handle("backend-mask-preview", async (event, cfg) => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "scanprep-mask-preview-"));
  const configPath = path.join(tmpDir, "config.json");
  fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2), "utf-8");
  return runPythonBackend(event.sender, ["--mask-preview-config", configPath]);
});

ipcMain.handle("backend-contrast-preview", async (event, cfg) => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "scanprep-contrast-preview-"));
  const configPath = path.join(tmpDir, "config.json");
  fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2), "utf-8");
  return runPythonBackend(event.sender, ["--contrast-preview-config", configPath]);
});

ipcMain.handle("backend-cancel", async (event) => {
  if (!activeBackend) return { cancelled: false };
  cancelRequested = true;
  const child = activeBackend;
  event.sender.send("backend-event", { type: "status", message: "Stop requested. Finishing current task safely..." });
  try {
    if (child.stdin && !child.stdin.destroyed) {
      child.stdin.write("cancel\n");
      child.stdin.end();
    }
  } catch (_error) {
    // Fall back to the timer below if stdin is unavailable.
  }
  if (cancelEscalationTimer) clearTimeout(cancelEscalationTimer);
  cancelEscalationTimer = setTimeout(() => {
    if (activeBackend === child && child.exitCode === null) {
      event.sender.send("backend-event", { type: "status", message: "Stop is taking longer than expected. Closing the tool now..." });
      child.kill();
    }
  }, 15000);
  cancelEscalationTimer.unref?.();
  return { cancelled: true };
});

ipcMain.handle("open-path", async (_event, targetPath) => {
  if (!targetPath || !fs.existsSync(targetPath)) return { opened: false };
  const error = await shell.openPath(targetPath);
  return { opened: error === "", error };
});
