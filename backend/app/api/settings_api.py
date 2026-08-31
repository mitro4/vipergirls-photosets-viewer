"""Settings endpoints — read / update runtime-configurable settings."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.settings_service import get_all_settings, update_settings

router = APIRouter(tags=["settings"])


class SettingsUpdate(BaseModel):
    order_images: bool | None = None
    download_concurrency: int | None = None
    thread_concurrency: int | None = None
    download_timeout: int | None = None
    max_retries: int | None = None
    forum_proxy: str | None = None
    proxy_enabled: bool | None = None
    proxy_url: str | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None
    auto_download: bool | None = None
    auto_clear_completed: bool | None = None


@router.get("/settings")
async def get_settings_api() -> dict:
    return await get_all_settings()


@router.put("/settings")
async def update_settings_api(body: SettingsUpdate) -> dict:
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return await update_settings(updates)
