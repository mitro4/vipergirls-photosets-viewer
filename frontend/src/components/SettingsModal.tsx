import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { X, Save, Loader2, Trash2, FolderOpen } from "lucide-react";
import { useState } from "react";
import { api, AppSettings, clearImageCache } from "../api/client";

interface Props {
  onClose: () => void;
}

export function SettingsModal({ onClose }: Props) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings,
  });
  const { data: stats } = useQuery({
    queryKey: ["stats"],
    queryFn: api.stats,
  });

  const [local, setLocal] = useState<AppSettings | null>(null);
  const settings = local ?? data ?? null;

  const saveMutation = useMutation({
    mutationFn: (body: Partial<AppSettings>) => api.updateSettings(body),
    onSuccess: (data) => {
      setLocal(data);
      queryClient.setQueryData(["settings"], data);
    },
  });

  const update = (key: keyof AppSettings, value: string | number | boolean) => {
    if (!settings) return;
    setLocal({ ...settings, [key]: value });
  };

  const [clearing, setClearing] = useState(false);
  const handleClear = async () => {
    setClearing(true);
    try {
      await clearImageCache();
      // Invalidate all queries so components re-render with the new
      // cache-bust token on image URLs. Settings modal stays open.
      await queryClient.invalidateQueries();
    } finally {
      setClearing(false);
    }
  };

  // Downloads folder lives outside AppSettings (owned by Electron, persisted
  // via /api/downloads/folder). Applied immediately through the native dialog,
  // not via the Save button.
  const isElectron = typeof window !== "undefined" && !!window.electronAPI;
  const { data: dlData } = useQuery({
    queryKey: ["downloads"],
    queryFn: api.downloads,
  });
  const downloadsFolder = dlData?.folder ?? "";
  const [pickingFolder, setPickingFolder] = useState(false);
  const handlePickFolder = async () => {
    if (!window.electronAPI) return;
    setPickingFolder(true);
    try {
      const chosen = await window.electronAPI.chooseDownloadsFolder();
      if (chosen) {
        await queryClient.invalidateQueries({ queryKey: ["downloads"] });
      }
    } finally {
      setPickingFolder(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-lg font-semibold">Settings</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {isLoading || !settings ? (
          <div className="flex h-64 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="max-h-[70vh] space-y-6 overflow-y-auto px-6 py-5">
            {/* Order images */}
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium">Sequential filenames</p>
                <p className="text-xs text-muted-foreground">
                  Rename images to 001.jpg, 002.jpg, … (ignores original names)
                </p>
              </div>
              <button
                onClick={() => update("order_images", !settings.order_images)}
                className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
                  settings.order_images ? "bg-primary" : "bg-muted"
                }`}
              >
                <span
                  className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                    settings.order_images ? "left-[22px]" : "left-0.5"
                  }`}
                />
              </button>
            </div>

            <Divider />

            {/* Download concurrency */}
            <SliderRow
              label="Concurrent image downloads"
              hint="Parallel image fetches within a single thread"
              value={settings.download_concurrency}
              min={1}
              max={20}
              onChange={(v) => update("download_concurrency", v)}
            />

            {/* Thread concurrency */}
            <SliderRow
              label="Concurrent thread downloads"
              hint="Parallel threads in multi-select download"
              value={settings.thread_concurrency}
              min={1}
              max={8}
              onChange={(v) => update("thread_concurrency", v)}
            />

            {/* Timeout */}
            <SliderRow
              label="Download timeout (seconds)"
              hint="Cancel a single image after this many seconds"
              value={settings.download_timeout}
              min={10}
              max={120}
              step={5}
              onChange={(v) => update("download_timeout", v)}
            />

            {/* Max retries */}
            <SliderRow
              label="Max retry attempts"
              hint="Retries per image on failure"
              value={settings.max_retries}
              min={0}
              max={10}
              onChange={(v) => update("max_retries", v)}
            />

            <Divider />

            {/* Auto-download */}
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium">Auto-download</p>
                <p className="text-xs text-muted-foreground">
                  Start downloading automatically when threads are added to the queue
                </p>
              </div>
              <button
                onClick={() => update("auto_download", !settings.auto_download)}
                className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
                  settings.auto_download ? "bg-primary" : "bg-muted"
                }`}
              >
                <span
                  className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                    settings.auto_download ? "left-[22px]" : "left-0.5"
                  }`}
                />
              </button>
            </div>

            {/* Auto-clear completed */}
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium">Auto-clear completed</p>
                <p className="text-xs text-muted-foreground">
                  Remove threads from the queue when fully downloaded
                </p>
              </div>
              <button
                onClick={() => update("auto_clear_completed", !settings.auto_clear_completed)}
                className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
                  settings.auto_clear_completed ? "bg-primary" : "bg-muted"
                }`}
              >
                <span
                  className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                    settings.auto_clear_completed ? "left-[22px]" : "left-0.5"
                  }`}
                />
              </button>
            </div>

            <Divider />

            {/* Forum domain */}
            <div className="space-y-2">
              <div>
                <p className="text-sm font-medium">Forum domain</p>
                <p className="text-xs text-muted-foreground">
                  Alternative mirror for accessing the forum
                </p>
              </div>
              <select
                value={settings.forum_proxy}
                onChange={(e) => update("forum_proxy", e.target.value)}
                className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none"
              >
                {(settings.available_domains ?? []).map((d) => (
                  <option key={d} value={d}>
                    {d.replace("https://", "")}
                  </option>
                ))}
              </select>
            </div>

            <Divider />

            {/* Network proxy (SOCKS5/HTTP) */}
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-medium">Network proxy</p>
                  <p className="text-xs text-muted-foreground">
                    Route all upstream requests (forum + image hosts) through a
                    proxy. SOCKS5 by default — just enter host:port. Explicit
                    schemes socks5://, http:// are also accepted.
                  </p>
                </div>
                <button
                  onClick={() => update("proxy_enabled", !settings.proxy_enabled)}
                  className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
                    settings.proxy_enabled ? "bg-primary" : "bg-muted"
                  }`}
                >
                  <span
                    className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                      settings.proxy_enabled ? "left-[22px]" : "left-0.5"
                    }`}
                  />
                </button>
              </div>
              <input
                type="text"
                value={settings.proxy_url ?? ""}
                onChange={(e) => update("proxy_url", e.target.value)}
                placeholder="127.0.0.1:1080  or  socks5://127.0.0.1:1080"
                disabled={!settings.proxy_enabled}
                className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm focus:border-primary focus:outline-none disabled:opacity-40"
              />
              <p className="text-xs text-muted-foreground">
                If your proxy requires authentication, enter the credentials
                below.
              </p>
              <div className="grid grid-cols-2 gap-2">
                <input
                  type="text"
                  value={settings.proxy_username ?? ""}
                  onChange={(e) => update("proxy_username", e.target.value)}
                  placeholder="Username (optional)"
                  disabled={!settings.proxy_enabled}
                  className="rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none disabled:opacity-40"
                />
                <input
                  type="password"
                  value={settings.proxy_password ?? ""}
                  onChange={(e) => update("proxy_password", e.target.value)}
                  placeholder="Password"
                  disabled={!settings.proxy_enabled}
                  className="rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none disabled:opacity-40"
                />
              </div>
            </div>

            <Divider />

            {/* Image cache */}
            <div className="space-y-2">
              <div>
                <p className="text-sm font-medium">Image cache</p>
                <p className="text-xs text-muted-foreground">
                  Force every image to re-download from its host. Useful when
                  previews are stuck or broken.
                </p>
              </div>
              {stats && (
                <p className="text-xs text-muted-foreground">
                  Current size:{" "}
                  <span className="font-mono font-medium text-foreground">
                    {(stats.cache_size_mb / 1024).toFixed(2)} GB
                  </span>
                </p>
              )}
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  value={settings.cache_limit_gb ?? 0}
                  onChange={(e) =>
                    update("cache_limit_gb", Math.max(0, parseFloat(e.target.value) || 0))
                  }
                  className="w-24 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none"
                />
                <p className="text-xs text-muted-foreground">
                  GB limit (0 = unlimited). Oldest cached files are removed in
                  the background to stay under it.
                </p>
              </div>
              <button
                onClick={handleClear}
                disabled={clearing}
                className="flex w-full items-center justify-center gap-2 rounded-lg border border-border px-4 py-2 text-sm hover:bg-secondary disabled:opacity-40"
              >
                {clearing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
                {clearing ? "Clearing…" : "Clear cache"}
              </button>
            </div>

            <Divider />

            {/* Downloads folder (desktop owns the save path; web is read-only) */}
            <div className="space-y-2">
              <div>
                <p className="text-sm font-medium">Downloads folder</p>
                <p className="text-xs text-muted-foreground">
                  Where ZIP archives are saved. The chosen folder applies immediately.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  readOnly
                  value={downloadsFolder || "Not set"}
                  className="flex-1 rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs focus:outline-none"
                />
                {isElectron && (
                  <button
                    onClick={handlePickFolder}
                    disabled={pickingFolder}
                    className="flex shrink-0 items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm hover:bg-secondary disabled:opacity-40"
                  >
                    {pickingFolder ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <FolderOpen className="h-4 w-4" />
                    )}
                    Browse…
                  </button>
                )}
              </div>
              {!isElectron && (
                <p className="text-xs text-muted-foreground">
                  Available in the desktop app only.
                </p>
              )}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-border px-6 py-4">
          <button
            onClick={onClose}
            className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-secondary"
          >
            Close
          </button>
          <button
            onClick={() => saveMutation.mutate(local ?? {})}
            disabled={!local || saveMutation.isPending}
            className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-40 hover:bg-primary/90"
          >
            {saveMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

function Divider() {
  return <div className="h-px bg-border" />;
}

function SliderRow({
  label,
  hint,
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  label: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium">{label}</p>
          <p className="text-xs text-muted-foreground">{hint}</p>
        </div>
        <span className="w-10 text-right text-sm font-semibold text-primary">
          {value}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-primary"
      />
    </div>
  );
}
