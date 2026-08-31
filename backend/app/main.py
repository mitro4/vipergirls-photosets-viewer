"""FastAPI application entry point.

Static frontend assets are served by Caddy in production; during local
backend development uvicorn serves them from the built frontend.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders

from .api import auth as auth_api
from .api import categories as categories_api
from .api import config_api as config_api
from .api import download as download_api
from .api import download_queue as download_queue_api
from .api import image as image_api
from .api import library as library_api
from .api import search as search_api
from .api import settings_api as settings_api
from .api import threads as threads_api
from .config import get_settings
from .db import close_pool, init_db
from .hosts.base import close_client as close_host_client
from .scrapers.auth import auto_login
from .scrapers.http import close_http
from .services import download_queue as queue_svc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("viper")

# Periodic maintenance: trim the image cache when the user has set a
# ``cache_limit_gb`` limit (0 = unlimited, the default — the cache only
# grows unless opted in).
_MAINTENANCE_INTERVAL = 30 * 60  # seconds


async def _maintenance_loop() -> None:
    from .services.image_proxy import trim_cache_if_needed

    while True:
        await asyncio.sleep(_MAINTENANCE_INTERVAL)
        try:
            await trim_cache_if_needed()
        except Exception:
            log.exception("Cache trim failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting ViperGirls Viewer backend")
    await init_db()
    log.info("Database initialised at %s", get_settings().db_path)
    await auto_login()
    await queue_svc.on_startup()
    maintenance = asyncio.create_task(_maintenance_loop())
    try:
        yield
    finally:
        maintenance.cancel()
        try:
            await maintenance
        except (asyncio.CancelledError, Exception):
            pass
        log.info("Shutting down")
        await close_http()
        await close_host_client()
        await close_pool()


class _NoCacheHTMLMiddleware:
    """Pure-ASGI replacement for ``@app.middleware("http")``.

    BaseHTTPMiddleware wraps every request in an extra task and adds
    measurable overhead on the large streaming image responses. This wrapper
    only inspects ``http.response.start`` headers and otherwise passes bytes
    through untouched.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "text/html" in headers.get("content-type", ""):
                    # index.html must always be revalidated — Vite assets are
                    # content-hashed, but a cached shell referencing old
                    # hashes 404s (blank page after an upgrade).
                    headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                    headers["Pragma"] = "no-cache"
                    headers["Expires"] = "0"
            await send(message)

        await self.app(scope, receive, send_wrapper)


app = FastAPI(title="ViperGirls Photo Sets Viewer API", version="0.1.6", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(_NoCacheHTMLMiddleware)

app.include_router(categories_api.router, prefix="/api")
app.include_router(config_api.router, prefix="/api")
app.include_router(threads_api.router, prefix="/api")
app.include_router(image_api.router, prefix="/api")
app.include_router(download_api.router, prefix="/api")
app.include_router(download_queue_api.router, prefix="/api")
app.include_router(auth_api.router, prefix="/api")
app.include_router(search_api.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(library_api.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


# Serve built frontend if present (production: Caddy does this, but keep as fallback)
_static = Path(__file__).resolve().parent.parent / "static"
if _static.exists():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
