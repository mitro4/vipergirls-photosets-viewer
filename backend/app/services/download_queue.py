"""Persistent download queue.

Threads are added to a SQLite-backed queue and processed by a background
worker, up to ``thread_concurrency`` concurrently, in insertion order.
Within each thread, images download through the shared ``download_concurrency``
semaphore (same budget as interactive browsing).

Per-thread controls:
  - stop  → freeze at the current position (status="stopped"); cached bytes
            and the partially-assembled folder are kept as-is.
  - start → re-queue a stopped/error/done thread (already-cached images are
            skipped, so resume is cheap).

The queue survives restarts: status/progress are persisted to the
``download_queue`` table; on startup, threads left "downloading" by a crash
are marked "stopped" so the user can resume them.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import shutil

from ..db import get_db
from ..services.settings_service import get_setting
from ..utils.path import sanitize_filename
from .fetcher import get_thread_images, process_image, thread_title
from .library import get_downloads_folder, record_download

log = logging.getLogger("viper.queue")

# status values: queued | downloading | stopped | done | error

# thread_id -> running download task
_active: dict[int, asyncio.Task] = {}
# thread_id -> live counters (for real-time UI without per-image DB writes)
_progress: dict[int, dict] = {}
_write_lock = asyncio.Lock()
_worker_task: asyncio.Task | None = None


# ── DB helpers ───────────────────────────────────────────────────────

async def _list_rows() -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT thread_id, title, status, total, completed, failed, error, added_at "
            "FROM download_queue ORDER BY _rowid_"
        )
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def _get_row(tid: int) -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT thread_id, title, status, total, completed, failed, error, added_at "
            "FROM download_queue WHERE thread_id=?",
            (tid,),
        )
        row = await cur.fetchone()
        await cur.close()
        return dict(row) if row else None
    finally:
        await db.close()


async def _persist(tid: int, status: str | None, **fields) -> None:
    """Update one queue row. ``status`` may be None to update only counters."""
    async with _write_lock:
        db = await get_db()
        try:
            cols: list[str] = []
            vals: list[object] = []
            if status is not None:
                cols.append("status=?")
                vals.append(status)
            for k, v in fields.items():
                cols.append(f"{k}=?")
                vals.append(v)
            vals.append(tid)
            await db.execute(
                f"UPDATE download_queue SET {', '.join(cols)} WHERE thread_id=?",
                vals,
            )
            await db.commit()
        finally:
            await db.close()


# ── Per-thread download ──────────────────────────────────────────────

async def _materialize_thread(
    entries: list[tuple[str, str]], tid: int, title: str, folder: str
) -> None:
    """Link/copy each cached image into downloads_folder/<folder>/<fname>."""
    base = await get_downloads_folder()
    if not base:
        return  # web mode — delivery is via the per-thread ZIP endpoint
    for zip_path, cache_path in entries:
        sub, fname = zip_path.rsplit("/", 1)
        target_dir = os.path.join(base, sub)
        target = os.path.join(target_dir, fname)
        try:
            os.makedirs(target_dir, exist_ok=True)
            if not os.path.exists(target):
                try:
                    os.link(cache_path, target)
                except OSError:
                    shutil.copy2(cache_path, target)
        except Exception as exc:
            log.warning("Queue materialize %s: %s", fname, exc)
    try:
        await record_download(tid, title, folder)
    except Exception:
        pass


async def _download_thread(tid: int) -> None:
    """Download every image of one thread to the cache, then materialize."""
    completed = 0
    failed = 0
    entries: list[tuple[str, str]] = []
    title = ""
    try:
        timeout = await get_setting("download_timeout")
        retries = await get_setting("max_retries")
        order_images = await get_setting("order_images")

        rows = await get_thread_images(tid)
        title = await thread_title(tid)
        folder = f"{sanitize_filename(title)[:80]} [{tid}]"
        total = len(rows)
        _progress[tid] = {"completed": 0, "failed": 0, "total": total}
        await _persist(
            tid, "downloading",
            title=title, total=total, completed=0, failed=0, error="",
        )

        async def one(row: dict) -> None:
            nonlocal completed, failed
            ok, zip_path, cache_path = await process_image(
                row, tid, folder, timeout, retries, order_images
            )
            if ok:
                completed += 1
                entries.append((zip_path, cache_path))
            else:
                failed += 1
            _progress[tid] = {"completed": completed, "failed": failed, "total": total}

        # All images of this thread are scheduled at once; the shared
        # download_concurrency semaphore (inside process_image) throttles
        # the actual in-flight count across ALL active threads + browsing.
        await asyncio.gather(*[one(r) for r in rows])

        await _materialize_thread(entries, tid, title, folder)
        if await get_setting("auto_clear_completed"):
            async with _write_lock:
                db = await get_db()
                try:
                    await db.execute(
                        "DELETE FROM download_queue WHERE thread_id=?", (tid,)
                    )
                    await db.commit()
                finally:
                    await db.close()
            log.info("Queue thread %s done + auto-cleared: %d/%d", tid, completed, total)
        else:
            await _persist(tid, "done", completed=completed, failed=failed)
            log.info("Queue thread %s done: %d/%d", tid, completed, total)
    except asyncio.CancelledError:
        # Stop request: persist whatever progress was made, keep the row.
        await _persist(tid, "stopped", completed=completed, failed=failed)
        log.info("Queue thread %s stopped at %d", tid, completed)
        raise
    except Exception as exc:
        log.exception("Queue thread %s failed", tid)
        await _persist(
            tid, "error", completed=completed, failed=failed, error=str(exc)
        )
    finally:
        _progress.pop(tid, None)


# ── Worker ───────────────────────────────────────────────────────────

def ensure_worker() -> None:
    """Start the background queue worker if it isn't already running."""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop())


