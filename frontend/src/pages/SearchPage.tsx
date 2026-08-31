import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search as SearchIcon } from "lucide-react";
import { useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, CoverOut, SearchResult } from "../api/client";
import { ThreadCard, ThreadRow } from "./CategoryPage";
import Pagination from "../components/Pagination";
import { useLikes } from "../hooks/useLikes";
import { useWaveLoader } from "../hooks/useWaveLoader";
import { useOrderedCovers } from "../hooks/useOrderedCovers";
import { useViewMode } from "../hooks/useViewMode";

// Stable empty list (see CategoryPage for rationale).
const EMPTY_RESULTS: SearchResult[] = [];

export default function SearchPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const q = searchParams.get("q") ?? "";
  const forums = searchParams.get("forums") ?? "";
  const mode = (searchParams.get("mode") as "threads" | "posts") || "threads";
  const sort = (searchParams.get("sort") as "new" | "old") || "new";
  const page = Number(searchParams.get("page")) || 1;

  const [viewMode, setViewMode] = useViewMode();
  const { loggedIn, likedIds, toggleLike } = useLikes();
  const qc = useQueryClient();
  const addToQueueMut = useMutation({
    mutationFn: (ids: number[]) => api.addToQueue(ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });

  const { data, isLoading, error } = useQuery({
    queryKey: ["search", q, forums, mode, sort, page],
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      api.search(q, forums, mode, sort, page, signal),
    enabled: q.trim().length >= 2,
  });

  const results: SearchResult[] = data?.results ?? EMPTY_RESULTS;
  const totalPages: number = data?.total_pages ?? 1;
  const { coverById } = useOrderedCovers(results);
  const allCoversSettled =
    results.length > 0 && results.every((r) => coverById.has(r.id));
  const { step: waveStep, reportCardDone } = useWaveLoader(
    results.length,
    allCoversSettled,
  );

  const goToPage = useCallback(
    (next: number) => {
      const p = new URLSearchParams(searchParams);
      if (next <= 1) p.delete("page");
      else p.set("page", String(next));
      navigate(`/search?${p.toString()}`, { replace: true });
    },
    [navigate, searchParams],
  );

  if (q.trim().length < 2) {
    return (
      <div className="flex h-[70vh] flex-col items-center justify-center gap-3 text-muted-foreground">
        <SearchIcon className="h-8 w-8 opacity-40" />
        <p className="text-sm">Type a query (min. 2 characters) to search the forum.</p>
      </div>
    );
  }

  return (
    <div className="pb-24">
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <p className="text-sm text-muted-foreground">
            {isLoading ? (
              <span className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" /> Searching…
              </span>
            ) : (
              <>
                {results.length} result(s) on page {page}
                {totalPages > 1 && <span className="ml-1 opacity-60">of {totalPages}</span>}
                <span className="ml-1 opacity-60">
                  for “{q}”{mode === "posts" ? " (posts)" : ""}
                </span>
              </>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          {/* Sort order */}
          <select
            value={sort}
            onChange={(e) => {
              const p = new URLSearchParams(searchParams);
              p.set("sort", e.target.value);
              p.delete("page");
              navigate(`/search?${p.toString()}`, { replace: true });
            }}
            title="Sort order"
            className="rounded-lg border border-border bg-background px-2 py-1.5 text-sm hover:bg-accent/20"
          >
            <option value="new">Newest first</option>
            <option value="old">Oldest first</option>
          </select>
          {/* View mode toggle */}
          <div className="flex items-center rounded-lg border border-border p-0.5">
            <button
              onClick={() => setViewMode("grid")}
              title="Grid view"
              className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${
                viewMode === "grid"
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <svg className="h-4 w-4" viewBox="0 0 16 16" fill="currentColor">
                <rect x="1" y="1" width="6" height="6" rx="1" />
                <rect x="9" y="1" width="6" height="6" rx="1" />
                <rect x="1" y="9" width="6" height="6" rx="1" />
                <rect x="9" y="9" width="6" height="6" rx="1" />
              </svg>
            </button>
            <button
              onClick={() => setViewMode("list")}
              title="List view"
              className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${
                viewMode === "list"
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <svg className="h-4 w-4" viewBox="0 0 16 16" fill="currentColor">
                <rect x="1" y="2" width="14" height="3" rx="1" />
                <rect x="1" y="6.5" width="14" height="3" rx="1" />
                <rect x="1" y="11" width="14" height="3" rx="1" />
              </svg>
            </button>
          </div>
          <Pagination
            page={page}
            totalPages={totalPages}
            onChange={goToPage}
          />
        </div>
      </div>

      {error ? (
        <div className="flex h-[50vh] flex-col items-center justify-center text-sm text-muted-foreground">
          <p className="mb-1">Search failed.</p>
          <p className="text-xs opacity-60">{String(error)}</p>
        </div>
      ) : !isLoading && results.length === 0 ? (
        <div className="flex h-[50vh] items-center justify-center text-sm text-muted-foreground">
          No results for “{q}”.
        </div>
      ) : (
        viewMode === "list" ? (
          <div className="flex flex-col gap-3">
            {results.map((r) => (
              <ThreadRow
                key={`${r.id}-${r.post_id}`}
                thread={r}
                cover={coverById.get(r.id)}
                selectMode={false}
                selected={false}
                onToggleSelect={() => {}}
                liked={likedIds.has(r.id)}
                onToggleLike={loggedIn ? toggleLike : undefined}
                forumId={r.forum_id}
                page={page}
              />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4">
            {results.map((r, idx) => (
              <ThreadCard
                key={`${r.id}-${r.post_id}`}
                thread={r}
                cover={coverById.get(r.id) as CoverOut | null | undefined}
                selectMode={false}
                selected={false}
                onToggleSelect={() => {}}
                liked={likedIds.has(r.id)}
                onToggleLike={loggedIn ? toggleLike : undefined}
                onDownload={(id) => addToQueueMut.mutate([id])}
                forumId={r.forum_id}
                page={page}
                cardIdx={idx}
                waveStep={waveStep}
                reportCardDone={reportCardDone}
              />
            ))}
          </div>
        )
      )}

      <Pagination
        page={page}
        totalPages={totalPages}
        onChange={goToPage}
        className="pt-4"
      />
    </div>
  );
}
