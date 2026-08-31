"""Download endpoint — one-off streaming ZIP of a single thread.

The legacy multi-thread job system (POST /api/download/multi → /status →
/retry → /zip) was removed; the persistent download queue
(``/api/download/queue``, services/download_queue.py) replaced it. Bulk
fetching logic lives in services/fetcher.py.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..services.fetcher import thread_title
from ..services.thread_service import get_thread_detail
from ..services.zip_service import stream_thread_zip

log = logging.getLogger("viper.api.download")
router = APIRouter()


@router.get("/thread/{thread_id}/download")
async def download_thread(thread_id: int):
    try:
        await get_thread_detail(thread_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    safe_title = "".join(
        c if c.isalnum() or c in "- " else "_" for c in (await thread_title(thread_id))
    ).strip() or f"thread_{thread_id}"
    zip_name = f"{safe_title[:80]} [{thread_id}].zip"

    try:
        from ..services.library import record_download
        await record_download(thread_id, safe_title, zip_name)
    except Exception:
        log.warning("Could not record download for thread %s", thread_id, exc_info=True)

    return StreamingResponse(
        stream_thread_zip(thread_id),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
