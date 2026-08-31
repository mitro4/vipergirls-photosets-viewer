"""GET /api/config — public runtime configuration for the UI."""
from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings
from ..models import ForumConfigOut
from ..services.settings_service import get_forum_base_url

router = APIRouter()


@router.get("/config", response_model=ForumConfigOut)
async def get_config() -> ForumConfigOut:
    return ForumConfigOut(
        forum_url=await get_forum_base_url(),
        click_url=get_settings().click_base_url,
    )
