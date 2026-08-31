"""Library endpoints — liked threads and download history.

GET    /api/liked               — list liked threads
POST   /api/thread/{id}/like     — like a thread (mirrors to forum post_thanks)
DELETE /api/thread/{id}/like     — unlike
GET    /api/downloads            — list downloaded threads + current folder
POST   /api/downloads/folder     — store the Electron downloads folder
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..scrapers.auth import is_logged_in
from ..services.library import (
    get_downloads_folder,
    like_thread,
    list_downloads,
    list_liked,
    set_downloads_folder,
    unlike_thread,
)

log = logging.getLogger("viper.api.library")
router = APIRouter()


def _require_auth() -> None:
    if not is_logged_in():
        raise HTTPException(status_code=401, detail="Not logged in")


@router.post("/thread/{thread_id}/like")
async def like_ep(thread_id: int) -> dict:
    _require_auth()
    try:
        return await like_thread(thread_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.delete("/thread/{thread_id}/like")
async def unlike_ep(thread_id: int) -> dict:
    _require_auth()
    try:
        return await unlike_thread(thread_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/liked")
async def liked_ep() -> dict:
    return {"items": await list_liked()}


@router.get("/downloads")
async def downloads_ep() -> dict:
    return {"items": await list_downloads(), "folder": await get_downloads_folder()}


class FolderRequest(BaseModel):
    folder: str


@router.post("/downloads/folder")
async def set_folder_ep(body: FolderRequest) -> dict:
    await set_downloads_folder(body.folder)
    return {"folder": body.folder}
