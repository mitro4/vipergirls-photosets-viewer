"""Download queue endpoints (persistent, stop/resume, folder delivery)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..services import download_queue as q

router = APIRouter()


class QueueAddRequest(BaseModel):
    thread_ids: list[int]


@router.get("/download/queue")
async def list_queue() -> dict:
    return {"items": await q.list_queue()}


@router.post("/download/queue")
async def add_to_queue(body: QueueAddRequest) -> dict:
    if not body.thread_ids:
        return {"items": await q.list_queue()}
    return {"items": await q.add_to_queue(body.thread_ids)}


@router.post("/download/queue/{thread_id}/stop")
async def stop_queue_item(thread_id: int) -> dict:
    await q.request_stop(thread_id)
    return {"ok": True}


@router.post("/download/queue/{thread_id}/start")
async def start_queue_item(thread_id: int) -> dict:
    await q.request_start(thread_id)
    return {"ok": True}


@router.delete("/download/queue")
async def clear_queue() -> dict:
    await q.clear_queue()
    return {"ok": True}
