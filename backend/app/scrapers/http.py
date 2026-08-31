"""Shared HTTP client with Cloudflare bypass and rate limiting.

Uses curl_cffi with Firefox TLS impersonation to get past Cloudflare.
Leaky-bucket rate limiters space requests at >= 1/rate seconds apart
(default 2 req/s, matching vripper's forum courtesy limit).

Limiters are **per-host**: viper.to (forum scraping) and viper.click
(vr.php metadata) are independent services and no longer serialise behind
one shared bucket — a batch of cover lookups used to stall behind forum
page scrapes and vice versa. Each host still gets the full configured
courtesy rate.
"""
from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlparse

from ..config import get_settings

log = logging.getLogger("viper.http")


class RateLimiter:
    """Leaky-bucket limiter: enforces minimum spacing between acquisitions."""

    def __init__(self, rate_per_sec: float) -> None:
        self._min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._last: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self._last + self._min_interval - now
            if wait > 0:
                log.debug("rate-limit sleep %.2fs", wait)
                await asyncio.sleep(wait)
            self._last = time.monotonic()


class HttpClient:
    """Lazy-initialised curl_cffi async session with rate limiting."""

    def __init__(self) -> None:
        self._session = None  # type: ignore[assignment]
        # One limiter per destination host (viper.to vs viper.click are
        # different services and shouldn't share a single courtesy budget).
        self._rates: dict[str, RateLimiter] = {}
        # Proxy URL currently applied to the session (empty = direct).  Tracked
        # so a runtime change to the ``proxy_url`` setting recreates the session.
        self._proxy_url: str = ""

    def _rate_for(self, url: str) -> RateLimiter:
        host = urlparse(url).hostname or ""
        lim = self._rates.get(host)
        if lim is None:
            lim = RateLimiter(get_settings().request_limit)
            self._rates[host] = lim
        return lim

    async def _ensure(self):
        from ..services.settings_service import get_proxy_url, redact_proxy

        proxy_url = await get_proxy_url()
        if self._session is None or proxy_url != self._proxy_url:
            if self._session is not None:
                try:
                    await self._session.close()
                except Exception:
                    pass
                self._session = None
            from curl_cffi.requests import AsyncSession

            kwargs: dict = {"impersonate": "firefox", "timeout": 30}
            if proxy_url:
                # libcurl understands socks5://, socks5h://, http://, https://.
                kwargs["proxies"] = {"http": proxy_url, "https": proxy_url}
            self._session = AsyncSession(**kwargs)
            self._proxy_url = proxy_url
            log.info(
                "HTTP session created (firefox impersonation, rate=%s r/s, proxy=%s)",
                get_settings().request_limit,
                redact_proxy(proxy_url) or "none",
            )
        return self._session

    async def get(self, url: str, *, params: dict | None = None,
                  headers: dict | None = None, referer: str | None = None,
                  skip_rate: bool = False):
        if not skip_rate:
            await self._rate_for(url).acquire()
        session = await self._ensure()
        h: dict[str, str] = {}
        if referer:
            h["Referer"] = referer
        if headers:
            h.update(headers)
        resp = await session.get(url, params=params, headers=h or None,
                                 allow_redirects=True)
        log.debug("GET %s → %s (%d bytes)", url, resp.status_code, len(resp.content))
        return resp

    async def post(self, url: str, *, data: dict | None = None,
                   headers: dict | None = None, referer: str | None = None,
                   skip_rate: bool = False):
        if not skip_rate:
            await self._rate_for(url).acquire()
        session = await self._ensure()
        h: dict[str, str] = {}
        if referer:
            h["Referer"] = referer
        if headers:
            h.update(headers)
        resp = await session.post(url, data=data, headers=h or None,
                                  allow_redirects=True)
        log.debug("POST %s → %s", url, resp.status_code)
        return resp

    @property
    def cookies(self):
        if self._session is None:
            return {}
        return self._session.cookies

    async def get_cookies(self):
        """Return the session Cookies object, initialising the session first."""
        session = await self._ensure()
        return session.cookies

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None


_client: HttpClient | None = None


def get_http() -> HttpClient:
    global _client
    if _client is None:
        _client = HttpClient()
    return _client


async def close_http() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
