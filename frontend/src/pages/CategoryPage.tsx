import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CheckSquare,
  Clock,
  Download,
  Eye,
  Heart,
  Loader2,
  MessageSquare,
  ImageIcon,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { LayoutGrid, List } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api, CoverOut, ThreadSummary } from "../api/client";
import Pagination from "../components/Pagination";
import { RetryImage } from "../components/RetryImage";
import { MAX_SLOTS, useWaveLoader } from "../hooks/useWaveLoader";
import { useLikes } from "../hooks/useLikes";
import { useOrderedCovers } from "../hooks/useOrderedCovers";
import { useViewMode } from "../hooks/useViewMode";

// Stable empty list so `data?.threads ?? EMPTY_THREADS` keeps the SAME reference
// while data is loading. Without this, the fallback `[]` would be a new array
// every render and trip the ordered-reveal reset / re-run the fetch pump.
const EMPTY_THREADS: ThreadSummary[] = [];

export default function CategoryPage({
  forumId,
  active = true,
}: {
  forumId: number;
  active?: boolean;
}) {
  // Page/sort are kept in LOCAL state (not read reactively from the URL on
  // every render) because this component stays mounted across thread
  // navigation — when hidden, useSearchParams would otherwise return the
  // thread URL's params and pollute the state. We sync from URL only while
  // `active` (i.e. when the user is actually on a category route).
  const [searchParams, setSearchParams] = useSearchParams();
  const [page, setPage] = useState(() => Number(searchParams.get("page")) || 1);
  const [sort, setSort] = useState<"new" | "old">(
    () => (searchParams.get("sort") as "new" | "old") || "new",
  );
  useEffect(() => {
    if (active) {
      setPage(Number(searchParams.get("page")) || 1);
      setSort((searchParams.get("sort") as "new" | "old") || "new");
    }
  }, [active, searchParams]);

  const fid = forumId;
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [viewMode, setViewMode] = useViewMode();

  useEffect(() => {
    setSelected(new Set());
    setSelectMode(false);
  }, [fid]);

  const goToPage = useCallback(
    (next: number) => {
      setPage(next);
      setSearchParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          if (next <= 1) p.delete("page");
          else p.set("page", String(next));
          return p;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const changeSort = useCallback(
    (next: string) => {
      setSort(next as "new" | "old");
      setPage(1);
      setSearchParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          // "new" (newest first) is the default — omit it from the URL.
          if (next === "new") p.delete("sort");
          else p.set("sort", next);
          p.delete("page");
          return p;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["threads", fid, page, sort],
    queryFn: ({ signal }) => api.threads(fid, page, sort, signal),
    enabled: fid > 0,
  });

  const threads = data?.threads ?? EMPTY_THREADS;
  const { coverById } = useOrderedCovers(threads);

  // Wave-loading coordinator: gate on all covers being settled so the wave
  // starts cleanly once every card knows how many images it has.  Before
  // settlement the step stays at 0 and cards display spinners.
  const allCoversSettled =
    threads.length > 0 && threads.every((t) => coverById.has(t.id));
  const { step: waveStep, reportCardDone } = useWaveLoader(
    threads.length,
    allCoversSettled,
  );

  const qc = useQueryClient();
  const addToQueueMut = useMutation({
    mutationFn: (ids: number[]) => api.addToQueue(ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });

  const { loggedIn, likedIds, toggleLike } = useLikes();

  const toggleSelect = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const setView = setViewMode;

  const selectAll = useCallback(() => {
    if (!data) return;
    setSelected(new Set(data.threads.map((t) => t.id)));
  }, [data]);

  const selectedList = [...selected];

  if (!fid) {
    return (
      <div className="flex h-[70vh] items-center justify-center text-muted-foreground">
        Select a category from the sidebar.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex h-[70vh] items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading threads…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex h-[70vh] flex-col items-center justify-center text-muted-foreground">
        <p className="mb-2 text-sm">Failed to load threads.</p>
        <p className="text-xs opacity-60">{String(error)}</p>
        <button
          onClick={() => refetch()}
          className="mt-4 rounded-lg bg-primary/20 px-4 py-2 text-sm text-primary hover:bg-primary/30"
        >
          Retry
        </button>
      </div>
    );
  }

  const totalPages = data.total_pages || 1;

  return (
    <div className="pb-24">
      {/* Page header */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <p className="text-sm text-muted-foreground">
            Page {page} of {totalPages}
            {data.threads.length > 0 && ` · ${data.threads.length} threads`}
          </p>
          {selectMode && selected.size > 0 && (
            <button
              onClick={selectAll}
              className="rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-secondary"
            >
              Select all ({data.threads.length})
            </button>
          )}
        </div>
        <div className="flex gap-2">
          {/* Sort order */}
          <select
            value={sort}
            onChange={(e) => changeSort(e.target.value)}
            title="Sort order"
            className="rounded-lg border border-border bg-background px-2 py-1.5 text-sm hover:bg-accent/20"
          >
            <option value="new">Newest first</option>
            <option value="old">Oldest first</option>
          </select>
          {/* View mode toggle */}
          <div className="flex items-center rounded-lg border border-border p-0.5">
            <button
              onClick={() => setView("grid")}
              title="Grid view"
              className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${
                viewMode === "grid"
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
            <button
              onClick={() => setView("list")}
              title="List view"
              className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${
                viewMode === "list"
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <List className="h-4 w-4" />
            </button>
          </div>
          <button
            onClick={() => {
              if (selectMode) {
                setSelected(new Set());
              }
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
          <Pagination page={page} totalPages={totalPages} onChange={goToPage} />
        </div>
      </div>

      {/* Thread grid */}
      {viewMode === "list" ? (
        <div className="flex flex-col gap-3">
          {data.threads.map((t) => (
            <ThreadRow
              key={t.id}
              thread={t}
              cover={coverById.get(t.id)}
              selectMode={selectMode}
              selected={selected.has(t.id)}
              onToggleSelect={toggleSelect}
              liked={likedIds.has(t.id)}
              onToggleLike={loggedIn ? toggleLike : undefined}
              forumId={fid}
              page={page}
            />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4">
          {data.threads.map((t, idx) => (
            <ThreadCard
              key={t.id}
              thread={t}
              cover={coverById.get(t.id)}
              selectMode={selectMode}
              selected={selected.has(t.id)}
              onToggleSelect={toggleSelect}
              liked={likedIds.has(t.id)}
                onToggleLike={loggedIn ? toggleLike : undefined}
                onDownload={(id) => addToQueueMut.mutate([id])}
                forumId={fid}
                page={page}
                cardIdx={idx}
              waveStep={waveStep}
              reportCardDone={reportCardDone}
            />
          ))}
        </div>
      )}

      {data.threads.length === 0 && (
        <div className="flex h-[50vh] items-center justify-center text-sm text-muted-foreground">
          No threads found on this page.
        </div>
      )}

      <Pagination
        page={page}
        totalPages={totalPages}
        onChange={goToPage}
        className="pt-4"
      />

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
                addToQueueMut.mutate(selectedList);
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

export function ThreadCard({
  thread,
  cover,
  selectMode,
  selected,
  onToggleSelect,
  liked,
  onToggleLike,
  onDownload,
  forumId,
  page,
  cardIdx,
  waveStep,
  reportCardDone,
}: {
  thread: ThreadSummary;
  cover?: CoverOut | null;
  selectMode: boolean;
  selected: boolean;
  onToggleSelect: (id: number) => void;
  liked?: boolean;
  onToggleLike?: (id: number) => void;
  onDownload?: (id: number) => void;
  forumId: number;
  page: number;
  cardIdx: number;
  waveStep: number;
  reportCardDone: (cardIdx: number) => void;
}) {
  const imageIds = (cover?.image_ids ?? thread.image_ids ?? []).slice(0, MAX_SLOTS);
  // Stable string key for effect dependencies (imageIds is a new array each
  // render, but its contents are stable while cover data doesn't change).
  const imageIdsKey = imageIds.join(",");

  // Slots whose thumb / medium variant has been confirmed loaded by a
  // background Image() probe.  The visible <img> src is derived from these
  // sets, so the browser never fires a request until the wave unlocks that
  // slot — and when it does, the response is already cached (instant paint).
  //
  // Initialise from the current waveStep so a card that remounts mid-wave
  // (e.g. grid→list→grid view switch) instantly reflects all slots the wave
  // has already passed — images are in the browser cache, no re-probe needed.
  const [thumbReady, setThumbReady] = useState<Set<number>>(
    () =>
      new Set(
        Array.from(
          { length: waveStep >= MAX_SLOTS ? imageIds.length : Math.min(waveStep, imageIds.length) },
          (_, i) => i,
        ),
      ),
  );
  const [mediumReady, setMediumReady] = useState<Set<number>>(
    // Only the cover (slot 0) upgrades to medium during the wave; preview
    // mediums are deferred to hover (see hoverMediumReady below). So this set
    // only ever tracks slot 0.
    () => (waveStep > MAX_SLOTS ? new Set([0]) : new Set()),
  );
  // Preview slots (1..N) get their medium only on hover, so we don't pull a
  // full-size original for every carousel image the user may never look at.
  const [hoverMediumReady, setHoverMediumReady] = useState<Set<number>>(
    new Set(),
  );

  // Reset state when image IDs change (page nav, new cover data) — but skip
  // the first mount so the waveStep-aware initialiser above takes effect.
  const firstMountRef = useRef(true);
  useEffect(() => {
    if (firstMountRef.current) {
      firstMountRef.current = false;
      return;
    }
    setThumbReady(new Set());
    setMediumReady(new Set());
  }, [imageIdsKey]);

  // --- Wave coordination ---------------------------------------------------
  // A single effect that, for each waveStep, either:
  //  • auto-reports if the card has no image at the current slot, or
  //  • fires a background Image() probe (thumb or medium depending on phase).
  //
  // Thumb phase (step < MAX_SLOTS): probe thumb → onload adds to thumbReady.
  // Medium phase (step >= MAX_SLOTS): probe medium → onload adds to mediumReady.
  // onerror always reports done (don't stall the wave on a broken host).
  //
  // IMPORTANT: an in-flight probe is deliberately NOT aborted when the wave
  // advances past its slot. The coordinator moves on once a 90% quorum of
  // cards finishes, so the slowest card's probe is routinely still in flight
  // at that moment — aborting it (probe.src = "" in a cleanup) would leave
  // that slot permanently unloaded: nothing ever revisits an earlier slot,
  // so the card would show an eternal spinner / blank preview. Instead the
  // probe is allowed to finish in the background; finish() marks its slot
  // ready and reports whenever it lands. pendingProbeRef deduplicates probes
  // across effect re-runs (thumbReady/mediumReady are deps and change often).
  const pendingProbeRef = useRef<Set<string>>(new Set());
  // Set false on unmount so a late finish() doesn't report toward a page the
  // card is no longer part of (cardIdx recycles across pages).
  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);
  useEffect(() => {
    if (imageIds.length === 0) {
      reportCardDone(cardIdx);
      return;
    }

    const isThumbPhase = waveStep < MAX_SLOTS;
    const slot = isThumbPhase ? waveStep : waveStep - MAX_SLOTS;

    if (slot >= imageIds.length || slot < 0 || waveStep >= 2 * MAX_SLOTS) {
      // Card has no image at this slot, or wave is complete — auto-report.
      reportCardDone(cardIdx);
      return;
    }

    if (!isThumbPhase && slot > 0) {
      // Only the cover (slot 0) upgrades to medium during the wave. Preview
      // mediums are lazy-loaded on hover to avoid downloading full-size
      // originals for images the user may never look at.
      reportCardDone(cardIdx);
      return;
    }

    const probeKey = `${isThumbPhase ? "t" : "m"}:${slot}`;
    const already = isThumbPhase
      ? thumbReady.has(slot)
      : mediumReady.has(slot);
    if (already) {
      reportCardDone(cardIdx);
      return;
    }
    if (pendingProbeRef.current.has(probeKey)) {
      // A probe for this slot is still in flight from an earlier run (the
      // wave advanced past us, or another slot's finish re-triggered this
      // effect) — its finish() will report. Don't fire a duplicate.
      return;
    }
    pendingProbeRef.current.add(probeKey);

    const finish = (ok: boolean) => {
      pendingProbeRef.current.delete(probeKey);
      if (isThumbPhase) {
        // Always mark thumb slot as ready — on failure, RetryImage will
        // show the red-X fallback instead of an infinite spinner.
        setThumbReady((s) => (s.has(slot) ? s : new Set(s).add(slot)));
      } else if (ok) {
        // Only upgrade to medium on success — on failure, keep showing
        // the cached thumb (which is already visible).
        setMediumReady((s) => (s.has(slot) ? s : new Set(s).add(slot)));
      }
      if (aliveRef.current) reportCardDone(cardIdx);
    };
    const probe = new Image();
    probe.onload = () => finish(true);
    probe.onerror = () => finish(false);
    probe.src = api.imageUrl(
      imageIds[slot],
      isThumbPhase ? "thumb" : "medium",
    );
  }, [waveStep, imageIdsKey, cardIdx, reportCardDone, thumbReady, mediumReady]);

  // --- Visible image URLs --------------------------------------------------
  // A slot is visible only after its thumb probe has landed (thumbReady).
  // If the medium probe has also landed (mediumReady), show the medium URL
  // instead — browser cache hit, instant swap, no flash.
  const imageUrls = imageIds.map((id, i) => {
    if (!thumbReady.has(i)) return "";
    if (i === 0) {
      // Cover: wave-upgraded medium.
      return mediumReady.has(0)
        ? api.imageUrl(id, "medium")
        : api.imageUrl(id, "thumb");
    }
    // Previews: medium only after the user has hovered this slot.
    return hoverMediumReady.has(i)
      ? api.imageUrl(id, "medium")
      : api.imageUrl(id, "thumb");
  });
  const coverUrl = imageUrls[0] || "";
  const imageCount = thread.image_count || cover?.image_count || 0;
  const settled = cover !== undefined;
  const showImg = coverUrl.length > 0;
  // Hover carousel state. `active` is the currently shown slot (null = not
  // hovering). `from` keeps the PREVIOUSLY shown preview opaque for the
  // duration of the crossfade: the incoming slot fades in on top of it
  // (z-10), so the cover never bleeds through underneath and mixed
  // -orientation images don't ghost-stack during the opacity transition.
  const hoverActiveRef = useRef<number | null>(null);
  const [hover, setHover] = useState<{
    active: number | null;
    from: number | null;
  }>({ active: null, from: null });
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const imgElRef = useRef<HTMLDivElement>(null);

  const applyHover = useCallback((idx: number | null) => {
    if (hoverActiveRef.current === idx) return;
    const prev = hoverActiveRef.current;
    hoverActiveRef.current = idx;
    setHover({ active: idx, from: prev !== null && prev > 0 ? prev : null });
    // Drop the outgoing overlay once the incoming fade has fully covered it
    // (it sits underneath, invisible by then).
    clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(
      () => setHover((h) => ({ ...h, from: null })),
      240,
    );
  }, []);

  useEffect(() => () => clearTimeout(hoverTimer.current), []);

  const handleMouseEnter = useCallback(() => {
    if (imageUrls.length > 1 && !selectMode) {
      applyHover(0);
    }
  }, [imageUrls.length, selectMode, applyHover]);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (imageUrls.length <= 1 || !imgElRef.current || selectMode) return;
      const rect = imgElRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const idx = Math.min(
        imageUrls.length - 1,
        Math.floor((x / rect.width) * imageUrls.length),
      );
      applyHover(idx);
    },
    [imageUrls.length, selectMode, applyHover],
  );

  const handleMouseLeave = useCallback(() => applyHover(null), [applyHover]);

  // Lazy medium upgrade for hover-carousel previews (slots 1+). On hover we
  // background-probe the medium; once cached, the visible src swaps to it
  // (instant, no flash — the thumb stays painted via useImageRetry until the
  // medium has loaded).
  useEffect(() => {
    if (hover.active === null || hover.active === 0) return;
    if (hover.active >= imageIds.length) return;
    const slot = hover.active;
    if (hoverMediumReady.has(slot)) return;
    let done = false;
    const probe = new Image();
    probe.onload = () => {
      if (done) return;
      setHoverMediumReady((s) =>
        s.has(slot) ? s : new Set(s).add(slot),
      );
    };
    probe.onerror = () => {};  // keep showing thumb on failure
    probe.src = api.imageUrl(imageIds[slot], "medium");
    return () => {
      done = true;
      probe.onload = null;
      probe.onerror = null;
      probe.src = "";
    };
  }, [hover.active, imageIdsKey, hoverMediumReady]);

  const cardClasses = `group relative flex flex-col overflow-hidden rounded-xl border bg-card transition ${
    selectMode
      ? selected
        ? "border-primary ring-2 ring-primary/40"
        : "border-border"
      : "border-border hover:border-primary/50 hover:shadow-lg hover:shadow-primary/5"
  }`;

  const cardContent = (
    <>
      <div
        ref={imgElRef}
        className="relative aspect-[4/3] overflow-hidden bg-muted/20"
        onMouseEnter={handleMouseEnter}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        {showImg ? (
          <>
            <RetryImage
              src={coverUrl}
              alt={thread.title}
              loading="eager"
              decoding="async"
              // High priority for the visible cover (fetchPriority is
              // supported natively as of React 18.3).
              fetchPriority="high"
              className={`absolute inset-0 h-full w-full bg-background object-contain transition-transform duration-200 ${
                !selectMode && "group-hover:scale-105"
              }`}
            />
            {imageUrls.length > 1 &&
              imageUrls.slice(1).map((url, i) => {
                const slot = i + 1;
                // Opaque during the crossfade if it's the incoming active
                // slot OR the outgoing one (`from`) — the incoming fades in
                // on top (z-10), the outgoing stays fully opaque underneath,
                // so the cover never shows through half-faded previews.
                // bg-background is REQUIRED: it occludes the cover behind a
                // portrait preview's letterbox bars (transparent bars would
                // show the cover photo — two different images in one card).
                const visible =
                  hover.active === slot || hover.from === slot;
                return url ? (
                  <RetryImage
                    key={i}
                    src={url}
                    alt=""
                    loading="eager"
                    decoding="async"
                    flashOnSwap={false}
                    // Hover previews are hidden until hover — low priority so
                    // they never contend with visible covers for bandwidth.
                    fetchPriority="low"
                    className={`absolute inset-0 h-full w-full bg-background object-contain transition-opacity duration-200 ${
                      !selectMode && "group-hover:scale-105"
                    } ${hover.active === slot ? "z-10" : ""} ${
                      visible ? "opacity-100" : "opacity-0"
                    }`}
                  />
                ) : (
                  <div key={i} className="absolute inset-0" />
                );
              })}
            {imageUrls.length > 1 &&
              hover.active !== null &&
              !selectMode && (
                <div className="absolute bottom-0 left-0 right-0 z-20 flex h-1 gap-px bg-black/40">
                  {imageUrls.map((_, i) => (
                    <div
                      key={i}
                      className={`flex-1 transition-all duration-150 ${
                        hover.active === i ? "bg-white" : "bg-white/20"
                      }`}
                    />
                  ))}
                </div>
              )}
          </>
        ) : settled && imageIds.length === 0 ? (
          <div className="flex h-full items-center justify-center text-muted-foreground/30">
            <ImageIcon className="h-8 w-8" />
          </div>
        ) : (
          <div className="flex h-full items-center justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted/40 border-t-primary/60" />
          </div>
        )}
        {imageCount > 0 && (
          <span className="absolute bottom-1.5 right-1.5 z-20 rounded-md bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
            {imageCount}
          </span>
        )}
        {/* Checkbox overlay in select mode */}
        {selectMode && (
          <div
            className={`absolute left-2 top-2 flex h-6 w-6 items-center justify-center rounded-md border-2 transition-colors ${
              selected
                ? "border-primary bg-primary text-primary-foreground"
                : "border-white/70 bg-black/40 text-transparent"
            }`}
          >
            <Check className="h-4 w-4" />
          </div>
        )}
        {/* Like button (top-left) — shown only when logged in and not in
            select mode. stopPropagation+preventDefault so the card's <Link>
            navigation doesn't fire when toggling the like. */}
        {onToggleLike && !selectMode && (
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onToggleLike(thread.id);
            }}
            title={liked ? "Убрать лайк" : "Лайкнуть"}
            className="absolute left-2 top-2 z-10 flex h-7 w-7 items-center justify-center rounded-full bg-black/50 text-white backdrop-blur-sm transition hover:bg-black/70"
          >
            <Heart
              className={`h-4 w-4 ${liked ? "fill-red-500 text-red-500" : ""}`}
            />
          </button>
        )}
        {/* Download button (top-right) — adds the thread to the queue. */}
        {onDownload && !selectMode && (
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onDownload(thread.id);
            }}
            title="Добавить в очередь загрузки"
            className="absolute right-2 top-2 z-10 flex h-7 w-7 items-center justify-center rounded-full bg-black/50 text-white backdrop-blur-sm transition hover:bg-black/70"
          >
            <Download className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-2.5">
        {thread.prefix && (
          <span className="inline-block w-fit rounded bg-primary/20 px-1.5 py-0.5 text-[10px] font-medium text-primary">
            {thread.prefix}
          </span>
        )}
        <h3 className="line-clamp-2 text-xs font-medium leading-snug" title={thread.title}>
          {thread.title}
        </h3>
        <div className="mt-auto flex items-center gap-3 pt-1 text-[10px] text-muted-foreground">
          <span className="flex items-center gap-0.5">
            <MessageSquare className="h-2.5 w-2.5" /> {thread.replies}
          </span>
          <span className="flex items-center gap-0.5">
            <Eye className="h-2.5 w-2.5" /> {thread.views.toLocaleString()}
          </span>
          {thread.posted_at && (
            <span
              className="flex min-w-0 items-center gap-0.5 truncate"
              title={thread.posted_at}
            >
              <Clock className="h-2.5 w-2.5 shrink-0" />
              <span className="truncate">{thread.posted_at}</span>
            </span>
          )}
        </div>
      </div>
    </>
  );

  if (selectMode) {
    return (
      <div
        className={cardClasses}
        onClick={() => onToggleSelect(thread.id)}
        role="button"
        tabIndex={0}
      >
        {cardContent}
      </div>
    );
  }

  return (
    <Link
      to={`/thread/${thread.id}?from=${forumId}${page > 1 ? `&page=${page}` : ""}`}
      className={cardClasses}
    >
      {cardContent}
    </Link>
  );
}

export function ThreadRow({
  thread,
  cover,
  selectMode,
  selected,
  onToggleSelect,
  liked,
  onToggleLike,
  forumId,
  page,
}: {
  thread: ThreadSummary;
  cover?: CoverOut | null;
  selectMode: boolean;
  selected: boolean;
  onToggleSelect: (id: number) => void;
  liked?: boolean;
  onToggleLike?: (id: number) => void;
  forumId: number;
  page: number;
}) {
  const imageIds = cover?.image_ids ?? thread.image_ids ?? [];
  // Cards render at ~100-130px; thumb (150-250px) is plenty and avoids the
  // backend path that downloads the FULL image (5-20MB) just to resize.
  const imageUrls = imageIds.slice(0, 5).map((id) => api.imageUrl(id, "thumb"));
  const coverUrl = imageUrls[0] || "";
  const previewUrls = imageUrls.slice(1);
  const imageCount = thread.image_count || cover?.image_count || 0;
  const settled = cover !== undefined;
  const showImg = coverUrl.length > 0;

  const rowContent = (
    <>
      {/* Cover (left) */}
      <div className="relative h-28 w-24 shrink-0 overflow-hidden rounded-l-xl bg-muted/20 sm:h-36 sm:w-32">
        {showImg ? (
          <RetryImage
            src={coverUrl}
            alt={thread.title}
            loading="eager"
            decoding="async"
            className="h-full w-full object-cover"
          />
        ) : settled ? (
          <div className="flex h-full items-center justify-center text-muted-foreground/30">
            <ImageIcon className="h-7 w-7" />
          </div>
        ) : (
          <div className="flex h-full items-center justify-center">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-muted/40 border-t-primary/60" />
          </div>
        )}
        {imageCount > 0 && (
          <span className="absolute right-1 top-1 rounded-md bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
            {imageCount}
          </span>
        )}
        {selectMode && (
          <div
            className={`absolute left-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-md border-2 transition-colors ${
              selected
                ? "border-primary bg-primary text-primary-foreground"
                : "border-white/70 bg-black/40 text-transparent"
            }`}
          >
            <Check className="h-4 w-4" />
          </div>
        )}
        {onToggleLike && !selectMode && (
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onToggleLike(thread.id);
            }}
            title={liked ? "Убрать лайк" : "Лайкнуть"}
            className="absolute left-1.5 top-1.5 z-10 flex h-6 w-6 items-center justify-center rounded-full bg-black/50 text-white backdrop-blur-sm transition hover:bg-black/70"
          >
            <Heart
              className={`h-3.5 w-3.5 ${liked ? "fill-red-500 text-red-500" : ""}`}
            />
          </button>
        )}
      </div>

      {/* Title + metadata (middle) */}
      <div className="flex min-w-0 flex-1 flex-col gap-1 p-3">
        {thread.prefix && (
          <span className="inline-block w-fit rounded bg-primary/20 px-1.5 py-0.5 text-[10px] font-medium text-primary">
            {thread.prefix}
          </span>
        )}
        <h3
          className="line-clamp-2 text-sm font-medium leading-snug"
          title={thread.title}
        >
          {thread.title}
        </h3>
        <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          {thread.author && <span className="truncate">{thread.author}</span>}
          <span className="flex items-center gap-0.5">
            <MessageSquare className="h-3 w-3" /> {thread.replies}
          </span>
          <span className="flex items-center gap-0.5">
            <Eye className="h-3 w-3" /> {thread.views.toLocaleString()}
          </span>
          {thread.posted_at && (
            <span
              className="flex min-w-0 items-center gap-0.5 truncate"
              title={thread.posted_at}
            >
              <Clock className="h-3 w-3 shrink-0" />
              <span className="truncate">{thread.posted_at}</span>
            </span>
          )}
        </div>
      </div>

      {/* First 5 photos (right), spaced — no carousel. Hidden on small
          screens; 3 photos on md, full 5 on lg+ so text never gets crowded. */}
      <div className="ml-auto hidden shrink-0 items-center gap-1.5 p-2 pr-3 md:flex">
        {previewUrls.length > 0
          ? previewUrls.map((url, i) => (
              <RetryImage
                key={i}
                src={url}
                alt=""
                loading="lazy"
                decoding="async"
                className={`h-20 w-20 shrink-0 rounded-md object-cover sm:h-24 sm:w-24 lg:h-32 lg:w-32 ${
                  i >= 3 ? "hidden lg:block" : ""
                }`}
              />
            ))
          : (
            <span className="text-xs text-muted-foreground/40">—</span>
          )}
      </div>
    </>
  );

  const rowClasses = `group relative flex overflow-hidden rounded-xl border bg-card transition ${
    selectMode
      ? selected
        ? "border-primary ring-2 ring-primary/40"
        : "border-border"
      : "border-border hover:border-primary/50 hover:shadow-lg hover:shadow-primary/5"
  }`;

  if (selectMode) {
    return (
      <div
        className={rowClasses}
        onClick={() => onToggleSelect(thread.id)}
        role="button"
        tabIndex={0}
      >
        {rowContent}
      </div>
    );
  }

  return (
    <Link
      to={`/thread/${thread.id}?from=${forumId}${page > 1 ? `&page=${page}` : ""}`}
      className={rowClasses}
    >
      {rowContent}
    </Link>
  );
}
