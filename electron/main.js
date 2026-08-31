"use strict";

const { app, BrowserWindow, shell, Menu, session, nativeImage, ipcMain, dialog } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");

const PORT = parseInt(process.env.VIPER_PORT || "8000", 10);
const HOST = process.env.VIPER_HOST || "127.0.0.1";
const BACKEND_URL = `http://${HOST}:${PORT}`;
const MAX_WAIT_MS = 30000;

// Pin the app name early — on Linux this sets WM_CLASS so the window
// manager can match us to vipergirls-viewer.desktop and show the right icon
// in the taskbar/dock. Without this Electron may default to "electron" or
// the executable basename, which doesn't match the .desktop file.
app.setName("vipergirls-viewer");

// A packaged app may run with no attached terminal, so the read end of our
// own stdout/stderr can already be closed. Forwarding the backend's logs to a
// closed pipe then surfaces as an uncaught EPIPE that crashes the main
// process — typically hit on settings save, which triggers a burst of backend
// logs (session/proxy client rebuild). Keep log forwarding best-effort and
// never let a broken log pipe kill the app.
process.stdout?.on?.("error", () => {});
process.stderr?.on?.("error", () => {});
process.on("uncaughtException", (err) => {
  if (err && err.code === "EPIPE") return;  // benign broken log pipe
  throw err;  // real bugs still crash loudly
});

let pyProcess = null;
let pyPid = 0;
let startedBackend = false;  // true only if WE spawned the backend (not systemd)
let mainWindow = null;

function getAppRoot() {
  if (process.env.VIPERGIRLS_APP_ROOT) return process.env.VIPERGIRLS_APP_ROOT;
  return path.resolve(__dirname, "..", "..", "..");
}

function getPythonBinary(appRoot) {
  const isWin = process.platform === "win32";
  if (isWin) {
    // Windows: python/pythonw.exe in the python/ dir
    const exe = path.join(appRoot, "python", "python.exe");
    if (fs.existsSync(exe)) return exe;
    const exeW = path.join(appRoot, "python", "pythonw.exe");
    if (fs.existsSync(exeW)) return exeW;
    return "python";
  }
  const names = ["python3.12", "python3.13", "python3.11", "python3"];
  for (const name of names) {
    const p = path.join(appRoot, "python", "bin", name);
    if (fs.existsSync(p)) return p;
  }
  return "python3";
}

function startBackend() {
  const appRoot = getAppRoot();
  const pythonBin = getPythonBinary(appRoot);
  const backendDir = path.join(appRoot, "backend");
  const isWin = process.platform === "win32";
  // On Linux: PYTHONHOME + PYTHONPATH point the bundled Python at its libs
  // and backend source. On Windows: the embeddable Python uses python312._pth
  // which IGNORES PYTHONPATH entirely — the backend path is baked into ._pth
  // at build time (see packaging/docker/windows/Dockerfile). Setting
  // PYTHONHOME on embeddable Python can actually break it.
  const env = { ...process.env };
  if (!isWin) {
    env.PYTHONHOME = path.join(appRoot, "python");
    env.PYTHONPATH = backendDir;
  }

  console.log(`[main] starting backend: ${pythonBin} -m app.launcher --no-gui`);
  // On Linux: detached=true puts python in its own process group so we can
  // kill the whole tree via -pid on close.
  // On Windows: detached is a no-op for process groups; we track the PID
  // and use taskkill /T /F /PID on close.
  pyProcess = spawn(pythonBin, ["-m", "app.launcher", "--no-gui"], {
    cwd: backendDir,
    env,
    stdio: ["ignore", "pipe", "pipe"],
    detached: !isWin,
    windowsHide: true,
  });
  pyPid = pyProcess.pid;

  pyProcess.stdout.on("data", (d) => { try { process.stdout.write(d); } catch (_) {} });
  pyProcess.stderr.on("data", (d) => { try { process.stderr.write(d); } catch (_) {} });
  pyProcess.on("exit", (code, signal) => {
    console.log(`[main] backend exited (code=${code}, signal=${signal})`);
    pyProcess = null;
    pyPid = 0;
  });
  pyProcess.on("error", (err) => console.error("[main] backend error:", err.message));
}

/** Quick single-shot check: is a backend already listening on BACKEND_URL? */
function checkBackendRunning() {
  return new Promise((resolve) => {
    const req = http.get(`${BACKEND_URL}/api/health`, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(1500, () => {
      req.destroy();
      resolve(false);
    });
  });
}

function waitForBackend() {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + MAX_WAIT_MS;
    const check = () => {
      if (Date.now() > deadline) {
        reject(new Error(`backend not ready within ${MAX_WAIT_MS / 1000}s`));
        return;
      }
      const req = http.get(`${BACKEND_URL}/api/health`, (res) => {
        res.resume();
        if (res.statusCode === 200) resolve();
        else setTimeout(check, 200);
      });
      req.on("error", () => setTimeout(check, 200));
      req.setTimeout(2000, () => {
        req.destroy();
        setTimeout(check, 200);
      });
    };
    check();
  });
}

