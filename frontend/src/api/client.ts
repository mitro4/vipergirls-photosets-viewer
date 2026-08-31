export interface CategoryOut {
  forum_id: number;
  title: string;
  slug: string;
  parent_id: number | null;
  group: string;
  thread_count: number;
  children: CategoryOut[];
}

export interface CategoryGroupOut {
  name: string;
  forum_id: number | null;
  categories: CategoryOut[];
}

export interface ThreadSummary {
  id: number;
  title: string;
  forum_id: number;
  prefix: string;
  author: string;
  posted_at: string;
  replies: number;
  views: number;
  cover_url: string;
  preview_urls: string[];
  image_ids: number[];
  image_count: number;
  has_previews: boolean;
}

export interface ThreadListOut {
  forum_id: number;
  page: number;
  total_pages: number;
  threads: ThreadSummary[];
}

export interface SearchResultsPage {
  query: string;
  mode: string;
  page: number;
  total_pages: number;
  results: SearchResult[];
}

export interface SearchResult extends ThreadSummary {
  post_id: number;
  mode: string;
}

export interface ImageOut {
  id: number;
  idx: number;
  post_id: number;
  main_url: string;
  thumb_url: string;
  host: string;
}

export interface ThreadDetailOut {
  id: number;
  title: string;
  forum_id: number;
  forum_title: string;
  author: string;
  image_count: number;
  post_count: number;
  images: ImageOut[];
}

export interface CoverOut {
  thread_id: number;
  title: string;
  cover_url: string;
  preview_urls: string[];
  image_ids: number[];
  image_count: number;
}

export interface AuthStatus {
  logged_in: boolean;
  username: string;
}

export interface StatsOut {
  threads: number;
  images: number;
  cache_size_mb: number;
  cache_limit_gb: number;
}

export interface AppSettings {
  order_images: boolean;
  download_concurrency: number;
  thread_concurrency: number;
  download_timeout: number;
  max_retries: number;
  forum_proxy: string;
  proxy_enabled: boolean;
  proxy_url: string;
  proxy_username: string;
  proxy_password: string;
  auto_download: boolean;
  auto_clear_completed: boolean;
  cache_limit_gb: number;
  available_domains: string[];
}

export interface ForumConfig {
  forum_url: string;
  click_url: string;
}

export interface LikedItem {
  thread_id: number;
  title: string;
  liked_at: string;
}

export interface LikedOut {
  items: LikedItem[];
}

export interface DownloadItem {
  thread_id: number;
  title: string;
  filename: string;
  downloaded_at: string;
}

export interface DownloadsOut {
  items: DownloadItem[];
  folder: string;
}

export interface QueueItem {
  thread_id: number;
  title: string;
  status: "queued" | "downloading" | "stopped" | "done" | "error";
  total: number;
  completed: number;
  failed: number;
  error: string;
  added_at: string;
}

export interface QueueOut {
  items: QueueItem[];
}

export interface LikeResult {
  liked: boolean;
  thread_id: number;
}

const BASE = import.meta.env.VITE_API_BASE ?? "";

