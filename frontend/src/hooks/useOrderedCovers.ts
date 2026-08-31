import { useEffect, useState } from "react";
import { api, CoverOut, ThreadSummary } from "../api/client";

interface Covers {
  /** Cover data per thread (null = fetch failed). */
  coverById: Map<number, CoverOut | null>;
}

/**
 * Cover metadata loader — fires ALL cover requests in parallel.
 *
 * Forum thread *listings* (forumdisplay) carry no image ids, so each thread's
 * cover must be fetched on demand from `/api/thread/{id}/cover`. With a small
 * page size this hook simply requests every pending cover concurrently and
 * patches them into the map as a batch. No windowing, no ordering gate.
 *
 * Image BYTES are left entirely to the browser: cards render a plain
 * `<img loading="eager">` as soon as their cover data is available, and the
 * browser downloads them concurrently (its per-host connection limit paces
 * them naturally). This mirrors how the forum itself loads images.
 *
 * Threads already carrying `image_ids` (cached server-side) need no request.
 */
export function useOrderedCovers(threads: ThreadSummary[]): Covers {
  const [coverById, setCovers] = useState<Map<number, CoverOut | null>>(
    () => new Map(),
  );

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    // Seed with threads that already have server-cached image ids (no fetch).
    const instant = new Map<number, CoverOut | null>();
    for (const t of threads) {
      if (t.image_ids.length > 0) {
        instant.set(t.id, {
          thread_id: t.id,
          title: t.title,
          cover_url: t.cover_url,
          preview_urls: t.preview_urls,
          image_ids: t.image_ids,
          image_count: t.image_count,
        });
      }
    }
    setCovers(instant);

    const need = threads.filter((t) => t.image_ids.length === 0);
    if (need.length === 0) return;

    // Resolve every pending cover with a single batch request instead of one
    // request per thread. Each per-thread cover was queued behind the 2 req/s
    // forum rate limiter and consumed one of the browser's 6 per-host
    // connections, so a page of ~30 cards could stall the tab for seconds.
    api
      .covers(need.map((t) => t.id), controller.signal)
      .then((res) => {
        if (cancelled) return;
        setCovers((prev) => {
          const next = new Map(prev);
          for (const t of need) {
            const c = res.covers[String(t.id)] ?? null;
            next.set(t.id, c);
          }
          return next;
        });
      })
      .catch(() => {
        // Batch failed (or aborted by a page change) — mark each pending
        // thread as settled-null so its spinner stops and it renders the
        // fallback, instead of hanging.
        if (cancelled) return;
        setCovers((prev) => {
          const next = new Map(prev);
          for (const t of need) next.set(t.id, null);
          return next;
        });
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [threads]);

  return { coverById };
}