function resolveIcon() {
  const candidates = [
    path.join(__dirname, "icon.png"),
    path.join(getAppRoot(), "electron", "resources", "app", "icon.png"),
    path.join(getAppRoot(), "vipergirls-viewer.png"),
    path.join(getAppRoot(), "icon.png"),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) {
      // nativeImage is required on Linux for the BrowserWindow icon to
      // propagate to _NET_WM_ICON reliably; a bare string path is flaky
      // across Electron versions and window managers.
      const img = nativeImage.createFromPath(p);
      if (!img.isEmpty()) return img;
    }
  }
  return undefined;
}

async function createWindow() {
  try {
    await waitForBackend();
  } catch (err) {
    console.error("[main]", err.message);
  }

  // Clear Chromium HTTP cache: an upgraded rpm installs new content-hashed
  // asset filenames, but a cached index.html from a previous build would
  // still reference the old hashes → 404 → blank window.
  try {
    await session.defaultSession.clearCache();
    console.log("[main] cleared HTTP cache");
  } catch (err) {
    console.warn("[main] clearCache failed:", err.message);
  }

  const iconPath = resolveIcon();
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 800,
    minHeight: 500,
    title: "ViperGirls Viewer",
    backgroundColor: "#0f0f0f",
    ...(iconPath ? { icon: iconPath } : {}),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  mainWindow.loadURL(BACKEND_URL);

  // If the initial load fails (backend not quite ready, transient network
  // error), retry a few times instead of leaving the window blank.
  let loadRetries = 0;
  mainWindow.webContents.on("did-fail-load", (event, errorCode, errorDescription, validatedURL, isMainFrame) => {
    if (!isMainFrame) return;  // ignore sub-frame failures (assets, iframes)
    if (loadRetries++ >= 10) {
      console.error(`[main] loadURL failed after ${loadRetries} retries: ${errorDescription}`);
      return;
    }
    console.warn(`[main] loadURL failed (${errorDescription}), retry ${loadRetries}...`);
    setTimeout(() => mainWindow && mainWindow.loadURL(BACKEND_URL), 500);
  });

  // F12 toggles DevTools (no menu bar, so the accelerator isn't built-in).
  mainWindow.webContents.on("before-input-event", (event, input) => {
    if (input.type === "keyDown" && input.key === "F12") {
      mainWindow.webContents.toggleDevTools();
      event.preventDefault();
    }
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http://") || url.startsWith("https://")) {
      shell.openExternal(url);
      return { action: "deny" };
    }
    return { action: "allow" };
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function killBackend() {
  if (!startedBackend || !pyPid) return;  // don't kill a systemd-owned backend
  const pid = pyPid;
  const isWin = process.platform === "win32";
  console.log(`[main] stopping backend (pid=${pid})...`);
  if (isWin) {
    // Windows: taskkill /T kills the process tree, /F forces.
    try { spawn("taskkill", ["/T", "/F", "/PID", String(pid)], { windowsHide: true }); } catch (_) {}
    return;
  }
  // Linux: kill the whole process group (negative PID) — uvicorn may have forked.
  try { process.kill(-pid, "SIGTERM"); } catch (_) {
    try { process.kill(pid, "SIGTERM"); } catch (_) {}
  }
  setTimeout(() => {
    try { process.kill(-pid, "SIGKILL"); } catch (_) {
      try { process.kill(pid, "SIGKILL"); } catch (_) {}
    }
  }, 1000);
}

function buildMenu() {
  // Hide the native menu bar entirely (File/Edit/View/Window). DevTools is
  // still accessible via F12 (registered in createWindow via before-input-event).
  Menu.setApplicationMenu(null);
}

// Configurable downloads folder — no "Save As" dialog. Every download (ZIP
// archives) lands under downloadsDir/<filename>, so the Downloads page can
// deterministically pair an entry with its on-disk file for "Show in folder".
// The user picks the folder from Settings (desktop only); it's persisted via
// the backend so it survives restarts.
let downloadsDir = "";

function defaultDownloadsDir() {
  return path.join(app.getPath("downloads"), "ViperGirls");
}

// POST the given folder to the backend. Returns a promise that resolves true
// once the backend accepts it (200), or retries then resolves false on repeated
// error. Promise-based (not fire-and-forget) so the caller can await it before
// reading the folder back — this is what prevents a stale default-POST retry
// from clobbering a user's just-chosen folder.
function postFolder(folder, retries = 0) {
  const body = JSON.stringify({ folder });
  return new Promise((resolve) => {
    const attempt = (n) => {
      const req = http.request(
        `${BACKEND_URL}/api/downloads/folder`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Content-Length": Buffer.byteLength(body),
          },
        },
        (res) => { res.resume(); resolve(true); }
      );
      req.on("error", () => { if (n > 0) setTimeout(() => attempt(n - 1), 500); else resolve(false); });
      req.write(body);
      req.end();
    };
    attempt(retries);
  });
}

