"""Search and system statistics endpoints."""
from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..config import get_settings
from ..db import get_db
from ..models import SearchResult, SearchResultsPage
from ..scrapers.search import search_forum
from ..services.thread_service import _enrich_covers

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResultsPage)
async def search(
    q: str = Query("", min_length=0),
    forums: str = Query("", description="Comma-separated top-level category ids"),
    mode: str = Query("threads", pattern="^(threads|posts)$"),
    sort: str = Query("new", pattern="^(new|old)$", description="new=descending (newest first), old=ascending (oldest first)"),
    page: int = Query(1, ge=1),
) -> SearchResultsPage:
    """Live forum search.

    Searches the viper.to forum (vBulletin Advanced Search) for *q*. When
    *forums* lists categories/forums, results are scoped to those (and their
    sub-forums, including any *Archive* sub-forum). vBulletin cannot filter on
    every sidebar forum in one request, so the scope is fanned out across
    batches of leaf forums and the per-batch result streams are merged by date
    (see ``scrapers/search.py``); every result therefore comes from a sidebar
    forum. When *forums* is empty the search spans every section the app
    presents in the sidebar (its top-level categories and all descendants),
    excluding unrelated forums such as Community/Support.

    Returns a paginated envelope: ``results`` (this page) plus ``page`` and
    ``total_pages`` so the UI can drive its pager. ``total_pages`` is computed
    from the exact per-batch match counts (the batches are disjoint, so their
    counts sum to the merged total).

    Results are enriched with cached cover/preview data when the thread has
    been browsed before.
    """
    if len(q.strip()) < 2:
        return SearchResultsPage(
            query=q.strip(), mode=mode, page=page, total_pages=1, results=[]
        )

    if forums.strip():
        try:
            forum_ids = [int(x) for x in forums.split(",") if x.strip()]
        except ValueError:
            forum_ids = []
    else:
        forum_ids = []

    page_data = await search_forum(
        q.strip(), forum_ids, mode=mode, page=page,
        order="ascending" if sort == "old" else "descending",
    )

    results: list[SearchResult] = [
        SearchResult(
            id=item.thread_id,
            title=item.title,
            forum_id=item.forum_id,
            author=item.author,
            posted_at=item.posted_at,
            replies=item.replies,
            views=item.views,
            post_id=item.post_id,
            mode=page_data.mode,
        )
        for item in page_data.results
    ]

    db = await get_db()
    try:
        await _enrich_covers(db, results)
    finally:
        await db.close()

    return SearchResultsPage(
        query=page_data.query,
        mode=page_data.mode,
        page=page_data.page,
        total_pages=page_data.total_pages,
        results=results,
    )



class StatsOut(BaseModel):
    threads: int
    images: int
    cache_size_mb: float
    cache_limit_gb: float


def _dir_size(path: Path) -> float:
    """Return directory size in MB."""
    if not path.exists():
        return 0.0
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total / (1024 * 1024)


# rglob+stat over the whole image cache (gigabytes, thousands of files) is slow;
# /api/stats would otherwise re-walk it on every call. Cache the result for a
# short TTL — it's a rough gauge, never needs to be live.
_DIR_SIZE_TTL = 60  # seconds
_dir_size_cache: tuple[float, float] = (0.0, 0.0)  # (mb, fetched_at_mono)


def _cached_dir_size(path: Path) -> float:
    global _dir_size_cache
    now = time.monotonic()
    mb, fetched_at = _dir_size_cache
    if now - fetched_at < _DIR_SIZE_TTL:
        return mb
    mb = _dir_size(path)
    _dir_size_cache = (mb, now)
    return mb


@router.get("/stats", response_model=StatsOut)
async def stats() -> StatsOut:
    from ..services.settings_service import get_setting

    db = await get_db()
    cur = await db.execute("SELECT COUNT(*) FROM threads")
    thread_count = (await cur.fetchone())[0]
    await cur.close()
    cur = await db.execute("SELECT COUNT(*) FROM images")
    image_count = (await cur.fetchone())[0]
    await cur.close()
    await db.close()
    settings = get_settings()
    # rglob+stat walks gigabytes of files — must never run on the event loop.
    cache_mb = await asyncio.to_thread(_cached_dir_size, settings.cache_dir)
    # Effective trim limit from the runtime settings table (0 = unlimited).
    limit_gb = await get_setting("cache_limit_gb")
    return StatsOut(
        threads=thread_count,
        images=image_count,
        cache_size_mb=round(cache_mb, 1),
        cache_limit_gb=float(limit_gb),
    )


@router.post("/cache/clear")
async def clear_cache() -> dict:
    """Delete all cached image files (keeps DB metadata)."""
    global _dir_size_cache
    settings = get_settings()
    cache_dir = settings.cache_dir / "img"
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
    # The cache was just emptied — reset the cached size so the next /stats
    # doesn't report the pre-clear value for up to a minute.
    _dir_size_cache = (0.0, time.monotonic())
    db = await get_db()
    await db.execute("UPDATE images SET resolved_url = NULL")
    await db.commit()
    return {"status": "cleared"}