async def _worker_loop() -> None:
    log.info("Download queue worker started")
    while True:
        try:
            # Reap finished tasks.
            for tid in [t for t, task in _active.items() if task.done()]:
                _active.pop(tid, None)

            # Flush live progress to DB (cheap, batched, survives restart).
            for tid, p in list(_progress.items()):
                try:
                    await _persist(tid, None, completed=p["completed"], failed=p["failed"])
                except Exception:
                    pass

            # Spawn queued threads up to the configured concurrency.
            conc = max(1, int(await get_setting("thread_concurrency")))
            while len(_active) < conc:
                db = await get_db()
                try:
                    cur = await db.execute(
                        "SELECT thread_id FROM download_queue "
                        "WHERE status='queued' ORDER BY _rowid_ LIMIT 1"
                    )
                    row = await cur.fetchone()
                    await cur.close()
                finally:
                    await db.close()
                if row is None:
                    break
                tid = row[0]
                # Claim it before spawning so the next iteration skips it.
                await _persist(tid, "downloading")
                _active[tid] = asyncio.create_task(_download_thread(tid))
        except Exception:
            log.exception("Queue worker iteration failed")
        await asyncio.sleep(2.0)


# ── Public API ───────────────────────────────────────────────────────

async def add_to_queue(thread_ids: list[int]) -> list[dict]:
    """Add threads to the queue. A thread already present is reset to
    ``queued`` (resume/re-download) unless it is currently downloading.

    When ``auto_download`` is off, new threads enter as ``stopped`` so the
    user must press Start to begin downloading them."""
    now = datetime.datetime.now().isoformat()
    auto_dl = await get_setting("auto_download")
    initial_status = "queued" if auto_dl else "stopped"
    for tid in thread_ids:
        title = await thread_title(tid)  # ensures metadata cached + title
        existing = await _get_row(tid)
        if existing:
            if existing["status"] != "downloading":
                await _persist(tid, initial_status, error="")
        else:
            db = await get_db()
            try:
                await db.execute(
                    "INSERT OR REPLACE INTO download_queue "
                    "(thread_id, title, status, total, completed, failed, error, added_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (tid, title, initial_status, 0, 0, 0, "", now),
                )
                await db.commit()
            finally:
                await db.close()
    ensure_worker()
    return await list_queue()


async def request_stop(tid: int) -> None:
    """Freeze a thread at its current position."""
    task = _active.get(tid)
    if task is not None and not task.done():
        task.cancel()  # _download_thread persists status="stopped" on cancel
    else:
        await _persist(tid, "stopped")


async def request_start(tid: int) -> None:
    """Re-queue a stopped/error/done thread so the worker resumes it."""
    row = await _get_row(tid)
    if row and row["status"] in ("stopped", "error", "done", "queued"):
        await _persist(tid, "queued", error="")
    ensure_worker()


async def clear_queue() -> None:
    """Remove every queue entry and cancel any active downloads."""
    tasks = [t for t in _active.values() if not t.done()]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _active.clear()
    _progress.clear()
    async with _write_lock:
        db = await get_db()
        try:
            await db.execute("DELETE FROM download_queue")
            await db.commit()
        finally:
            await db.close()


async def list_queue() -> list[dict]:
    rows = await _list_rows()
    # Overlay live progress for active threads so the UI sees fresh counts
    # without waiting for the periodic DB flush.
    for r in rows:
        live = _progress.get(r["thread_id"])
        if live:
            r["completed"] = live["completed"]
            r["failed"] = live["failed"]
            r["total"] = live["total"]
    return rows


async def on_startup() -> None:
    """Crash recovery: threads left "downloading" have no live task now."""
    async with _write_lock:
        db = await get_db()
        try:
            await db.execute(
                "UPDATE download_queue SET status='stopped' WHERE status='downloading'"
            )
            await db.commit()
        finally:
            await db.close()
    ensure_worker()
