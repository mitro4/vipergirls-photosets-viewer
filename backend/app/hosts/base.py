"""Image-host resolvers — convert interstitial page URLs to direct image URLs.

Each of the 16 supported hosts wraps images in an HTML interstitial page.
The resolvers here fetch that page, extract the real image URL + filename,
and return them for streaming.  imx.to is a special case: its direct image
URL can be computed purely from the thumb_url via string substitution,
so no HTTP request is needed.

Reimplementation of vripper-project's host handlers (vripper-core/.../host/*.kt).
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

import httpx
from bs4 import BeautifulSoup

from ..config import get_settings
from .registry import identify_host

log = logging.getLogger("viper.hosts")

# A resolver takes the interstitial page URL and returns (filename, direct_url).
ResolverFn = Callable[[str], Awaitable[tuple[str, str]]]

# ---------------------------------------------------------------------------
# httpx client for image-host requests (no rate limiting — that's for forum)
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None
# Proxy URL currently applied to the client (empty = direct).  Tracked so a
# runtime change to the ``proxy_url`` setting recreates the client.
_proxy_url: str = ""


async def get_client() -> httpx.AsyncClient:
    global _client, _proxy_url
    from ..services.settings_service import get_proxy_url, redact_proxy

    proxy_url = await get_proxy_url()
    if (
        _client is None
        or _client.is_closed
        or proxy_url != _proxy_url
    ):
        if _client is not None and not _client.is_closed:
            await _client.aclose()
        kwargs: dict = {
            "timeout": httpx.Timeout(connect=10, read=30, write=10, pool=5),
            "follow_redirects": True,
            # HTTP/2 multiplexes image requests on a single TLS connection per
            # host — less TLS/ALPN overhead and head-of-line blocking than a
            # fresh HTTP/1.1 connection per picture. Falls back to HTTP/1.1 via
            # ALPN negotiation when the host doesn't speak h2. Needs h2 (the
            # httpx[http2] extra, declared in backend/requirements.txt).
            "http2": True,
            "headers": {"User-Agent": get_settings().user_agent},
        }
        if proxy_url:
            # Requires httpx[socks] (socksio) for socks5:// / socks5h://.
            kwargs["proxy"] = proxy_url
        _client = httpx.AsyncClient(**kwargs)
        _proxy_url = proxy_url
        log.info("Image-host httpx client created (proxy=%s)",
                 redact_proxy(proxy_url) or "none")
    return _client


async def close_client() -> None:
    global _client, _proxy_url
    if _client is not None:
        await _client.aclose()
        _client = None
    _proxy_url = ""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _fetch_html(url: str, *, referer: str = "") -> BeautifulSoup:
    """GET *url* and return a parsed BeautifulSoup (lxml)."""
    client = await get_client()
    headers: dict[str, str] = {}
    if referer:
        headers["Referer"] = referer
    resp = await client.get(url, headers=headers or None, timeout=10)
    resp.raise_for_status()
    return BeautifulSoup(resp.content, "lxml")


def _filename_from_url(url: str) -> str:
    """Extract a filename from the tail of a URL."""
    tail = url.rsplit("/", 1)[-1]
    # Strip query/fragment
    for sep in ("?", "#"):
        tail = tail.split(sep)[0]
    return tail or "image"


def _ensure_scheme(url: str) -> str:
    """Prefix https: to protocol-relative URLs (//host/...)."""
    if url.startswith("//"):
        return "https:" + url
    return url


# ---------------------------------------------------------------------------
# imx.to — pure URL transform (no HTTP request)
# ---------------------------------------------------------------------------

_IMX_TRANSFORMS: list[tuple[str, str]] = [
    ("https://image.imx.to/u/t/", "https://image.imx.to/u/i/"),
    ("https://imx.to/u/t", "https://image.imx.to/u/i/"),
    ("https://t.imx.to/t/", "https://image.imx.to/u/i/"),
    ("https://imx.to/upload/small/", "https://image.imx.to/u/i/"),
    ("https://i.imx.to/t/", "https://image.imx.to/u/i/"),
]


def resolve_imx(thumb_url: str) -> str:
    """Transform an imx.to thumbnail URL into the direct full-size URL."""
    url = thumb_url.replace("http:", "https:")
    if url.startswith("https://image.imx.to/u/i/"):
        return url
    for prefix, replacement in _IMX_TRANSFORMS:
        if url.startswith(prefix):
            return replacement + url[len(prefix):]
    raise ValueError(f"Cannot find imx.to pattern for {thumb_url}")


def resolve_imx_thumb(thumb_url: str) -> str:
    """Transform any imx.to thumbnail URL into the alive thumb-CDN URL.

    The natural thumb URLs from the forum parser (``imx.to/upload/small/``,
    ``t.imx.to/t/``, …) are intermittently dead — especially the old http://
    apex ones — but ``image.imx.to/u/t/`` is a stable, reachable thumb CDN
    (302 → ``tNN.imx.to/t/``). Used for the *thumb* tier (cards); ``resolve_imx``
    targets ``u/i/`` (the full image) for medium/full.
    """
    cdn = "https://image.imx.to/u/t/"
    url = thumb_url.replace("http:", "https:")
    if url.startswith(cdn):
        return url
    for prefix, _ in _IMX_TRANSFORMS:
        if url.startswith(prefix):
            return cdn + url[len(prefix):]
    raise ValueError(f"Cannot find imx.to thumb pattern for {thumb_url}")


async def _resolve_imx_via_url(url: str) -> tuple[str, str]:
    """Fallback: fetch the imx.to interstitial page and parse."""
    soup = await _fetch_html(url, referer="https://imx.to/")
    img = soup.select_one("img.centred")
    if not img:
        raise ValueError("imx.to: img.centred not found")
    return img.get("alt") or _filename_from_url(url), _ensure_scheme(img.get("src", ""))


# ---------------------------------------------------------------------------
# pixhost.to / pixhost.cc — pure URL transform (no HTTP request)
# ---------------------------------------------------------------------------
# The interstitial show page is pixhost.{to,cc}/show/{album}/{file} but the
# direct image is served from img2.pixhost.to/images/{album}/{file}. Deriving
# the URL by substitution (like imx.to) avoids fetching the show page entirely
# — and crucially avoids depending on DNS for the apex show-page host, which is
# intermittently unreachable from some networks even though the image CDN
# (img*.pixhost.to, same image pool, currently fronted by img2) resolves and
# serves reliably. pixhost.cc is a full mirror of pixhost.to (identical image
# library; img2.pixhost.{to,cc} both serve the same bytes), so both apex
# domains map to the canonical img2.pixhost.to CDN. The HTML resolver below
# remains as a fallback for any URL shape the transform doesn't recognise.

_PIXHOST_SHOW_PREFIXES = (
    "https://www.pixhost.to/show/",
    "https://pixhost.to/show/",
    "https://www.pixhost.cc/show/",
    "https://pixhost.cc/show/",
)


def resolve_pixhost(main_url: str) -> str:
    """Transform a pixhost show-page URL into the direct image URL.

    Handles both the pixhost.to and pixhost.cc mirrors. Already-direct URLs
    (img*.pixhost.{to,cc}/images/...) are returned unchanged. Raises ValueError
    for unrecognised URL shapes.
    """
    url = main_url.replace("http://", "https://")
    # Already a direct image link on either mirror's CDN.
    if "pixhost.to/images/" in url or "pixhost.cc/images/" in url:
        return url
    for prefix in _PIXHOST_SHOW_PREFIXES:
        if url.startswith(prefix):
            # Both mirrors share the same image library; img2.pixhost.to is
            # canonical and resolves reliably (verified across albums/mirrors).
            return "https://img2.pixhost.to/images/" + url[len(prefix):]
    raise ValueError(f"unrecognized pixhost URL: {main_url}")


# ---------------------------------------------------------------------------
# Simple hosts — just GET + parse one CSS selector
# ---------------------------------------------------------------------------

def _simple(selector: str, *, name_attr: str = "alt", src_attr: str = "src",
            referer: str = "") -> ResolverFn:
    """Build a resolver that fetches HTML and extracts one <img> by selector."""

    async def resolve(url: str) -> tuple[str, str]:
        soup = await _fetch_html(url, referer=referer or None)
        img = soup.select_one(selector)
        if not img:
            raise ValueError(f"Element not found: {selector}")
        direct = _ensure_scheme(img.get(src_attr, ""))
        if not direct:
            raise ValueError(f"No {src_attr} attribute in {selector}")
        name = img.get(name_attr) or ""
        return name, direct

    return resolve


# ---------------------------------------------------------------------------
# Complex hosts — continue buttons, cookies, URL rewrites
# ---------------------------------------------------------------------------

async def _resolve_acidimg(url: str) -> tuple[str, str]:
    client = await get_client()
    resp = await client.get(url, timeout=10)
    soup = BeautifulSoup(resp.content, "lxml")

    if soup.select_one("input#continuebutton"):
        resp = await client.post(
            url, data={"imgContinue": "Continue to your image"}, timeout=10,
        )
        soup = BeautifulSoup(resp.content, "lxml")

    img = soup.select_one("img.centred")
    if not img:
        raise ValueError("acidimg: img.centred not found")
    return img.get("alt", ""), _ensure_scheme(img.get("src", ""))


async def _resolve_imagebam(url: str) -> tuple[str, str]:
    client = await get_client()
    resp = await client.get(url, timeout=10)
    if "Continue" in resp.text:
        client.cookies.set("nsfw_inter", "1", domain="imagebam.com")
        client.cookies.set("sfw_inter", "1", domain="imagebam.com")
        resp = await client.get(url, timeout=10)
    soup = BeautifulSoup(resp.content, "lxml")
    img = soup.select_one("img[class*=main-image]")
    if not img:
        raise ValueError("imagebam: img.main-image not found")
    return img.get("alt", ""), _ensure_scheme(img.get("src", ""))


async def _resolve_imagevenue(url: str) -> tuple[str, str]:
    client = await get_client()
    resp = await client.get(url, timeout=10)
    soup = BeautifulSoup(resp.content, "lxml")

    continue_link = soup.select_one("a[title='Continue to ImageVenue']")
    if continue_link and continue_link.get("href"):
        resp = await client.get(continue_link["href"], timeout=10)
        soup = BeautifulSoup(resp.content, "lxml")

    img = soup.select_one("a[data-toggle=full] img#main-image")
    if not img:
        img = soup.select_one("img#main-image")
    if not img:
        raise ValueError("imagevenue: img#main-image not found")
    return img.get("alt", ""), _ensure_scheme(img.get("src", ""))


async def _resolve_imagezilla(url: str) -> tuple[str, str]:
    # URL rewrite: show/ -> images/ gives the direct image
    direct_url = url.replace("/show/", "/images/")
    client = await get_client()
    # Check if the rewritten URL is an image
    head = await client.head(direct_url, timeout=5)
    if head.headers.get("content-type", "").startswith("image/"):
        return _filename_from_url(direct_url), direct_url
    # Fallback: parse the page
    soup = await _fetch_html(url)
    img = soup.select_one("img#photo")
    if not img:
        raise ValueError("imagezilla: img#photo not found")
    return img.get("title") or "", _ensure_scheme(img.get("src", ""))


async def _resolve_pimpandhost(url: str) -> tuple[str, str]:
    # Strip -medium.html, append ?size=original
    clean = url.replace("-medium.html", ".html")
    if "?" not in clean:
        clean += "?size=original"
    else:
        clean += "&size=original"
    soup = await _fetch_html(clean)
    img = soup.select_one("img[class*=original]")
    if not img:
        raise ValueError("pimpandhost: img.original not found")
    return img.get("alt", ""), _ensure_scheme(img.get("src", ""))


async def _resolve_pixhost(url: str) -> tuple[str, str]:
    # Already a direct image link (img-cdn / imgNN .pixhost.{to,cc}/images/...)?
    # Short-circuit: fetching it as "HTML" downloads the whole JPEG into RAM
    # and fails to parse, then the HEAD fallback re-downloads it — a wasted
    # multi-MB round-trip per image that, across a thread, compounds the load
    # on the host.
    if "pixhost.to/images/" in url or "pixhost.cc/images/" in url:
        return _filename_from_url(url), url
    soup = await _fetch_html(url)
    img = soup.select_one("img#image")
    if not img:
        raise ValueError("pixhost: img#image not found")
    # Strip title prefix up to and including first _
    alt = img.get("alt", "")
    if "_" in alt:
        alt = alt.split("_", 1)[1] if "_" in alt else alt
    return alt, _ensure_scheme(img.get("src", ""))


async def _resolve_pixxxels(url: str) -> tuple[str, str]:
    soup = await _fetch_html(url)
    download_link = soup.select_one("#download")
    if download_link and download_link.get("href"):
        direct = _ensure_scheme(download_link["href"])
        return _filename_from_url(direct), direct
    raise ValueError("pixxxels: #download link not found")


async def _resolve_turboimagehost(url: str) -> tuple[str, str]:
    soup = await _fetch_html(url)
    title_el = soup.select_one("div[class*=titleFullS] h1")
    img = soup.select_one("img#imageid")
    if not img:
        raise ValueError("turboimagehost: img#imageid not found")
    name = title_el.get_text(strip=True) if title_el else img.get("alt", "")
    return name, _ensure_scheme(img.get("src", ""))


async def _resolve_viprim(url: str) -> tuple[str, str]:
    soup = await _fetch_html(url, referer="https://vipr.im/")
    img = soup.select_one("img[class*=img]")
    if not img:
        raise ValueError("vipr.im: img.img not found")
    return img.get("alt", ""), _ensure_scheme(img.get("src", ""))


# ---------------------------------------------------------------------------
# Resolver registry
# ---------------------------------------------------------------------------

_RESOLVERS: dict[str, ResolverFn] = {
    "acidimg.cc": _resolve_acidimg,
    "dpic.me": _simple("img#pic"),
    "imagebam.com": _resolve_imagebam,
    "imagetwist.com": _simple("img[class*=img]"),
    "imagevenue.com": _resolve_imagevenue,
    "imagezilla.net": _resolve_imagezilla,
    "imgbox.com": _simple("img#img", name_attr="title"),
    "imgspice.com": _simple("img#imgpreview"),
    "pimpandhost.com": _resolve_pimpandhost,
    "pixhost.to": _resolve_pixhost,
    "pixroute.com": _simple("img#imgpreview"),
    "pixxxels.cc": _resolve_pixxxels,
    "postimg.cc": _simple("img[class*=img-fluid]"),
    "turboimagehost.com": _resolve_turboimagehost,
    "vipr.im": _resolve_viprim,
}

_REFERER_MAP: dict[str, str] = {
    "vipr.im": "https://vipr.im/",
}


def referer_for_host(host: str) -> str:
    """Return the Referer header value needed when downloading from *host*."""
    return _REFERER_MAP.get(host, "")


async def resolve_to_direct(
    main_url: str, thumb_url: str = ""
) -> tuple[str, str]:
    """Resolve an image URL to (filename, direct_image_url).

    For imx.to and pixhost.to the direct URL is computed by a pure string
    transform (no HTTP needed).  For all other hosts the interstitial HTML
    page is fetched and parsed with the host-specific selector.

    If the host is unknown or resolution fails, falls back to returning
    *main_url* as-is (the caller may still get a usable image).
    """
    host = identify_host(main_url)

    # imx.to — pure URL transform (no HTTP request)
    if host == "imx.to":
        source = thumb_url or main_url
        try:
            direct = resolve_imx(source)
            return _filename_from_url(direct), direct
        except ValueError:
            # Thumb URL didn't match known patterns — fall through to HTML parse
            log.warning("imx.to transform failed for %s, trying HTML", source)
            try:
                return await _resolve_imx_via_url(main_url)
            except Exception:
                pass  # fall through to generic

    # pixhost.to / pixhost.cc — pure URL transform (no HTTP request); avoids
    # depending on the apex show-page host whose DNS is intermittently
    # unreachable from some networks, while the image CDN (img2.pixhost.to)
    # resolves reliably. identify_host maps both mirrors to "pixhost.to".
    if host == "pixhost.to":
        try:
            direct = resolve_pixhost(main_url)
            return _filename_from_url(direct), direct
        except ValueError:
            pass  # unrecognized shape — fall through to HTML resolver

    # Dispatch to host-specific resolver
    resolver = _RESOLVERS.get(host)
    if resolver:
        try:
            return await resolver(main_url)
        except Exception as exc:
            log.warning("Resolver for %s failed (%s), trying direct", host, exc)

    # Fallback: HEAD-check the URL — might already be a direct image link.
    # Short timeout: a dead host must not hold the request (and the browser's
    # limited per-host connections) for the full 30s client default.
    try:
        client = await get_client()
        head = await client.head(main_url, timeout=5)
        ct = head.headers.get("content-type", "")
        if ct.startswith("image/"):
            return _filename_from_url(main_url), main_url
    except Exception:
        pass

    # Last resort: return as-is
    return _filename_from_url(main_url), main_url
