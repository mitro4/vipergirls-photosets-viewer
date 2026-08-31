"""Shared image-fetch pipeline used by the download queue.

Extracted from the removed legacy multi-job system (download_jobs.py):
resolve an image row to a direct URL (with DB/LRU write-through), download
it into the content-addressed disk cache with retries, and compute the
ZIP/member filename. The interactive path (image_proxy) shares the same
cache and the same ``download_concurrency`` semaphore budget.
"""
from __future__ import annotations

import asyncio
import logging

from ..db import get_db
from ..hosts.base import get_client, referer_for_host, resolve_to_direct
from ..hosts.registry import identify_host
from ..services.image_proxy import (
    _cache_dir,
    _cache_key,
    _get_proxy_semaphore,
    put_image_rows,
    set_resolved_url_cache,
)
from ..services.thread_service import get_thread_detail
from ..utils.path import ext_from_url, numbered_filename, ordered_filename

log = logging.getLogger("viper.fetcher")
CHUNK = 65536


async def get_thread_images(thread_id: int) -> list[dict]:
    """Return image rows for *thread_id*, ensuring metadata is cached."""
    await get_thread_detail(thread_id)
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, idx, main_url, thumb_url, host, resolved_url "
            "FROM images WHERE thread_id=? ORDER BY idx",
            (thread_id,),
        )
        rows = await cur.fetchall()
        await cur.close()
    finally:
        await db.close()
    put_image_rows(rows)  # warm the interactive path's row LRU
    return [dict(r) for r in rows]


async def thread_title(thread_id: int) -> str:
    db = await get_db()
    try:
        row = await (
            await db.execute("SELECT title FROM threads WHERE id=?", (thread_id,))
        ).fetchone()
        return row["title"] if row else f"thread_{thread_id}"
    finally:
        await db.close()


async def resolve_row(row: dict) -> str:
    """Resolve a direct URL for an image row, caching to DB."""
    if row["resolved_url"]:
        return row["resolved_url"]
    try:
        _, direct = await resolve_to_direct(row["main_url"], row["thumb_url"])
    except Exception as exc:
        log.warning("Resolve failed img %s: %s", row["id"], exc)
        direct = row["main_url"]
    if direct and direct != row["main_url"]:
        # Write-through the row LRU so interactive /api/image requests see
        # the freshly resolved URL without a DB hit.
        set_resolved_url_cache(row["id"], direct)
        try:
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE images SET resolved_url=? WHERE id=?",
                    (direct, row["id"]),
                )
                await db.commit()
            finally:
                await db.close()
        except Exception:
            pass
    return direct


async def download_with_retry(
    url: str, cache_path, referer: str, timeout: int, retries: int
) -> bool:
    """Download *url* to *cache_path*. Returns True on success."""
    client = await get_client()
    headers: dict[str, str] = {}
    if referer:
        headers["Referer"] = referer

    for attempt in range(retries + 1):
        resp = None
        try:
            req = client.build_request("GET", url, headers=headers or None)
            resp = await asyncio.wait_for(
                client.send(req, stream=True), timeout=timeout
            )
            if resp.status_code != 200:
                await resp.aclose()
                if attempt < retries:
                    await asyncio.sleep(0.5)
                    continue
                return False

            async def _save():
                with open(cache_path, "wb") as f:
                    async for chunk in resp.aiter_raw(CHUNK):
                        f.write(chunk)

            await asyncio.wait_for(_save(), timeout=timeout)
            await resp.aclose()
            return True
        except asyncio.CancelledError:
            # Cooperative stop: don't leave a half-written file behind (a
            # resume would mistake it for complete and serve corrupt bytes).
            if resp is not None:
                try:
                    await resp.aclose()
                except Exception:
                    pass
            cache_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            # resp is only assigned after client.send() returns; a timeout or
            # send error leaves it unbound, so guard before aclose().
            if resp is not None:
                try:
                    await resp.aclose()
                except Exception:
                    pass
            cache_path.unlink(missing_ok=True)
            if attempt < retries:
                log.debug("Retry %d/%d for %s: %s", attempt + 1, retries, url, exc)
                await asyncio.sleep(0.5 * (attempt + 1))
            else:
                log.warning("Download failed after %d attempts: %s — %s", retries + 1, url, exc)
                return False
    return False


async def process_image(
    row: dict, tid: int, folder: str,
    timeout: int, retries: int, order_images: bool,
) -> tuple[bool, str, str]:
    """Resolve + (if needed) download one image.

    Returns ``(ok, zip_path, cache_path)``. On success the file is on disk at
    *cache_path*; on failure no file is guaranteed to exist.
    """
    sem = await _get_proxy_semaphore()
    async with sem:
        direct = await resolve_row(row)
        host = identify_host(direct) or row["host"] or ""
        referer = referer_for_host(host)
        cache_path = _cache_dir() / _cache_key(direct)

        if order_images:
            fname = numbered_filename(row["idx"], ext_from_url(direct))
        else:
            tail = direct.rsplit("/", 1)[-1].split("?")[0] or f"img_{row['idx']}.jpg"
            fname = ordered_filename(row["idx"], tail)
        zip_path = f"{folder}/{fname}"

        if not cache_path.exists():
            ok = await download_with_retry(direct, cache_path, referer, timeout, retries)
            if not ok:
                return False, zip_path, str(cache_path)
        return True, zip_path, str(cache_path)
