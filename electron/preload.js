"use strict";

// Runs in an isolated world (contextIsolation: true, nodeIntegration: false)
// and exposes a tiny, explicit surface to the renderer. The SPA detects
// Electron via `window.electronAPI` (undefined under a plain browser/Docker)
// and uses it only for "Show in folder" on the Downloads page.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  isElectron: true,
  showInFolder: (p) => ipcRenderer.invoke("show-in-folder", p),
  openPath: (p) => ipcRenderer.invoke("open-folder", p),
  chooseDownloadsFolder: () => ipcRenderer.invoke("choose-downloads-folder"),
});