// Read the backend-stored folder (so a user-chosen folder survives restarts),
// falling back to the default. Registers will-download against the live
// downloadsDir so a later folder change takes effect at once.
async function initDownloads() {
  let stored = "";
  try {
    stored = await new Promise((resolve) => {
      const tryGet = (retries) => {
        const req = http.get(`${BACKEND_URL}/api/downloads`, (res) => {
          let body = "";
          res.on("data", (c) => { body += c; });
          res.on("end", () => {
            try { resolve(JSON.parse(body).folder || ""); }
            catch (_) { resolve(""); }
          });
        });
        req.on("error", () => { if (retries > 0) setTimeout(() => tryGet(retries - 1), 500); else resolve(""); });
        req.setTimeout(1500, () => { req.destroy(); if (retries > 0) setTimeout(() => tryGet(retries - 1), 500); else resolve(""); });
      };
      tryGet(10);
    });
  } catch (_) {}
  downloadsDir = stored || defaultDownloadsDir();
  try { fs.mkdirSync(downloadsDir, { recursive: true }); } catch (err) {
    console.warn("[main] mkdir downloads failed:", err.message);
  }
  if (!stored) postFolder(downloadsDir, 0);  // persist the default once (single attempt: never clobber a later user pick)
  // Auto-save every download to downloadsDir, skipping the dialog.
  session.defaultSession.on("will-download", (event, item) => {
    try {
      item.setSavePath(path.join(downloadsDir, item.getFilename()));
    } catch (err) {
      console.warn("[main] will-download setSavePath failed:", err.message);
    }
  });
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    buildMenu();
    // "Show in folder" from the Downloads page → reveal the ZIP in the OS
    // file manager (Finder/Explorer/xdg-open). Desktop-only by construction:
    // there's no electronAPI under a plain browser or the Docker web build.
    ipcMain.handle("show-in-folder", (event, p) => {
      if (typeof p === "string" && p.length) shell.showItemInFolder(p);
      return undefined;
    });
    // Open a folder in the OS file manager (Downloads page / batch-download
    // "Open folder"). Unlike show-in-folder (which highlights a file), this is
    // used to open a directory — the per-thread image folders on disk.
    // Returns a result object so the renderer can handle a stale/missing path
    // gracefully instead of triggering an OS "not found" error dialog.
    ipcMain.handle("open-folder", async (event, p) => {
      if (typeof p !== "string" || !p) return { ok: false };
      try {
        if (!fs.existsSync(p)) return { ok: false, missing: true };
      } catch (_) {
        return { ok: false, missing: true };
      }
      const errMsg = await shell.openPath(p);
      return { ok: !errMsg };
    });
    // Pick a downloads folder from Settings → native directory chooser. On
    // confirm: switch downloadsDir, ensure it exists, persist via the backend
    // so it survives restarts. Canceled → null (frontend treats as no-op).
    ipcMain.handle("choose-downloads-folder", async () => {
      try {
        const result = await dialog.showOpenDialog(mainWindow, {
          properties: ["openDirectory"],
        });
        if (result.canceled || !result.filePaths.length) return null;
        const chosen = result.filePaths[0];
        downloadsDir = chosen;
        try { fs.mkdirSync(chosen, { recursive: true }); } catch (_) {}
        // Await persistence BEFORE returning chosen: the frontend refetches
        // ['downloads'] the moment this resolves, so the backend must already
        // hold the new folder or reopen would show the old one.
        await postFolder(chosen, 3);
        return chosen;
      } catch (err) {
        console.warn("[main] choose-downloads-folder failed:", err.message);
        return null;
      }
    });
    // If a backend is already running (e.g. systemd service), reuse it
    // instead of spawning a second one (which would fail with "address
    // already in use").
    if (await checkBackendRunning()) {
      console.log("[main] backend already running, reusing");
    } else {
      startBackend();
      startedBackend = true;
    }
    createWindow();
    initDownloads();
  });
}

app.on("window-all-closed", () => {
  killBackend();
  app.quit();
  // Hard exit after 1.5s as a fallback — ensures the child process is
  // reaped and the port is released even if app.quit() hangs.
  setTimeout(() => process.exit(0), 1500);
});

app.on("before-quit", () => killBackend());

app.on("activate", () => {
  if (mainWindow === null) createWindow();
});
