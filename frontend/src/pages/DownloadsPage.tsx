import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Loader2 } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { api, ThreadSummary } from "../api/client";
import { RetryImage } from "../components/RetryImage";
import { useOrderedCovers } from "../hooks/useOrderedCovers";

const PAGE_SIZE = 60;

function toSummary(id: number): ThreadSummary {
  return {
    id,
    title: "",
    forum_id: 0,
    prefix: "",
    author: "",
    posted_at: "",
    replies: 0,
    views: 0,
    cover_url: "",
    preview_urls: [],
    image_ids: [],
    image_count: 0,
    has_previews: false,
  };
}

export default function DownloadsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["downloads"],
    queryFn: api.downloads,
    // Sync with disk on every navigation into the page: the backend prunes
    // records whose folder was deleted externally as part of this GET.
    refetchOnMount: "always",
  });

  // Memoized so the array identity is stable across renders — otherwise the
  // cover-loader's effect re-fires every render and floods the backend with
  // POST /api/threads/covers requests (ERR_INSUFFICIENT_RESOURCES).
  const rawItems = data?.items;
  const items = useMemo(() => (rawItems ?? []).slice(0, PAGE_SIZE), [rawItems]);
  const folder = data?.folder ?? "";
  const isElectron = !!window.electronAPI;

  const summaries = useMemo(() => items.map((i) => toSummary(i.thread_id)), [items]);
  const { coverById } = useOrderedCovers(summaries);

  const qc = useQueryClient();
  const openFolder = async (filename: string) => {
    if (!folder || !window.electronAPI) return;
    // filename is the per-thread image subfolder (recorded server-side at
    // materialization time). Join with the downloads root → the thread's
    // folder. OS-native separators are tolerated by Electron's openPath.
    const sep = folder.includes("\\") && !folder.includes("/") ? "\\" : "/";
    const res = await window.electronAPI.openPath(`${folder}${sep}${filename}`);
    if (res && !res.ok) {
      // Folder missing (deleted externally / volume unmounted). Refresh the
      // list — the backend prunes records whose folder no longer exists — and
      // tell the user instead of leaving a confusing OS error dialog.
      qc.invalidateQueries({ queryKey: ["downloads"] });
      window.alert("Папка не найдена на диске. Запись удалена из списка.");
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-[70vh] items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading downloads…
      </div>
    );
  }

  return (
    <div className="pb-24">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <FolderOpen className="h-5 w-5" />
        <p className="text-sm text-muted-foreground">
          {items.length} downloaded photoset{items.length === 1 ? "" : "s"}
          {items.length > PAGE_SIZE && (
            <span className="ml-1 opacity-60">(showing first {PAGE_SIZE})</span>
          )}
        </p>
        {folder && (
          <span className="rounded-md border border-border px-2 py-0.5 text-xs text-muted-foreground">
            {folder}
          </span>
        )}
      </div>

      {items.length === 0 ? (
        <div className="flex h-[50vh] flex-col items-center justify-center gap-3 text-muted-foreground">
          <FolderOpen className="h-8 w-8 opacity-40" />
          <p className="text-sm">No downloads yet.</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4">
          {items.map((item) => {
            const cover = coverById.get(item.thread_id);
            const coverId = cover?.image_ids?.[0];
            const imgSrc = coverId
              ? api.imageUrl(coverId, "medium")
              : cover?.cover_url
                ? api.proxyUrl(cover.cover_url)
                : "";
            const imgCount = cover?.image_count ?? 0;
            return (
              <div
                key={item.thread_id}
                className="group relative flex flex-col overflow-hidden rounded-xl border border-border bg-card transition hover:border-primary/50 hover:shadow-lg hover:shadow-primary/5"
              >
                <Link to={`/thread/${item.thread_id}`} className="block">
                  <div className="relative aspect-[4/3] overflow-hidden bg-muted/20">
                    {imgSrc ? (
                      <RetryImage
                        src={imgSrc}
                        alt={item.title}
                        loading="lazy"
                        decoding="async"
                        className="absolute inset-0 h-full w-full object-contain transition-transform duration-200 group-hover:scale-105"
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center text-muted-foreground/30">
                        <FolderOpen className="h-8 w-8" />
                      </div>
                    )}
                    {imgCount > 0 && (
                      <span className="absolute right-1.5 top-1.5 rounded-md bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
                        {imgCount}
                      </span>
                    )}
                  </div>
                </Link>
                <div className="flex flex-1 flex-col gap-1 p-2.5">
                  <h3
                    className="line-clamp-2 text-xs font-medium leading-snug"
                    title={item.title}
                  >
                    {item.title}
                  </h3>
                  <span
                    className="truncate text-[10px] text-muted-foreground"
                    title={item.filename}
                  >
                    {item.filename}
                  </span>
                  {isElectron && folder && (
                    <button
                      onClick={() => openFolder(item.filename)}
                      title="Открыть папку в файловом менеджере"
                      className="mt-1 flex items-center justify-center gap-1.5 rounded-lg border border-border px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                    >
                      <FolderOpen className="h-3 w-3" />
                      Open folder
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
