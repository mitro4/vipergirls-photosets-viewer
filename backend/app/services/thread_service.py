"""Thread listing, detail, and cover service with SQLite caching.

Thread listings are cached per (forum_id, page) with a configurable TTL.
Thread details and covers are fetched via viper.click and cached permanently
in the threads+images tables. A single vr.php call populates cover, previews,
image_count, and the full image list.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta

from ..db import get_db
from ..forums import get_node, is_known_forum
from ..models import (
    CoverOut,
    ImageOut,
    PostOut,
    PostPageOut,
    ThreadDetailOut,
    ThreadListOut,
    ThreadSummary,
)
from ..scrapers.forumdisplay import fetch_forum_page
from ..scrapers.viper_click import lookup_thread
from .settings_service import get_setting

log = logging.getLogger("viper.threads")

LISTING_TTL = timedelta(minutes=30)

# Deduplicate concurrent vr.php fetches for the same thread_id.
_inflight: dict[int, asyncio.Task] = {}

# Background task registry — keeps fire-and-forget prefetch/warm tasks
# referenced so asyncio doesn't GC them mid-flight (and warn about "future
# exception was never retrieved").
_bg_tasks: set[asyncio.Task] = set()


def fire_background_task(coro) -> asyncio.Task:
    """Schedule a best-effort background task. Errors are logged, not raised."""
    task = asyncio.create_task(coro)

    def _done(t: asyncio.Task) -> None:
        _bg_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            log.warning("Background task failed: %s", exc)

    task.add_done_callback(_done)
    _bg_tasks.add(task)
    return task

# IMPORTANT-prefixed threads are section rules/guidelines (no images) and are
# hidden from the grid. Anchored at the start to avoid matching ordinary
# photo-set titles/prefixes that merely contain the word "important".
_IMPORTANT_PREFIX_RE = re.compile(r"^\*?\s*important\b", re.I)
_IMPORTANT_TITLE_RE = re.compile(r"^\s*\[?\*?\s*IMPORTANT\b", re.I)


def _is_non_photoset(t: ThreadSummary) -> bool:
    """True for announcement/rules threads and confirmed-empty threads.

    Hidden when it carries an IMPORTANT marker (prefix, or a leading marker in
    the title), or when its metadata has already been fetched via viper.click
    and it contains no images at all. Threads never fetched (has_previews
    False) are kept — their image count is unknown until a cover request
    resolves it client-side (the cover fetch caches image_count in the DB).
    """
    if t.prefix and _IMPORTANT_PREFIX_RE.search(t.prefix):
        return True
    if t.title and _IMPORTANT_TITLE_RE.search(t.title):
        return True
    return t.has_previews and t.image_count == 0


async def list_threads(
    forum_id: int,
    page: int,
    *,
    sort: str = "default",
    force_refresh: bool = False,
) -> ThreadListOut:
    """Return a page of thread listings for a forum, using cache when fresh.

    Only the default (natural) sort is cached: the forum_pages cache is keyed
    by (forum_id, page), so non-default sorts bypass it to avoid returning
    incorrectly ordered data.
    """
    if not is_known_forum(forum_id):
        raise ValueError(f"Unknown forum_id {forum_id}")

    page = max(1, page)
    cacheable = sort == "default"

    threads: list[ThreadSummary] | None = None
    total_pages = 1

    # --- 1. Cache read (short-lived conn) ---
    if cacheable and not force_refresh:
        db = await get_db()
        try:
            row = await (
                await db.execute(
                    "SELECT threads_json, total_pages, total_threads, fetched_at "
                    "FROM forum_pages WHERE forum_id=? AND page=?",
                    (forum_id, page),
                )
            ).fetchone()
            if row:
                age = datetime.utcnow() - datetime.fromisoformat(row["fetched_at"])
                if age < LISTING_TTL:
                    threads = [
                        ThreadSummary(**t) for t in json.loads(row["threads_json"])
                    ]
                    total_pages = row["total_pages"]
        finally:
            await db.close()

    # --- 2. Scrape (no DB conn held: fetch_forum_page can take seconds behind
    # the rate limiter; a pooled connection must not be pinned for that) ---
    if threads is None:
        log.info("Scraping forum %s page %d sort=%s", forum_id, page, sort)
        forum_page = await fetch_forum_page(forum_id, page, sort=sort)
        threads = [
            ThreadSummary(
                id=t.thread_id,
                title=t.title,
                forum_id=t.forum_id,
                prefix=t.prefix,
                author=t.author,
                posted_at=t.posted_at,
                replies=t.replies,
                views=t.views,
            )
            for t in forum_page.threads
        ]
        total_pages = forum_page.total_pages
        now = datetime.utcnow().isoformat()

        db = await get_db()
        try:
            if cacheable:
                threads_json = json.dumps([t.model_dump() for t in threads])
                await db.execute(
                    "INSERT OR REPLACE INTO forum_pages "
                    "(forum_id, page, threads_json, total_pages, total_threads, fetched_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (forum_id, page, threads_json, total_pages,
                     forum_page.total_threads, now),
                )
            # Batch-insert all thread rows in one statement instead of one
            # INSERT per thread (a page can hold dozens).
            await db.executemany(
                "INSERT OR IGNORE INTO threads (id, title, forum_id, prefix, author, "
                "posted_at, replies, views, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (t.id, t.title, t.forum_id, t.prefix, t.author, t.posted_at,
                     t.replies, t.views, now)
                    for t in threads
                ],
            )
            await db.commit()
        finally:
            await db.close()

    # --- 3. Enrich with cover data from the threads table ---
    db = await get_db()
    try:
        await _enrich_covers(db, threads)
    finally:
        await db.close()

    # Drop non-photoset threads: announcement/rules carry an IMPORTANT
    # marker, and any thread already confirmed (via viper.click metadata)
    # to contain zero images is not a photo set. Threads never inspected
    # (has_previews False) are kept — their image count is unknown until
    # their cover is fetched (which happens client-side on view).
    threads = [t for t in threads if not _is_non_photoset(t)]

    return ThreadListOut(
        forum_id=forum_id, page=page, total_pages=total_pages, threads=threads
    )


async def get_thread_cover(
    thread_id: int, *, force_refresh: bool = False
) -> CoverOut:
    """Return cover + preview URLs, fetching via viper.click if not cached."""
    db = await get_db()
    try:
        if not force_refresh:
            row = await (
                await db.execute(
                    "SELECT title, cover_url, preview_urls_json, image_count, meta_fetched "
                    "FROM threads WHERE id=?",
                    (thread_id,),
                )
            ).fetchone()
            if row and row["meta_fetched"]:
                img_rows = await (
                    await db.execute(
                        "SELECT id FROM images WHERE thread_id=? AND idx < 5 ORDER BY idx",
                        (thread_id,),
                    )
                ).fetchall()
                return CoverOut(
                    thread_id=thread_id,
                    title=row["title"],
                    cover_url=row["cover_url"],
                    preview_urls=json.loads(row["preview_urls_json"] or "[]"),
                    image_ids=[r["id"] for r in img_rows],
                    image_count=row["image_count"],
                )
    finally:
        await db.close()

    await _fetch_and_cache_thread(thread_id)

    db = await get_db()
    try:
        row = await (
            await db.execute(
                "SELECT title, cover_url, preview_urls_json, image_count "
                "FROM threads WHERE id=?",
                (thread_id,),
            )
        ).fetchone()
        if row:
            img_rows = await (
                await db.execute(
                    "SELECT id FROM images WHERE thread_id=? AND idx < 5 ORDER BY idx",
                    (thread_id,),
                )
            ).fetchall()
            return CoverOut(
                thread_id=thread_id,
                title=row["title"],
                cover_url=row["cover_url"],
                preview_urls=json.loads(row["preview_urls_json"] or "[]"),
                image_ids=[r["id"] for r in img_rows],
                image_count=row["image_count"],
            )
    finally:
        await db.close()

    raise RuntimeError(f"Failed to load cover for thread {thread_id}")


async def get_thread_covers_batch(thread_ids: list[int]) -> dict[int, CoverOut | None]:
    """Resolve covers for many threads in one call.

    Replaces the frontend firing N parallel ``GET /api/thread/{id}/cover``
    requests (each queued behind the 2 req/s forum rate limiter, and each
    consuming one of the browser's 6 per-host connections).  Per-thread
    failures are isolated — a failed id maps to ``None`` so the caller can mark
    it settled instead of leaving a spinner forever.
    """
    # Bound concurrency: vr.php calls are themselves rate-limited, but a
    # semaphore avoids spinning up a coroutine per id.
    conc = await get_setting("thread_concurrency")
    sem = asyncio.Semaphore(conc if isinstance(conc, int) and conc > 0 else 2)
    results: dict[int, CoverOut | None] = {}

    async def one(tid: int) -> None:
        async with sem:
            try:
                results[tid] = await get_thread_cover(tid)
            except Exception as exc:
                log.warning("Batch cover lookup failed for %d: %s", tid, exc)
                results[tid] = None

    await asyncio.gather(*[one(tid) for tid in thread_ids])

    # Fire-and-forget: resolve direct image URLs for the covers we just built so
    # the first /api/image request skips the interstitial-resolution RTT. Best
    # effort, bounded — runs entirely after the response data is ready.
    all_image_ids = [
        img_id
        for c in results.values()
        if c and c.image_ids
        for img_id in c.image_ids
    ]
    if all_image_ids:
        from .image_proxy import prefetch_resolution
        fire_background_task(prefetch_resolution(all_image_ids))
    return results


async def get_thread_detail(
    thread_id: int, *, force_refresh: bool = False
) -> ThreadDetailOut:
    """Return full thread image list, cached in DB after first fetch."""
    db = await get_db()
    try:
        if not force_refresh:
            row = await (
                await db.execute(
                    "SELECT id, title, forum_id, image_count, meta_fetched "
                    "FROM threads WHERE id=?",
                    (thread_id,),
                )
            ).fetchone()
            if row and row["meta_fetched"]:
                img_rows = await (
                    await db.execute(
                        "SELECT id, idx, post_id, main_url, thumb_url, host "
                        "FROM images WHERE thread_id=? ORDER BY idx",
                        (thread_id,),
                    )
                ).fetchall()
                images = [
                    ImageOut(
                        id=r["id"], idx=r["idx"], post_id=r["post_id"],
                        main_url=r["main_url"], thumb_url=r["thumb_url"],
                        host=r["host"],
                    )
                    for r in img_rows
                ]
                return ThreadDetailOut(
                    id=row["id"], title=row["title"], forum_id=row["forum_id"],
                    forum_title=_forum_title(row["forum_id"]),
                    image_count=row["image_count"],
                    post_count=await _count_posts(db, thread_id), images=images,
                )
    finally:
        await db.close()

    await _fetch_and_cache_thread(thread_id)

    db = await get_db()
    try:
        row = await (
            await db.execute(
                "SELECT id, title, forum_id, image_count FROM threads WHERE id=?",
                (thread_id,),
            )
        ).fetchone()
        if not row:
            raise RuntimeError(f"Thread {thread_id} vanished after fetch")
        img_rows = await (
            await db.execute(
                "SELECT id, idx, post_id, main_url, thumb_url, host FROM images "
                "WHERE thread_id=? ORDER BY idx",
                (thread_id,),
            )
        ).fetchall()
        images = [
            ImageOut(
                id=r["id"], idx=r["idx"], post_id=r["post_id"],
                main_url=r["main_url"], thumb_url=r["thumb_url"],
                host=r["host"],
            )
            for r in img_rows
        ]
        return ThreadDetailOut(
            id=row["id"], title=row["title"], forum_id=row["forum_id"],
            forum_title=_forum_title(row["forum_id"]),
            image_count=row["image_count"],
            post_count=await _count_posts(db, thread_id), images=images,
        )
    finally:
        await db.close()


async def get_thread_posts(
    thread_id: int, page: int, *, per_page: int = 5, force_refresh: bool = False
) -> PostPageOut:
    """Return one page of posts (each with its images) for a thread.

    Posts are derived by grouping the cached images by post_id, in order of
    first appearance. Guarantees a fresh fetch if the thread metadata is missing.
    """
    db = await get_db()
    try:
        row = await (
            await db.execute(
                "SELECT id, title FROM threads WHERE id=?", (thread_id,)
            )
        ).fetchone()
        if not row or not row["title"]:
            await db.close()
            await _fetch_and_cache_thread(thread_id)
            db = await get_db()
    finally:
        pass

    try:
        # Distinct post_ids ordered by their earliest image index.
        post_rows = await (
            await db.execute(
                "SELECT post_id FROM images WHERE thread_id=? "
                "GROUP BY post_id ORDER BY MIN(idx)",
                (thread_id,),
            )
        ).fetchall()
        post_ids = [r["post_id"] for r in post_rows]
        total_pages = max(1, (len(post_ids) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        page_post_ids = post_ids[start : start + per_page]

        posts: list[PostOut] = []
        for i, pid in enumerate(page_post_ids):
            img_rows = await (
                await db.execute(
                    "SELECT id, idx, post_id, main_url, thumb_url, host "
                    "FROM images WHERE thread_id=? AND post_id=? ORDER BY idx",
                    (thread_id, pid),
                )
            ).fetchall()
            images = [
                ImageOut(
                    id=r["id"], idx=r["idx"], post_id=r["post_id"],
                    main_url=r["main_url"], thumb_url=r["thumb_url"],
                    host=r["host"],
                )
                for r in img_rows
            ]
            posts.append(
                PostOut(
                    post_id=pid,
                    index=start + i + 1,
                    image_count=len(images),
                    images=images,
                )
            )
        return PostPageOut(
            thread_id=thread_id,
            page=page,
            total_pages=total_pages,
            post_count=len(post_ids),
            posts=posts,
        )
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _count_posts(db, thread_id: int) -> int:
    row = await (
        await db.execute(
            "SELECT COUNT(DISTINCT post_id) AS c FROM images WHERE thread_id=?",
            (thread_id,),
        )
    ).fetchone()
    return row["c"] if row else 0


def _forum_title(forum_id: int) -> str:
    """Best-effort forum name for a thread's forum_id (from the static tree)."""
    node = get_node(forum_id)
    return node.title if node else ""


async def _enrich_covers(db, threads: list[ThreadSummary]) -> None:
    """Populate cover_url, image_count, has_previews, image_ids from the DB."""
    if not threads:
        return
    ids = [t.id for t in threads]
    placeholders = ",".join("?" * len(ids))
    rows = await (
        await db.execute(
            f"SELECT id, cover_url, preview_urls_json, image_count, meta_fetched "
            f"FROM threads WHERE id IN ({placeholders})",
            ids,
        )
    ).fetchall()
    cover_map = {r["id"]: r for r in rows}

    # First-5 image row IDs per thread (for high-quality proxy URLs).
    img_rows = await (
        await db.execute(
            f"SELECT thread_id, id FROM images "
            f"WHERE thread_id IN ({placeholders}) AND idx < 5 "
            f"ORDER BY thread_id, idx",
            ids,
        )
    ).fetchall()
    img_map: dict[int, list[int]] = {}
    for r in img_rows:
        img_map.setdefault(r["thread_id"], []).append(r["id"])

    for t in threads:
        if t.id in cover_map:
            r = cover_map[t.id]
            t.cover_url = r["cover_url"] or ""
            t.preview_urls = json.loads(r["preview_urls_json"] or "[]")
            t.image_count = r["image_count"] or 0
            t.has_previews = bool(r["meta_fetched"])
        t.image_ids = img_map.get(t.id, [])


async def _fetch_and_cache_thread(thread_id: int) -> None:
    """Fetch thread via viper.click and cache cover + previews + all images.

    Deduplicates concurrent calls for the same thread_id.
    Raises RuntimeError on viper.click errors.
    """
    existing_task = _inflight.get(thread_id)
    if existing_task is not None:
        await asyncio.shield(existing_task)
        return

    task = asyncio.ensure_future(_do_fetch_and_cache(thread_id))
    _inflight[thread_id] = task
    try:
        await asyncio.shield(task)
    finally:
        _inflight.pop(thread_id, None)


async def _do_fetch_and_cache(thread_id: int) -> None:
    log.info("Fetching thread %d via viper.click", thread_id)
    result = await lookup_thread(thread_id)
    if result.error:
        raise RuntimeError(f"viper.click error: {result.error}")

    all_images = result.all_images()
    cover_url = all_images[0].thumb_url if all_images else ""
    preview_urls = [img.thumb_url for img in all_images[:5]]
    now = datetime.utcnow().isoformat()

    db = await get_db()
    try:
        # Preserve listing metadata if the thread row was already populated.
        existing = await (
            await db.execute(
                "SELECT forum_id, prefix, author, posted_at, replies, views "
                "FROM threads WHERE id=?",
                (thread_id,),
            )
        ).fetchone()
        if existing:
            forum_id = existing["forum_id"]
            prefix = existing["prefix"]
            author = existing["author"]
            posted_at = existing["posted_at"]
            replies = existing["replies"]
            views = existing["views"]
        else:
            forum_id = 0
            prefix = author = posted_at = ""
            replies = views = 0

        await db.execute(
            "INSERT OR REPLACE INTO threads (id, title, forum_id, prefix, author, "
            "posted_at, replies, views, cover_url, preview_urls_json, image_count, "
            "meta_fetched, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (thread_id, result.title, forum_id, prefix, author, posted_at,
             replies, views, cover_url, json.dumps(preview_urls),
             len(all_images), 1, now),
        )
        await db.execute("DELETE FROM images WHERE thread_id=?", (thread_id,))

        # Batch-insert every image row in one statement. A set often holds
        # 100+ images; the previous one-INSERT-per-image loop dominated the
        # fetch-and-cache latency.
        rows: list[tuple] = []
        idx = 0
        for post in result.posts:
            for img in post.images:
                host = _extract_host(img.main_url)
                rows.append(
                    (thread_id, idx, post.post_id, img.main_url, img.thumb_url,
                     host, "pending", now)
                )
                idx += 1
        if rows:
            await db.executemany(
                "INSERT INTO images (thread_id, idx, post_id, main_url, thumb_url, "
                "host, status, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
                rows,
            )
        await db.commit()
        log.info(
            "Cached thread %d: %d images, cover=%s",
            thread_id, len(all_images), cover_url[:60],
        )
    finally:
        await db.close()


def _extract_host(url: str) -> str:
    from ..hosts.registry import identify_host

    return identify_host(url)
