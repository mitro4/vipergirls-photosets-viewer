import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, Play, Square, Trash2, X } from "lucide-react";
import { api, QueueItem } from "../api/client";

function StatusBadge({ status }: { status: QueueItem["status"] }) {
  const map: Record<QueueItem["status"], { label: string; cls: string }> = {
    queued: { label: "Queued", cls: "bg-muted text-muted-foreground" },
    downloading: { label: "Downloading", cls: "bg-blue-500/15 text-blue-400" },
    stopped: { label: "Stopped", cls: "bg-amber-500/15 text-amber-400" },
    done: { label: "Done", cls: "bg-emerald-500/15 text-emerald-400" },
    error: { label: "Error", cls: "bg-red-500/15 text-red-400" },
  };
  const s = map[status];
  return (
    <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ${s.cls}`}>
      {status === "downloading" && <Loader2 className="h-3 w-3 animate-spin" />}
      {status === "done" && <CheckCircle2 className="h-3 w-3" />}
      {s.label}
    </span>
  );
}

export default function DownloadQueuePanel({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["queue"], queryFn: api.listQueue });
  const items = data?.items ?? [];

  const stopMut = useMutation({
    mutationFn: (tid: number) => api.stopQueueItem(tid),
    onSettled: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });
  const startMut = useMutation({
    mutationFn: (tid: number) => api.startQueueItem(tid),
    onSettled: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });
  const clearMut = useMutation({
    mutationFn: () => api.clearQueue(),
    onSettled: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });

  return (
    <div className="absolute right-0 top-full z-40 mt-2 w-[30rem] max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-border bg-card shadow-2xl">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">Download queue</h2>
          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
            {items.length}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => clearMut.mutate()}
            disabled={clearMut.isPending || items.length === 0}
            title="Clear queue"
            className="flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-accent/20 disabled:opacity-40"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Clear
          </button>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-muted-foreground hover:bg-accent/20"
            title="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="max-h-[60vh] overflow-y-auto">
        {items.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-muted-foreground">
            Queue is empty. Select threads and choose Download to add them here.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {items.map((it) => {
              const isActive = it.status === "downloading" || it.status === "queued";
              const pct = it.total > 0 ? Math.round((it.completed / it.total) * 100) : 0;
              return (
                <li key={it.thread_id} className="px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium" title={it.title}>
                        {it.title || `thread ${it.thread_id}`}
                      </p>
                      <div className="mt-1 flex items-center gap-2">
                        <StatusBadge status={it.status} />
                        <span className="font-mono text-xs text-muted-foreground">
                          {it.completed}/{it.total}
                          {it.failed > 0 && (
                            <span className="text-red-400"> · {it.failed} failed</span>
                          )}
                        </span>
                      </div>
                      {it.total > 0 && (
                        <div className="mt-1.5 h-1 w-full overflow-hidden rounded bg-muted">
                          <div
                            className={`h-full ${it.status === "error" ? "bg-red-500" : it.status === "done" ? "bg-emerald-500" : "bg-primary"}`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      )}
                      {it.status === "error" && it.error && (
                        <p className="mt-1 truncate text-[11px] text-red-400" title={it.error}>
                          {it.error}
                        </p>
                      )}
                    </div>
                    {it.status !== "done" && (
                      <button
                        onClick={() =>
                          isActive
                            ? stopMut.mutate(it.thread_id)
                            : startMut.mutate(it.thread_id)
                        }
                        disabled={stopMut.isPending || startMut.isPending}
                        title={isActive ? "Stop" : "Start"}
                        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border ${
                          isActive
                            ? "border-border hover:bg-red-500/10 hover:text-red-400"
                            : "border-border hover:bg-emerald-500/10 hover:text-emerald-400"
                        } disabled:opacity-40`}
                      >
                        {isActive ? (
                          <Square className="h-3.5 w-3.5" fill="currentColor" />
                        ) : (
                          <Play className="h-3.5 w-3.5" fill="currentColor" />
                        )}
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
