"""Thread listing and detail endpoints.

GET /api/forums/{forum_id}/threads?page=N   — paginated thread listing
GET /api/thread/{thread_id}                  — full thread with all images
POST /api/threads/covers                     — batch-resolve covers for many threads
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..forums import is_known_forum
from ..services.thread_service import (
    get_thread_cover,
    get_thread_covers_batch,
    get_thread_detail,
    get_thread_posts,
    list_threads,
)

log = logging.getLogger("viper.api.threads")
router = APIRouter()


@router.get("/forums/{forum_id}/threads", response_model=dict)
async def get_forum_threads(
    forum_id: int,
    page: int = Query(1, ge=1),
    sort: str = Query("default", pattern="^(default|new|old)$"),
    refresh: bool = Query(False),
):
    if not is_known_forum(forum_id):
        raise HTTPException(status_code=404, detail=f"Unknown forum {forum_id}")
    try:
        result = await list_threads(forum_id, page, sort=sort, force_refresh=refresh)
    except RuntimeError as exc:
        log.warning("Forum scrape failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))
    return result.model_dump()


@router.get("/thread/{thread_id}/cover", response_model=dict)
async def get_thread_cover_ep(thread_id: int, refresh: bool = Query(False)):
    try:
        result = await get_thread_cover(thread_id, force_refresh=refresh)
    except RuntimeError as exc:
        log.warning("Cover lookup failed for %d: %s", thread_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))
    return result.model_dump()


class CoversRequest(BaseModel):
    thread_ids: list[int]


@router.post("/threads/covers", response_model=dict)
async def get_thread_covers_ep(body: CoversRequest):
    """Batch-resolve covers for many thread ids in a single request.

    Returns ``{"covers": {"<id>": <CoverOut|null>, ...}}``. Replaces the
    client fanning out one ``/api/thread/{id}/cover`` request per card, which
    exhausted the browser's connection pool and queued behind the forum rate
    limiter one-by-one.
    """
    ids = [i for i in body.thread_ids if i > 0][:200]  # sane cap
    covers = await get_thread_covers_batch(ids)
    return {"covers": {str(tid): (c.model_dump() if c else None) for tid, c in covers.items()}}


@router.get("/thread/{thread_id}", response_model=dict)
async def get_thread(thread_id: int, refresh: bool = Query(False)):
    try:
        result = await get_thread_detail(thread_id, force_refresh=refresh)
    except RuntimeError as exc:
        log.warning("Thread lookup failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))
    return result.model_dump()


@router.get("/thread/{thread_id}/posts", response_model=dict)
async def get_thread_posts_ep(
    thread_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(5, ge=1, le=50),
    refresh: bool = Query(False),
):
    try:
        result = await get_thread_posts(
            thread_id, page, per_page=per_page, force_refresh=refresh
        )
    except RuntimeError as exc:
        log.warning("Thread posts lookup failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))
    # Background-warm the medium tier for the first post's images so the grid
    # paints fast once the browser renders: the full is fetched once
    # (single-flighted) and the medium rendered ahead of the <img> requests.
    first_ids = (
        [img.id for img in result.posts[0].images if img.id]
        if result.posts
        else []
    )
    if first_ids:
        from ..services.image_proxy import prewarm_mediums
        from ..services.thread_service import fire_background_task
        fire_background_task(prewarm_mediums(first_ids, limit=6))
    return result.model_dump()
