"""Runtime settings stored in SQLite — overridable via the UI.

Env vars (config.py) seed the initial defaults **once** — a key absent from
the DB takes its value from the corresponding ``VIPER_*`` var on first load
(see ``_ensure_loaded``). After that the DB row exists and always wins: the
user changes values at runtime through the Settings API, and the env var is
ignored from then on. Values are cached in memory after first load and
invalidated on update.
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote, urlparse, urlunparse

from ..config import get_settings
from ..db import get_db

log = logging.getLogger("viper.settings")

# key → (default, type)
_SCHEMA: dict[str, tuple[object, type]] = {
    "order_images": (False, bool),
    "download_concurrency": (8, int),
    "thread_concurrency": (2, int),
    "download_timeout": (30, int),
    "max_retries": (3, int),
    "forum_proxy": ("", str),
    "proxy_enabled": (True, bool),
    "proxy_url": ("", str),
    "proxy_username": ("", str),
    "proxy_password": ("", str),
    "auto_download": (True, bool),
    "auto_clear_completed": (False, bool),
    # Image-cache LRU trim limit in GB. 0 (default) = unlimited — the cache
    # only grows unless the user opts in. Applied by the maintenance loop.
    "cache_limit_gb": (0.0, float),
}

FORUM_DOMAINS = [
    "https://viper.to",
    "https://vipergirls.to",
    "https://planetviper.club",
    "https://viperbb.rocks",
    "https://viperkats.eu",
    "https://viperohilia.art",
    "https://viperproxy.org",
    "https://vipervault.link",
]

# Runtime keys that can be seeded from env/config on first sight. Only keys
# explicitly present in the environment (or .env) are seeded — pydantic's
# model_fields_set tells us which fields the user actually provided, so an
# unchanged default never writes a row and later code-default changes still
# apply to fresh installs.
_ENV_SEED_KEYS = (
    "download_concurrency",
    "thread_concurrency",
    "download_timeout",
    "max_retries",
    "cache_limit_gb",
)


def _env_seeds() -> dict[str, str]:
    s = get_settings()
    return {
        key: str(getattr(s, key))
        for key in _ENV_SEED_KEYS
        if key in s.model_fields_set
    }

_cache: dict[str, str] = {}
_loaded = False
_lock = asyncio.Lock()


def _coerce(raw: str, default: object, typ: type) -> object:
    if not raw:
        return default
    if typ is bool:
        return raw.lower() in ("true", "1", "yes")
    if typ is int:
        try:
            return int(raw)
        except ValueError:
            return default
    if typ is float:
        try:
            return float(raw)
        except ValueError:
            return default
    return raw


async def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    db = await get_db()
    try:
        cur = await db.execute("SELECT key, value FROM settings")
        rows = {row["key"]: row["value"] for row in await cur.fetchall()}
        await cur.close()
        # Seed keys absent from the DB with explicitly-set env values. This
        # runs at most once per key: once the row exists (seeded here or
        # written by the UI), the DB value wins forever.
        seeds = {k: v for k, v in _env_seeds().items() if k not in rows}
        if seeds:
            for k, v in seeds.items():
                await db.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (k, v),
                )
                rows[k] = v
            await db.commit()
        _cache.update(rows)
        _loaded = True
    finally:
        await db.close()


async def get_setting(key: str):
    """Return the typed value for *key*."""
    async with _lock:
        await _ensure_loaded()
    default, typ = _SCHEMA[key]
    return _coerce(_cache.get(key, ""), default, typ)


async def get_all_settings() -> dict[str, object]:
    async with _lock:
        await _ensure_loaded()
    result: dict[str, object] = {}
    for key, (default, typ) in _SCHEMA.items():
        result[key] = _coerce(_cache.get(key, ""), default, typ)
    # Resolve effective forum proxy
    if not result["forum_proxy"]:
        result["forum_proxy"] = get_settings().forum_base_url
    result["available_domains"] = FORUM_DOMAINS
    return result


async def update_settings(updates: dict[str, object]) -> dict[str, object]:
    async with _lock:
        await _ensure_loaded()
        db = await get_db()
        try:
            for key, value in updates.items():
                if key not in _SCHEMA:
                    continue
                if isinstance(value, bool):
                    val_str = "true" if value else "false"
                else:
                    val_str = str(value)
                await db.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, val_str),
                )
                _cache[key] = val_str
            await db.commit()
        finally:
            await db.close()
    return await get_all_settings()


async def get_forum_base_url() -> str:
    """Return the effective forum base URL (setting or config default)."""
    proxy = await get_setting("forum_proxy")
    if proxy and isinstance(proxy, str):
        return proxy
    return get_settings().forum_base_url


async def get_proxy_url() -> str:
    """Return the proxy URL with credentials embedded (empty = direct).

    Reads ``proxy_enabled`` first — when disabled, returns "" (direct)
    without consuming the stored ``proxy_url`` / credentials, so the user
    can toggle the proxy back on without re-entering them.  Otherwise
    composes ``socks5h://user:pass@host:port`` from ``proxy_url`` plus
    optional ``proxy_username`` / ``proxy_password``.  Both curl_cffi
    (libcurl) and httpx (via socksio) accept credentials in the URL.

    A ``socks5://`` scheme is normalised to ``socks5h://`` (DNS via the
    proxy).  With plain socks5, libcurl resolves hostnames LOCALLY and only
    the connection goes through the proxy — when the site is blocked by DNS
    (the typical reason for using a proxy here) the local resolver returns
    a poisoned/unreachable IP and the proxied connection dies with a
    timeout.  httpx always passes the hostname to the SOCKS server
    (ATYP=3), so the rewrite is a no-op for it semantically.

    A bare ``host:port`` (no scheme) defaults to SOCKS5 — the user never
    has to know about socks5h:// or even type a scheme.
    """
    if not await get_setting("proxy_enabled"):
        return ""
    base = ((await get_setting("proxy_url")) or "").strip()
    if not base:
        return ""
    if "://" not in base:
        base = "socks5://" + base
    if base.lower().startswith("socks5://"):
        base = "socks5h://" + base[len("socks5://"):]
    username = (await get_setting("proxy_username")) or ""
    if not username:
        return base
    password = (await get_setting("proxy_password")) or ""
    p = urlparse(base)
    creds = quote(username, safe="")
    if password:
        creds += ":" + quote(password, safe="")
    host = p.hostname or ""
    if p.port:
        host = f"{host}:{p.port}"
    netloc = f"{creds}@{host}"
    return urlunparse((p.scheme, netloc, p.path, p.params, p.query, p.fragment))


def redact_proxy(url: str) -> str:
    """Strip credentials from a proxy URL for safe logging."""
    if not url or "@" not in url:
        return url
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    netloc, slash, path = rest.partition("/")
    if "@" in netloc:
        _, _, host = netloc.partition("@")
        rebuilt = f"{scheme}://{host}"
        if slash:
            rebuilt += "/" + path
        return rebuilt
    return url
