"""Image proxy endpoints.

GET /api/image/{image_id}?size=thumb|medium|full
    Streams the image through the backend, resolving host interstitials
    and caching on disk.  *medium* is a server-resized ~800px preview
    (crisp in cards without the bandwidth cost of the full image).
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response

from ..services.image_proxy import proxy_image, proxy_raw_url

router = APIRouter()


@router.get("/image/{image_id}")
async def get_image(
    image_id: int,
    size: str = Query("full", pattern="^(thumb|medium|full)$"),
) -> Response:
    """Proxy a single image by database ID."""
    return await proxy_image(image_id, size=size)


@router.get("/proxy")
async def proxy_url(
    url: str = Query(..., description="Image URL to proxy"),
) -> Response:
    """Proxy an arbitrary image URL (for thumbnails/cover URLs)."""
    return await proxy_raw_url(url)
