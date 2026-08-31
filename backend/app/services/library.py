"""User library — liked threads and download history (persisted locally).

Likes are mirrored to the forum via vBulletin's ``post_thanks.php`` addon and
recorded locally so the "Liked" view can list them without a round-trip.
Downloads are recorded at ZIP-stream time so the "Downloads" view (with
show-in-folder) knows what the user saved and under which filename.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from ..db import get_db
from ..scrapers.http import get_http
from ..scrapers.search import _get_securitytoken
from ..services.settings_service import get_forum_base_url
from ..services.thread_service import get_thread_detail

log = logging.getLogger("viper.library")

_DOWNLOADS_FOLDER_KEY = "downloads_folder"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


async def _thread_title(thread_id: int) -> str:
    db = await get_db()
    try:
        row = await (
            await db.execute("SELECT title FROM threads WHERE id=?", (thread_id,))
        ).fetchone()
        return row["title"] if row else f"thread_{thread_id}"
    finally:
        await db.close()


async def _first_post_id(thread_id: int) -> int:
    """The post id vBulletin expects for ``post_thanks_add`` (first image post)."""
    db = await get_db()
    try:
        row = await (
            await db.execute(
                "SELECT post_id FROM images WHERE thread_id=? AND post_id>0 "
                "GROUP BY post_id ORDER BY MIN(idx) LIMIT 1",
                (thread_id,),
            )
        ).fetchone()
        return row["post_id"] if row else 0
    finally:
        await db.close()


async def _post_thanks(thread_id: int, post_id: int, *, add: bool) -> bool:
    """Hit ``post_thanks.php`` to add/remove a like on the forum.

    Returns True when the forum responds without an HTTP error. The
    securitytoken is fetched fresh each call (it's session-scoped and the
    guest value is rejected for this action).
    """
    base = await get_forum_base_url()
    token = await _get_securitytoken(base)
    url = f"{base}/post_thanks.php"
    params = {
        "do": "post_thanks_add" if add else "post_thanks_remove",
        "p": str(post_id),
        "securitytoken": token or "guest",
    }
    referer = f"{base}/threads/{thread_id}"
    resp = await get_http().get(url, params=params, referer=referer)
    if resp.status_code >= 400:
        log.warning(
            "post_thanks %s for thread %s (post %s) -> HTTP %d",
            params["do"], thread_id, post_id, resp.status_code,
        )
        return False
    return True


# ── likes ─────────────────────────────────────────────────────────────

async def is_liked(thread_id: int) -> bool:
    db = await get_db()
    try:
        row = await (
            await db.execute(
                "SELECT 1 FROM liked_threads WHERE thread_id=?", (thread_id,)
            )
        ).fetchone()
        return row is not None
    finally:
        await db.close()


async def like_thread(thread_id: int) -> dict:
    if await is_liked(thread_id):
        return {"liked": True, "thread_id": thread_id, "already": True}
    # Ensure the thread's images are cached so the first post id is resolvable
    # (cards don't populate images — only viewing the thread does).
    try:
        await get_thread_detail(thread_id)
    except RuntimeError:
        pass  # proceed best-effort with whatever is cached
    title = await _thread_title(thread_id)
    post_id = await _first_post_id(thread_id)
    if not post_id:
        raise RuntimeError("Could not determine the thread's first post id")
    await _post_thanks(thread_id, post_id, add=True)
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO liked_threads (thread_id, title, post_id, liked_at) "
            "VALUES (?, ?, ?, ?)",
            (thread_id, title, post_id, _now()),
        )
        await db.commit()
    finally:
        await db.close()
    return {"liked": True, "thread_id": thread_id}


async def unlike_thread(thread_id: int) -> dict:
    db = await get_db()
    try:
        row = await (
            await db.execute(
                "SELECT post_id FROM liked_threads WHERE thread_id=?", (thread_id,)
            )
        ).fetchone()
    finally:
        await db.close()
    if row and row["post_id"]:
        await _post_thanks(thread_id, row["post_id"], add=False)
    db = await get_db()
    try:
        await db.execute("DELETE FROM liked_threads WHERE thread_id=?", (thread_id,))
        await db.commit()
    finally:
        await db.close()
    return {"liked": False, "thread_id": thread_id}


async def list_liked() -> list[dict]:
    db = await get_db()
    try:
        rows = await (
            await db.execute(
                "SELECT thread_id, title, liked_at FROM liked_threads "
                "ORDER BY liked_at DESC"
            )
        ).fetchall()
        return [
            {"thread_id": r["thread_id"], "title": r["title"], "liked_at": r["liked_at"]}
            for r in rows
        ]
    finally:
        await db.close()


# ── downloads ─────────────────────────────────────────────────────────

async def record_download(thread_id: int, title: str, filename: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO downloads (thread_id, title, filename, downloaded_at) "
            "VALUES (?, ?, ?, ?)",
            (thread_id, title, filename, _now()),
        )
        await db.commit()
    finally:
        await db.close()


async def list_downloads() -> list[dict]:
    db = await get_db()
    try:
        rows = await (
            await db.execute(
                "SELECT thread_id, title, filename, downloaded_at FROM downloads "
                "ORDER BY downloaded_at DESC"
            )
        ).fetchall()
    finally:
        await db.close()

    items = [
        {
            "thread_id": r["thread_id"],
            "title": r["title"],
            "filename": r["filename"],
            "downloaded_at": r["downloaded_at"],
        }
        for r in rows
    ]

    # The Downloads view mirrors the save folder. Drop (and forget) records
    # whose thread folder was removed on disk — otherwise they'd stay listed
    # and "Open folder" would surface an OS error about a missing directory.
    # Skipped when no folder is configured (web builds: nothing to check).
    folder = await get_downloads_folder()
    if folder:
        items = await _prune_missing_downloads(folder, items)
    return items


async def _prune_missing_downloads(folder: str, items: list[dict]) -> list[dict]:
    """Remove download records whose thread subfolder no longer exists."""
    keep: list[dict] = []
    stale: list[int] = []
    for it in items:
        sub = it.get("filename") or ""
        if os.path.isdir(os.path.join(folder, sub)):
            keep.append(it)
        else:
            stale.append(it["thread_id"])
    if stale:
        db = await get_db()
        try:
            await db.executemany(
                "DELETE FROM downloads WHERE thread_id=?", [(i,) for i in stale]
            )
            await db.commit()
        finally:
            await db.close()
        log.info("Pruned %d missing download folders from history", len(stale))
    return keep


async def get_downloads_folder() -> str:
    # Read directly — ``downloads_folder`` is not part of settings_service's
    # typed _SCHEMA, so get_setting() would KeyError on it.
    db = await get_db()
    try:
        row = await (
            await db.execute("SELECT value FROM settings WHERE key=?", (_DOWNLOADS_FOLDER_KEY,))
        ).fetchone()
        return row["value"] if row else ""
    finally:
        await db.close()


async def set_downloads_folder(folder: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (_DOWNLOADS_FOLDER_KEY, folder or ""),
        )
        await db.commit()
    finally:
        await db.close()
