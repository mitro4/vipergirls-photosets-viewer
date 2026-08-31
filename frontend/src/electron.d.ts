// Exposed by Electron's preload.js (contextBridge). Absent in web/Docker mode.
export {};

declare global {
  interface Window {
    electronAPI?: {
      isElectron: true;
      showInFolder: (path: string) => Promise<void>;
      openPath: (path: string) => Promise<{ ok: boolean; missing?: boolean }>;
      chooseDownloadsFolder: () => Promise<string | null>;
    };
  }
}
