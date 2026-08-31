"""Image proxy — streams full-size and thumbnail images through the backend.

Solves three problems:
1. **Hotlink protection** — many image hosts check the Referer header; the
   browser can't set cross-origin Referers on <img> tags.
2. **Interstitial resolution** — the XML's main_url is a page URL, not a
   direct image; the host resolvers convert it.
3. **Caching** — resolved images are cached on disk so subsequent views are
   instant and the upstream host isn't re-hit.

Every tier is served download-then-serve: the upstream file lands in the
content-addressed disk cache first (single-flighted), then goes out as a
FileResponse. That gives honest error statuses (a dead host is a real 502
the browser can retry, not a 200 with a truncated body) and lets concurrent
requests for the same URL share one upstream fetch.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import OrderedDict
from contextlib import AsyncExitStack
from pathlib import Path

import httpx
from fastapi.responses import FileResponse, Response

from ..config import get_settings
from ..db import get_db
from ..hosts.base import get_client, referer_for_host, resolve_imx_thumb, resolve_to_direct
from ..hosts.circuit import is_host_dead, record_host_failure, record_host_success
from ..hosts.registry import identify_host

log = logging.getLogger("viper.proxy")

# 256 KiB: large enough that streaming a 20 MB image is a few hundred
# iterations, not tens of thousands (the previous 8 KiB starved the loop with
# per-chunk await + write overhead).
_CHUNK = 262144
MEDIUM_MAX_WIDTH = 800
# WebP for the medium tier: ~25-35% smaller than JPEG q82 at equal/better
# perceived quality, and universally supported by modern browsers. The "full"
# tier is still the untouched original — no quality loss where it matters.
MEDIUM_FORMAT = "WEBP"
MEDIUM_QUALITY = 82
MEDIUM_EXT = ".webp"
# method=2 encodes ~2x faster than method=4 at ~5-10% larger output — the
# medium tier is latency-sensitive (cards wait on it), size is secondary.
MEDIUM_METHOD = 2

# Single-flight locks keyed by cache file name (sha256 of the source URL).
# Concurrent requests for the SAME image — a wave-loader probe + the visible
# <img>, medium + full for one picture, or auto-retries — would otherwise each
# download the full original. The first caller fetches; concurrent callers
# wait, then find the cache populated and serve instantly.
_INFLIGHT_LOCKS: dict[str, asyncio.Lock] = {}


def _inflight_lock(name: str) -> asyncio.Lock:
    lock = _INFLIGHT_LOCKS.get(name)
    if lock is None:
        lock = asyncio.Lock()
        _INFLIGHT_LOCKS[name] = lock
    return lock


def _release_inflight_lock(name: str) -> None:
    _INFLIGHT_LOCKS.pop(name, None)


# In-memory LRU of image rows (id → dict with id/main_url/thumb_url/host/
# resolved_url). /api/image hits this on every request; with the row cache the
# DB is only touched on a cold miss. Rows are immutable except resolved_url,
# which is written through on update. Re-parsed threads get NEW autoincrement
# ids, so stale entries are only wasted memory, never wrong data.
_ROW_CACHE_MAX = 8192
_row_cache: OrderedDict[int, dict] = OrderedDict()


def _row_cache_put(row: dict) -> None:
    image_id = row["id"]
    _row_cache[image_id] = row
    _row_cache.move_to_end(image_id)
    while len(_row_cache) > _ROW_CACHE_MAX:
        _row_cache.popitem(last=False)


async def get_image_row(image_id: int) -> dict | None:
    """Fetch an image row via the LRU cache (write-through for resolved_url)."""
    row = _row_cache.get(image_id)
    if row is not None:
        _row_cache.move_to_end(image_id)
        return row
    db = await get_db()
    try:
        r = await (
            await db.execute(
                "SELECT id, main_url, thumb_url, host, resolved_url "
                "FROM images WHERE id=?",
                (image_id,),
            )
        ).fetchone()
    finally:
        await db.close()
    if r is None:
        return None
    d = dict(r)
    _row_cache_put(d)
    return d


def set_resolved_url_cache(image_id: int, direct_url: str) -> None:
    """Write-through update for the resolved_url of a cached row (other
    modules — e.g. the download queue — persist resolved_url too)."""
    row = _row_cache.get(image_id)
    if row is not None:
        row["resolved_url"] = direct_url


def put_image_rows(rows: list[dict]) -> None:
    """Warm the row LRU from a batch fetch (e.g. the download queue selecting
    every image of a thread). Only the cached subset of fields is kept."""
    for r in rows:
        try:
            _row_cache_put({
                "id": r["id"],
                "main_url": r["main_url"],
                "thumb_url": r["thumb_url"],
                "host": r["host"],
                "resolved_url": r["resolved_url"],
            })
        except (KeyError, TypeError):
            continue


# Cap concurrent upstream image fetches.  Without this, a page of ~10 cards
# fires 20-50 image requests at once; dead-host requests hold each connection
# for the full timeout, exhausting the browser's 6-conn-per-host limit and
# freezing the tab (even non-image requests queue behind them).  The semaphore
# bounds the number of *simultaneous upstream fetches* so live images still
# load while dead ones fail fast without monopolising connections.
#
# Dynamically sized from the ``download_concurrency`` runtime setting (default
# 8) via _get_proxy_semaphore() — shared by the image proxy (previews/viewing)
# AND download jobs (ZIP).  Recreated when the setting changes.  Per-host
# semaphores still prevent a single slow host from monopolising the budget.
_PROXY_SEMAPHORE: asyncio.Semaphore | None = None
_proxy_semaphore_limit: int = 0


async def _get_proxy_semaphore() -> asyncio.Semaphore:
    """Return the global image-fetch semaphore, sized from the
    ``download_concurrency`` runtime setting.

    Recreated when the setting changes so adjusting it in the UI takes effect
    immediately.  Brief imprecision during recreation (in-flight acquires on
    the old semaphore aren't counted on the new one) is acceptable — settings
    change rarely.
    """
    global _PROXY_SEMAPHORE, _proxy_semaphore_limit
    from ..services.settings_service import get_setting
    limit = await get_setting("download_concurrency")
    if not isinstance(limit, int) or limit < 1:
        limit = 8
    if _PROXY_SEMAPHORE is None or limit != _proxy_semaphore_limit:
        _PROXY_SEMAPHORE = asyncio.Semaphore(limit)
        _proxy_semaphore_limit = limit
        log.info("Image-fetch semaphore: %d", limit)
    return _PROXY_SEMAPHORE


# Per-host cap on top of the global semaphore: a single slow/dead host can
# otherwise consume the whole global budget, starving every other host.  Lazily
# created per host (Semaphore binds to the running loop on first use).
_HOST_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


def _host_semaphore(host: str) -> asyncio.Semaphore | None:
    if not host:
        return None
    sem = _HOST_SEMAPHORES.get(host)
    if sem is None:
        sem = asyncio.Semaphore(get_settings().per_host_concurrency)
        _HOST_SEMAPHORES[host] = sem
    return sem
# Images are served from a content-addressed disk cache (sha256 of the source
# URL), so a given URL never changes. Mark responses immutable so browsers and
# Caddy reuse them aggressively across navigations without revalidating.
_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


def _cache_dir() -> Path:
    d = get_settings().cache_dir / "img"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def _media_type(url: str) -> str:
    ext = url.rsplit(".", 1)[-1].split("?")[0].lower() if "." in url else ""
    return {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "gif": "image/gif",
        "webp": "image/webp", "bmp": "image/bmp",
    }.get(ext, "image/jpeg")


def _is_gif_file(path: Path) -> bool:
    """Sniff magic bytes to detect a GIF. Cache files are content-addressed by
    SHA-256 hash with **no extension**, so ``path.suffix`` is always empty and
    cannot be used to tell formats apart. GIF streams start with ``GIF87a`` or
    ``GIF89a``."""
    try:
        with open(path, "rb") as fh:
            return fh.read(6) in (b"GIF87a", b"GIF89a")
    except OSError:
        return False


def _medium_path(full_cache_path: Path) -> Path:
    return full_cache_path.with_name(full_cache_path.stem + "_m" + MEDIUM_EXT)


def _create_medium(full_path: Path) -> Path | None:
    """Resize *full_path* to a ≤800px-wide WebP.  Returns the medium path
    (created if necessary) or None on failure."""
    medium_path = _medium_path(full_path)
    if medium_path.exists() and medium_path.stat().st_size > 0:
        return medium_path
    try:
        from PIL import Image, ImageOps

        with Image.open(full_path) as img:
            # Decode JPEGs at reduced scale: draft() configures the decoder so
            # a 6000px photo is decoded as ~750-800px directly (~1/8 of the
            # pixels) instead of decoding full size and throwing most of it
            # away in thumbnail(). No-op for non-JPEG formats.
            if img.format == "JPEG":
                img.draft("RGB", (MEDIUM_MAX_WIDTH, MEDIUM_MAX_WIDTH))
            # Honour the EXIF orientation flag (phone photos would otherwise
            # render sideways in the medium tier).
            img = ImageOps.exif_transpose(img)
            img.thumbnail((MEDIUM_MAX_WIDTH, MEDIUM_MAX_WIDTH))
            # Flatten transparency / palette onto white — photos are RGB and
            # this avoids a surprising dark matte when the browser composites.
            if img.mode != "RGB":
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode in ("RGBA", "LA"):
                    background.paste(img, mask=img.convert("RGBA").split()[-1])
                else:
                    background.paste(img.convert("RGB"))
                img = background
            img.save(medium_path, MEDIUM_FORMAT, quality=MEDIUM_QUALITY,
                     method=MEDIUM_METHOD)
        return medium_path
    except Exception as exc:
        log.warning("Medium creation failed for %s: %s", full_path.name, exc)
        return None


async def _ensure_medium(full_path: Path) -> Path | None:
    """Single-flighted medium creation.

    Without this, concurrent ``?size=medium`` requests for the same image
    (wave-loader probe + the visible <img>) each run a Pillow encode of the
    same original; the loser's file then clobbers the winner's mid-write.
    Keyed by the medium file name — distinct from the full-image lock, which
    only guards the download."""
    medium_path = _medium_path(full_path)
    if medium_path.exists() and medium_path.stat().st_size > 0:
        return medium_path
    lock = _inflight_lock(medium_path.name)
    try:
        async with lock:
            if medium_path.exists() and medium_path.stat().st_size > 0:
                return medium_path
            return await asyncio.to_thread(_create_medium, full_path)
    finally:
        _release_inflight_lock(medium_path.name)


async def _download_full_to_disk(
    direct_url: str, referer: str, cache_path: Path, *, host: str = "",
) -> Path | None:
    """Download *direct_url* straight to *cache_path* via a .part file + atomic
    rename (a partial file can never be served from the content-addressed cache).

    Must run while holding the single-flight lock for ``cache_path.name``.
    """
    client = await get_client()
    headers: dict[str, str] = {"Referer": referer} if referer else {}
    h = host or identify_host(direct_url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + ".part")
    host_sem = _host_semaphore(h)
    try:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(await _get_proxy_semaphore())
            if host_sem is not None:
                await stack.enter_async_context(host_sem)
            # stream=True so the body is never fully buffered in RAM. The
            # semaphore is held across the whole read so concurrent upstream
            # fetches stay bounded. read=25s tolerates slow image hosts under a
            # proxy without aborting a healthy transfer (8s was too tight).
            req = client.build_request(
                "GET", direct_url, headers=headers or None,
                timeout=httpx.Timeout(connect=10, read=25, write=10, pool=5),
            )
            resp = await client.send(req, stream=True, follow_redirects=True)
            try:
                if resp.status_code != 200:
                    log.warning("Image fetch %s → %d", direct_url, resp.status_code)
                    record_host_failure(h)
                    return None
                # Reject non-image bodies that arrive with 200 (a Cloudflare
                # challenge page, an unresolved interstitial, or an error page).
                # Caching such a body would poison the cache and silently render
                # as a red ✕ — and recording success would mask a failing host
                # from the circuit breaker, so it never recovers.
                ct = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if ct and not ct.startswith("image/"):
                    log.warning(
                        "Non-image content-type %r for %s", ct, direct_url
                    )
                    record_host_failure(h)
                    return None
                # Use the upstream content-type when available — cache files
                # are extension-less, so a URL-based guess can be wrong
                # (e.g. hosts serving .jpg URLs as image/webp).
                media_type = ct if ct.startswith("image/") else _media_type(direct_url)
                _note_content_type(cache_path.name, media_type)
                # Host responded 200 with an image — it's alive; clear any
                # prior failure count.
                record_host_success(h)
                with open(tmp_path, "wb") as fh:
                    async for chunk in resp.aiter_raw(_CHUNK):
                        fh.write(chunk)
            finally:
                await resp.aclose()
        tmp_path.replace(cache_path)
        return cache_path
    except Exception as exc:
        log.warning("Image fetch failed %s: %s", direct_url, exc)
        record_host_failure(h)
        tmp_path.unlink(missing_ok=True)
        return None


# Upstream-declared media type per cache file (cache files are extension-less).
# Small bounded map; misses fall back to the URL-extension guess.
_content_types: OrderedDict[str, str] = OrderedDict()


def _media_type_for_cache(name: str, url: str) -> str:
    ct = _content_types.get(name)
    if ct is not None:
        _content_types.move_to_end(name)
        return ct
    return _media_type(url)


def _note_content_type(name: str, media_type: str) -> None:
    _content_types[name] = media_type
    _content_types.move_to_end(name)
    while len(_content_types) > 4096:
        _content_types.popitem(last=False)


async def _ensure_full_cached(
    direct_url: str, referer: str, cache_path: Path, *, host: str = "",
) -> Path | None:
    """Make sure the full image is on disk; fetch it if missing.

    Single-flighted per cache key: concurrent medium/full/probe requests for the
    same picture share one download instead of racing to fetch the original.
    """
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path
    lock = _inflight_lock(cache_path.name)
    result: Path | None = None
    async with lock:
        # Re-check after acquiring — another in-flight request may have just
        # produced the file while we waited.
        if cache_path.exists() and cache_path.stat().st_size > 0:
            result = cache_path
        else:
            result = await _download_full_to_disk(
                direct_url, referer, cache_path, host=host
            )
    _release_inflight_lock(cache_path.name)
    return result


async def _resolve_row(row: dict) -> tuple[str, str]:
    """Resolve a DB image row to (direct_url, referer), persisting the result."""
    direct_url = row["resolved_url"] or ""
    if not direct_url:
        # Bound concurrent interstitial-page fetches per host, the same way
        # downloads are bounded below. Without this, opening a thread fires one
        # show-page request per image in parallel at the host — a burst that
        # triggers rate-limiting/timeouts and trips the circuit breaker before
        # the (already-bounded) download path even starts. The result is every
        # image rendering as a red ✕ while card thumbnails — served from a
        # different, direct subdomain and browser-cached immutable — still load.
        resolve_host = row["host"] or identify_host(row["main_url"]) or ""
        host_sem = _host_semaphore(resolve_host)
        try:
            async with AsyncExitStack() as stack:
                if host_sem is not None:
                    await stack.enter_async_context(host_sem)
                _, direct_url = await resolve_to_direct(
                    row["main_url"], row["thumb_url"]
                )
        except Exception as exc:
            log.error("Resolution failed for image %s: %s", row["id"], exc)
            raise
        if direct_url and direct_url != row["main_url"]:
            # Write-through: ``row`` is usually the cached LRU dict itself.
            row["resolved_url"] = direct_url
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
    return direct_url, referer_for_host(host)


async def _serve_thumbnail(thumb_url: str) -> Response:
    """Serve a thumbnail from cache or fetch it from upstream.

    The thumbnail is the degraded fallback for unreachable full images
    (circuit-broken / Cloudflare-challenged hosts such as turboimagehost) and
    is also served directly for card covers, so it must ALWAYS be attempted:
    thumbs frequently live on a separate, reachable CDN even when the
    full-image interstitial is behind a JS wall (turboimagehost thumbs on
    s4d*.turboimagehost.com/t/ and turboimg.net return 200 while the /p/
    interstitial is a CF 403). The full-image host's circuit breaker must NOT
    block the thumb — when the thumb shares the host identity (s4d1.
    turboimagehost.com -> "turboimagehost.com") the breaker would defeat the
    very fallback we rely on. A genuinely dead thumb fails in the fetch below
    and surfaces a natural 502.
    """
    cache_path = _cache_dir() / _cache_key(thumb_url)
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return FileResponse(
            str(cache_path),
            media_type=_media_type_for_cache(cache_path.name, thumb_url),
            headers=_CACHE_HEADERS,
        )
    thumb_host = identify_host(thumb_url)
    referer = referer_for_host(thumb_host)
    path = await _ensure_full_cached(
        thumb_url, referer, cache_path, host=thumb_host
    )
    if path is None:
        return Response(status_code=502, content=b"Thumbnail unavailable")
    return FileResponse(
        str(path),
        media_type=_media_type_for_cache(cache_path.name, thumb_url),
        headers=_CACHE_HEADERS,
    )


async def proxy_image(image_id: int, size: str = "full") -> Response:
    """Look up an image by DB id and stream it back.

    *thumb*   — the host's own thumbnail (small, direct link).
    *medium*  — a server-resized ≤800px WebP (crisp in cards, light bandwidth).
    *full*    — the original full-size image.

    For medium/full, if the full image can't be reached — the host is circuit-
    broken, behind an unsolvable challenge (e.g. turboimagehost's Cloudflare JS
    wall), or resolution/fetch fails — the thumbnail is served as a degraded
    fallback.  Visible-but-low-res beats a red ✕, and the thumbnail usually
    lives on a separate CDN that stays reachable when the full host is down.
    """
    if size not in ("thumb", "medium", "full"):
        size = "full"

    row = await get_image_row(image_id)
    if not row:
        return Response(status_code=404, content=b"Not found")

    host = row["host"] or identify_host(row["main_url"]) or ""
    thumb_url = row["thumb_url"] or row["main_url"]

    # --- Thumbnail path: direct URL, just proxy (own host identity) ---
    if size == "thumb":
        # imx.to's natural thumb URLs (esp. old http:// apex ones) are often
        # dead, but image.imx.to/u/t/ is a stable thumb CDN — transform first.
        if host == "imx.to":
            try:
                return await _serve_thumbnail(resolve_imx_thumb(thumb_url))
            except ValueError:
                pass
        return await _serve_thumbnail(thumb_url)

    # --- full / medium ---
    # Circuit breaker: when the host is in its fail-fast window, skip the
    # doomed upstream resolution/fetch.  An already-cached result (from a prior
    # successful fetch) still serves; otherwise we fall through to the
    # thumbnail fallback below.
    dead = bool(host) and is_host_dead(host)
    direct_url = ""
    referer = ""
    if dead:
        direct_url = row["resolved_url"] or ""
        referer = referer_for_host(host)
    else:
        try:
            direct_url, referer = await _resolve_row(row)
        except Exception as exc:
            log.warning("Resolution failed for image %s: %s", image_id, exc)
            record_host_failure(host)
            direct_url = ""

    if direct_url:
        full_cache = _cache_dir() / _cache_key(direct_url)
        if size == "medium":
            full_path = await _ensure_full_cached(
                direct_url, referer, full_cache, host=host
            )
            if full_path:
                # GIFs are served as-is — a Pillow resize would collapse the
                # animation down to a single static frame.
                if _is_gif_file(full_path):
                    return FileResponse(
                        str(full_path), media_type="image/gif",
                        headers=_CACHE_HEADERS,
                    )
                medium_path = await _ensure_medium(full_path)
                if medium_path:
                    return FileResponse(
                        str(medium_path), media_type="image/webp",
                        headers=_CACHE_HEADERS,
                    )
                # Resize failed — fall back to the full image.
                return FileResponse(
                    str(full_path),
                    media_type=_media_type_for_cache(full_cache.name, direct_url),
                    headers=_CACHE_HEADERS,
                )
        else:  # full
            full_path = await _ensure_full_cached(
                direct_url, referer, full_cache, host=host
            )
            if full_path:
                return FileResponse(
                    str(full_path),
                    media_type=_media_type_for_cache(full_cache.name, direct_url),
                    headers=_CACHE_HEADERS,
                )
            # Download failed → fall through to the thumbnail fallback below
            # (medium and full share the same degraded path).

    # Degraded fallback: the full image is unreachable. Serve the thumbnail
    # instead of returning a red-✕ 502.
    if dead:
        log.info("Thumbnail fallback (dead host %s) for image %s", host, image_id)
    return await _serve_thumbnail(thumb_url)


async def proxy_raw_url(url: str) -> Response:
    """Proxy an arbitrary image URL (used for thumbnails/cover URLs)."""
    cache_path = _cache_dir() / f"{_cache_key(url)}"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return FileResponse(
            str(cache_path),
            media_type=_media_type_for_cache(cache_path.name, url),
            headers=_CACHE_HEADERS,
        )

    host = identify_host(url)
    if host and is_host_dead(host):
        return Response(status_code=502, content=b"Host temporarily unavailable")
    referer = referer_for_host(host)
    path = await _ensure_full_cached(url, referer, cache_path, host=host)
    if path is None:
        return Response(status_code=502, content=b"Upstream fetch failed")
    return FileResponse(
        str(path),
        media_type=_media_type_for_cache(cache_path.name, url),
        headers=_CACHE_HEADERS,
    )


def cleanup_cache(max_bytes: int) -> None:
    """Remove oldest files if the cache exceeds *max_bytes* (LRU by mtime).

    Hardlinked downloads are safe: deleting the cache name leaves the download
    folder's link (same inode) fully intact.
    """
    if max_bytes <= 0:
        return
    cache = _cache_dir()
    files = [f for f in cache.iterdir() if f.is_file()]
    total = 0
    for f in files:
        try:
            total += f.stat().st_size
        except OSError:
            pass
    if total <= max_bytes:
        return
    files.sort(key=lambda f: f.stat().st_mtime)
    removed = 0
    while total > max_bytes * 0.9 and files:
        f = files.pop(0)
        try:
            sz = f.stat().st_size
            f.unlink()
            total -= sz
            removed += 1
        except OSError:
            pass
    if removed:
        log.info("Cache cleanup: removed %d files, now %.1f MB",
                 removed, total / 1048576)


async def trim_cache_if_needed() -> None:
    """Maintenance entry point: trim the cache when the runtime
    ``cache_limit_gb`` setting is set (> 0). Runs the walk off-loop."""
    from .settings_service import get_setting
    limit_gb = await get_setting("cache_limit_gb")
    try:
        limit_gb = float(limit_gb)
    except (TypeError, ValueError):
        return
    if limit_gb <= 0:
        return
    await asyncio.to_thread(cleanup_cache, int(limit_gb * 1024**3))


async def prefetch_resolution(image_ids: list[int], limit: int = 20) -> None:
    """Background-prefetch direct image URLs so the first ``/api/image`` request
    for each id skips the interstitial-resolution RTT.  Idempotent — rows that
    already carry a resolved_url are skipped.  Best-effort: errors are swallowed.
    """
    ids = [i for i in image_ids if i and i > 0][:limit]
    if not ids:
        return
    sem = asyncio.Semaphore(4)

    async def one(img_id: int) -> None:
        async with sem:
            row = await get_image_row(img_id)
            if not row or row["resolved_url"]:
                return
            try:
                await _resolve_row(row)
            except Exception as exc:
                log.debug("Prefetch resolve failed for %s: %s", img_id, exc)

    await asyncio.gather(*[one(i) for i in ids], return_exceptions=True)


async def prewarm_mediums(image_ids: list[int], limit: int = 6) -> None:
    """Background-warm the medium tier for the given images so the browser's
    subsequent ``?size=medium`` requests hit a ready cache.

    Resolves the direct URL, downloads the full once (single-flighted), and
    renders the medium.  Bounded to a small cohort (the first visible images of
    a thread) to avoid pulling full-size originals the user may never scroll to.
    Best-effort.
    """
    ids = [i for i in image_ids if i and i > 0][:limit]
    if not ids:
        return
    sem = asyncio.Semaphore(3)

    async def one(img_id: int) -> None:
        async with sem:
            row = await get_image_row(img_id)
            if not row:
                return
            host = row["host"] or identify_host(row["main_url"]) or ""
            if host and is_host_dead(host):
                return
            try:
                direct_url, referer = await _resolve_row(row)
            except Exception:
                return
            if not direct_url:
                return
            full_cache = _cache_dir() / _cache_key(direct_url)
            full_path = await _ensure_full_cached(
                direct_url, referer, full_cache, host=host
            )
            if full_path and not _is_gif_file(full_path):
                await _ensure_medium(full_path)

    await asyncio.gather(*[one(i) for i in ids], return_exceptions=True)
