"""Stream-zip download — produces a ZIP archive of a thread's full-size images.

Uses ``stream_zip.async_stream_zip`` for fully async streaming:
  1. Pre-resolve all image direct URLs in parallel (semaphore-limited,
     reusing cached ``resolved_url`` values from the DB).
  2. Lazily download each image inside an async generator member, caching
     to disk while yielding chunks to the ZIP encoder.

The client receives the first ZIP bytes as soon as the first image is
downloaded — no need to wait for all images.
"""
from __future__ import annotations

import asyncio
import datetime
import logging

from stream_zip import ZIP_64, async_stream_zip

from ..config import get_settings
from ..db import get_db
from ..hosts.base import get_client, referer_for_host, resolve_to_direct
from ..hosts.registry import identify_host
from ..services.image_proxy import _cache_dir, _cache_key
from ..services.settings_service import get_setting
from ..utils.path import ext_from_url, numbered_filename, ordered_filename

log = logging.getLogger("viper.zip")

CHUNK = 65536


async def _resolve_all(thread_id: int) -> list[dict]:
    """Resolve every image's direct URL in parallel.

    Returns a list of dicts with keys: filename, direct_url, referer,
    cache_path — ordered by image idx.
    """
    db = await get_db()
    try:
        rows = await (
            await db.execute(
                "SELECT id, idx, main_url, thumb_url, host, resolved_url "
                "FROM images WHERE thread_id=? ORDER BY idx",
                (thread_id,),
            )
        ).fetchall()
    finally:
        await db.close()

    if not rows:
        return []

    conc = await get_setting("download_concurrency")
    sem = asyncio.Semaphore(conc if isinstance(conc, int) and conc > 0 else 8)
    order_images = await get_setting("order_images")

    async def resolve_one(row) -> dict:
        async with sem:
            direct_url = row["resolved_url"] or ""
            if not direct_url:
                try:
                    _, direct_url = await resolve_to_direct(
                        row["main_url"], row["thumb_url"]
                    )
                except Exception as exc:
                    log.warning("Resolve failed image %s: %s", row["id"], exc)
                    direct_url = row["main_url"]

                if direct_url and direct_url != row["main_url"]:
                    try:
                        db = await get_db()
                        try:
                            await db.execute(
                                "UPDATE images SET resolved_url=? WHERE id=?",
                                (direct_url, row["id"]),
                            )
                            await db.commit()
                        finally:
                            await db.close()
                    except Exception:
                        pass

            host = identify_host(direct_url) or row["host"] or ""
            tail = (
                direct_url.rsplit("/", 1)[-1].split("?")[0].split("#")[0]
                or f"image_{row['idx']}.jpg"
            )
            if order_images:
                filename = numbered_filename(row["idx"], ext_from_url(direct_url))
            else:
                filename = ordered_filename(row["idx"], tail)
            return {
                "idx": row["idx"],
                "filename": filename,
                "direct_url": direct_url,
                "referer": referer_for_host(host),
                "cache_path": _cache_dir() / _cache_key(direct_url),
            }

    return await asyncio.gather(*[resolve_one(r) for r in rows])


async def stream_thread_zip(thread_id: int):
    """Async generator yielding ZIP bytes for *thread_id*."""
    images = await _resolve_all(thread_id)
    if not images:
        return

    client = await get_client()

    async def member_files():
        for img in images:
            async def data_stream(
                *, _img=img, _client=client
            ):
                # Fast path: already on disk (e.g. user browsed the set before)
                if _img["cache_path"].exists():
                    with open(_img["cache_path"], "rb") as f:
                        while True:
                            chunk = f.read(CHUNK)
                            if not chunk:
                                break
                            yield chunk
                    return

                # Download, cache to disk, and yield simultaneously
                headers: dict[str, str] = {}
                if _img["referer"]:
                    headers["Referer"] = _img["referer"]
                cache_file = open(_img["cache_path"], "wb")
                try:
                    req = _client.build_request(
                        "GET", _img["direct_url"], headers=headers or None
                    )
                    resp = await _client.send(req, stream=True)
                    if resp.status_code != 200:
                        log.warning(
                            "ZIP fetch %s → %d", _img["direct_url"], resp.status_code
                        )
                        await resp.aclose()
                        return
                    async for chunk in resp.aiter_raw(CHUNK):
                        cache_file.write(chunk)
                        yield chunk
                    await resp.aclose()
                except Exception as exc:
                    log.error("ZIP stream error for %s: %s", _img["direct_url"], exc)
                    cache_file.close()
                    _img["cache_path"].unlink(missing_ok=True)
                    raise
                finally:
                    cache_file.close()

            yield (
                img["filename"],
                datetime.datetime.now(),
                0o644,
                ZIP_64,
                data_stream(),
            )

    async for chunk in async_stream_zip(member_files()):
        yield chunk
