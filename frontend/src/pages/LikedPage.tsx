import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckSquare, Download, Heart, Loader2, X } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { api, ThreadSummary } from "../api/client";
import { ThreadCard } from "./CategoryPage";
import { useLikes } from "../hooks/useLikes";
import { useOrderedCovers } from "../hooks/useOrderedCovers";
import { useWaveLoader } from "../hooks/useWaveLoader";

// Page size for the liked grid — large enough to fill a wide screen, small
// enough that resolving covers stays cheap.
const PAGE_SIZE = 60;

function toSummary(id: number, title: string, likedAt: string): ThreadSummary {
  return {
    id,
    title,
    forum_id: 0,
    prefix: "",
    author: "",
    posted_at: likedAt,
    replies: 0,
    views: 0,
    cover_url: "",
    preview_urls: [],
    image_ids: [],
    image_count: 0,
    has_previews: false,
  };
}

export default function LikedPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["liked"],
    queryFn: api.liked,
  });
  const { loggedIn, likedIds, toggleLike } = useLikes();

  const rawItems = data?.items;
  const totalCount = rawItems?.length ?? 0;
  // Memoized so the array identity is stable across renders — otherwise the
  // cover-loader's effect (dep on this array) re-fires every render, each time
  // kicking off a fresh POST /api/threads/covers → a request storm that
  // exhausts the browser's connection pool (ERR_INSUFFICIENT_RESOURCES).
  const shown = useMemo(() => (rawItems ?? []).slice(0, PAGE_SIZE), [rawItems]);
  const summaries = useMemo(
    () => shown.map((i) => toSummary(i.thread_id, i.title, i.liked_at)),
    [shown],
  );
  const { coverById } = useOrderedCovers(summaries);

  const allCoversSettled =
    shown.length > 0 && shown.every((i) => coverById.has(i.thread_id));
  const { step: waveStep, reportCardDone } = useWaveLoader(
    shown.length,
    allCoversSettled,
  );

  // Multi-select + bulk download (mirrors CategoryPage).
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const toggleSelect = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelected(new Set(shown.map((i) => i.thread_id)));
  }, [shown]);

  const qc = useQueryClient();
  const addToQueueMut = useMutation({
    mutationFn: (ids: number[]) => api.addToQueue(ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });

  if (!loggedIn) {
    return (
      <div className="flex h-[70vh] flex-col items-center justify-center gap-3 text-muted-foreground">
        <Heart className="h-8 w-8 opacity-40" />
        <p className="text-sm">Log in to see photosets you've liked.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex h-[70vh] items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading liked…
      </div>
    );
  }

  return (
    <div className="pb-24">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Heart className="h-5 w-5 fill-red-500 text-red-500" />
          <p className="text-sm text-muted-foreground">
            {totalCount} liked photoset{totalCount === 1 ? "" : "s"}
            {totalCount > PAGE_SIZE && (
              <span className="ml-1 opacity-60">(showing first {PAGE_SIZE})</span>
            )}
          </p>
          {selectMode && shown.length > 0 && (
            <button
              onClick={selectAll}
              className="rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-secondary"
            >
              Select all ({shown.length})
            </button>
          )}
        </div>
        <button
          onClick={() => {
            if (selectMode) setSelected(new Set());
            setSelectMode(!selectMode);
          }}
          className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition-colors ${
            selectMode
              ? "border-primary bg-primary/10 text-primary"
              : "border-border hover:bg-accent/20"
          }`}
        >
          {selectMode ? (
            <>
              <X className="h-4 w-4" /> Cancel
            </>
          ) : (
            <>
              <CheckSquare className="h-4 w-4" /> Select
            </>
          )}
        </button>
      </div>

      {shown.length === 0 ? (
        <div className="flex h-[50vh] flex-col items-center justify-center gap-3 text-muted-foreground">
          <Heart className="h-8 w-8 opacity-40" />
          <p className="text-sm">
            No likes yet. Tap the heart on a card to save a photoset here.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4">
          {shown.map((item, idx) => {
            const thread = summaries[idx];
            return (
              <ThreadCard
                key={item.thread_id}
                thread={thread}
                cover={coverById.get(item.thread_id)}
                selectMode={selectMode}
                selected={selected.has(item.thread_id)}
                onToggleSelect={toggleSelect}
                liked={likedIds.has(item.thread_id)}
                onToggleLike={toggleLike}
                onDownload={(id) => addToQueueMut.mutate([id])}
                forumId={0}
                page={1}
                cardIdx={idx}
                waveStep={waveStep}
                reportCardDone={reportCardDone}
              />
            );
          })}
        </div>
      )}

      {/* Sticky selection bar */}
      {selectMode && selected.size > 0 && (
        <div className="fixed bottom-0 left-0 right-0 z-30 border-t border-border bg-card/95 backdrop-blur-md">
          <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-6 py-3">
            <div className="flex items-center gap-2 text-sm">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                {selected.size}
              </span>
              <span className="text-muted-foreground">
                {selected.size === 1 ? "thread" : "threads"} selected
              </span>
              <button
                onClick={() => setSelected(new Set())}
                className="ml-2 text-xs text-muted-foreground underline hover:text-foreground"
              >
                Clear
              </button>
            </div>
            <button
              onClick={() => {
                addToQueueMut.mutate([...selected]);
                setSelectMode(false);
                setSelected(new Set());
              }}
              disabled={addToQueueMut.isPending}
              className="flex items-center gap-2 rounded-lg bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            >
              {addToQueueMut.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              Download {selected.size}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