// Images are served with `Cache-Control: … immutable, max-age=31536000`, so a
// plain reload never re-fetches them. Appending `_v=<token>` to image URLs
// forces the browser to treat them as fresh entries. The token lives in
// sessionStorage and is bumped by the "clear cache" action (which then
// reloads), so freshly-rendered <img> tags pick up the new URL.
let _IMG_CACHE_V = "";
try {
  _IMG_CACHE_V = sessionStorage.getItem("imgCacheV") ?? "";
} catch {
  // sessionStorage unavailable — cache busting disabled
}
const _bust = () => (_IMG_CACHE_V ? `&_v=${_IMG_CACHE_V}` : "");

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} — ${path}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  categories: () => http<CategoryGroupOut[]>("/api/categories"),
  config: () => http<ForumConfig>("/api/config"),
  threads: (
    forumId: number,
    page = 1,
    sort: "default" | "new" | "old" = "default",
    signal?: AbortSignal,
  ) =>
    http<ThreadListOut>(
      `/api/forums/${forumId}/threads?page=${page}&sort=${sort}`,
      signal ? { signal } : undefined,
    ),
  thread: (id: number) => http<ThreadDetailOut>(`/api/thread/${id}`),
  cover: (id: number) => http<CoverOut>(`/api/thread/${id}/cover`),
  /** Batch-resolve covers for many threads in a single request. */
  covers: (ids: number[], signal?: AbortSignal) =>
    http<{ covers: Record<string, CoverOut | null> }>(`/api/threads/covers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_ids: ids }),
      ...(signal ? { signal } : {}),
    }),
  /** Image URL via backend proxy. *medium* = server-resized ~800px (good for cards). */
  imageUrl: (imageId: number, size: "thumb" | "medium" | "full" = "full") =>
    `${BASE}/api/image/${imageId}?size=${size}${_bust()}`,
  /** Proxy an arbitrary image URL (thumbnails, covers). */
  proxyUrl: (url: string) =>
    `${BASE}/api/proxy?url=${encodeURIComponent(url)}${_bust()}`,
  /** ZIP download URL for an entire photoset. */
  downloadUrl: (threadId: number) =>
    `${BASE}/api/thread/${threadId}/download`,
  authStatus: () => http<AuthStatus>("/api/auth/status"),
  login: (username: string, password: string) =>
    http<AuthStatus>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }),
  logout: () =>
    http<AuthStatus>("/api/auth/logout", { method: "POST" }),
  search: (q: string, forums = "", mode: "threads" | "posts" = "threads", sort: "new" | "old" = "new", page = 1, signal?: AbortSignal) => {
    const params = new URLSearchParams({ q, mode, sort, page: String(page) });
    if (forums) params.set("forums", forums);
    return http<SearchResultsPage>(`/api/search?${params.toString()}`, signal ? { signal } : undefined);
  },
  stats: () => http<StatsOut>("/api/stats"),
  clearCache: () =>
    http<{ status: string }>("/api/cache/clear", { method: "POST" }),
  settings: () => http<AppSettings>("/api/settings"),
  updateSettings: (body: Partial<AppSettings>) =>
    http<AppSettings>("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  /** Like a thread (forum "post thanks" on its first post). Requires login. */
  likeThread: (threadId: number) =>
    http<LikeResult>(`/api/thread/${threadId}/like`, { method: "POST" }),
  /** Remove a like from a thread. */
  unlikeThread: (threadId: number) =>
    http<LikeResult>(`/api/thread/${threadId}/like`, { method: "DELETE" }),
  /** List threads the user has liked. */
  liked: () => http<LikedOut>("/api/liked"),
  /** List threads the user has downloaded + the download folder (desktop). */
  downloads: () => http<DownloadsOut>("/api/downloads"),
  /** Store the desktop download folder (reported by Electron at startup). */
  setDownloadsFolder: (folder: string) =>
    http<{ folder: string }>("/api/downloads/folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder }),
    }),
  /** Download queue (persistent; survives restart; stop/resume). */
  listQueue: () => http<QueueOut>("/api/download/queue"),
  addToQueue: (threadIds: number[]) =>
    http<QueueOut>("/api/download/queue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_ids: threadIds }),
    }),
  stopQueueItem: (threadId: number) =>
    http<{ ok: boolean }>(`/api/download/queue/${threadId}/stop`, {
      method: "POST",
    }),
  startQueueItem: (threadId: number) =>
    http<{ ok: boolean }>(`/api/download/queue/${threadId}/start`, {
      method: "POST",
    }),
  clearQueue: () =>
    http<{ ok: boolean }>("/api/download/queue", { method: "DELETE" }),
};

/**
 * Clear the image cache and bust browser-cached image responses.
 *
 * Because image responses are served immutable (1-year browser cache), a
 * normal reload won't drop them — so this:
 *   1. clears the server-side disk cache (`POST /api/cache/clear`),
 *   2. drops Cache Storage entries (defensive, for any service worker),
 *   3. bumps the in-memory cache-bust token so image URLs change.
 *
 * After calling this, invalidate any TanStack Query caches that hold image
 * URLs (e.g. covers) so components re-render with the new cache-bust token.
 * Does NOT reload the page — callers stay mounted.
 */
export async function clearImageCache(): Promise<void> {
  try {
    await api.clearCache();
  } catch {
    // best-effort — still bust the browser cache below
  }
  try {
    if ("caches" in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    }
  } catch {
    // ignore
  }
  bustImageCache();
}

/** Update the cache-bust token in-place + sessionStorage (no page reload). */
export function bustImageCache(): void {
  _IMG_CACHE_V = String(Date.now());
  try {
    sessionStorage.setItem("imgCacheV", _IMG_CACHE_V);
  } catch {
    // sessionStorage unavailable — in-memory token still works for this session
  }
}
