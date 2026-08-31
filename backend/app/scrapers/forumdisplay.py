"""Parse vBulletin 4 forum thread-listing pages.

URL: {forum_base_url}/forumdisplay.php?f=<forum_id>[&page=<N>]
Each page lists ~25 threads with: id, title, prefix, author, date, replies, views.

Parsing is defensive: vBulletin 4 theming varies, so we anchor on the
universal thread-link pattern (showthread.php?<id> or threads/<id>-)
and extract metadata from the surrounding container via regex.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..config import get_settings
from .http import get_http

log = logging.getLogger("viper.forumdisplay")

THREAD_ID_RE = re.compile(r"(?:threads/|showthread\.php\?)(\d+)")
PAGE_OF_RE = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)", re.I)
RESULTS_RE = re.compile(r"Results\s+(\d+)\s+to\s+(\d+)\s+of\s+([\d,]+)", re.I)
SKIP_TITLES = frozenset({
    "last post", "go to last post", "reply", "view",
    "permalink", "bookmark & share", "more",
})

# IMPORTANT-prefixed threads are section rules/guidelines (no images). vBulletin
# lists them at the top of page 1 and counts them toward the pp=PER_PAGE limit,
# so they would crowd out real photo sets — after the downstream non-photoset
# filter drops them, only a few cards remain. Skipping them here (before the
# PER_PAGE truncation) keeps the slots for actual photo sets.
_IMPORTANT_PREFIX_RE = re.compile(r"^\*?\s*important\b", re.I)
_IMPORTANT_TITLE_RE = re.compile(r"^\s*\[?\*?\s*IMPORTANT\b", re.I)


@dataclass
class ThreadListItem:
    thread_id: int
    title: str
    forum_id: int
    prefix: str = ""
    author: str = ""
    posted_at: str = ""
    replies: int = 0
    views: int = 0
    url: str = ""


@dataclass
class ForumPage:
    forum_id: int
    page: int
    total_pages: int
    total_threads: int
    threads: list[ThreadListItem] = field(default_factory=list)


def _find_thread_container(anchor):
    """Walk up the DOM to the thread row/list-item."""
    for parent in anchor.parents:
        if parent.name in ("li", "tr"):
            pid = parent.get("id", "")
            if pid.startswith("thread_"):
                return parent
            # If no id match, still accept li/tr that contain a thread link
            if parent.select_one("a[href]") and THREAD_ID_RE.search(
                parent.select_one("a[href]").get("href", ""
            ) or ""):
                return parent
        if parent.name in ("ol", "table"):
            break
    # Fallback: nearest li/tr
    return anchor.find_parent(["li", "tr"])


def _has_sticky_token(ident: str | None, classes) -> bool:
    """True if the id/class attribute set contains the word 'sticky'."""
    blob = ((ident or "") + " " + " ".join(classes or [])).lower()
    return "sticky" in blob


def _is_sticky(container) -> bool:
    """True if the thread row is a vBulletin sticky/pinned thread.

    Most vBulletin 4 themes render stickies in a dedicated
    ``<ol id="stickies">`` (or ``<tbody class="...sticky...">``), but some
    styles keep them inside the main list and tag the row with a ``sticky``
    class. Detect both, otherwise leaked stickies push the per-page count past
    PER_PAGE (they appear on every page of the listing).
    """
    if container is None:
        return False
    if _has_sticky_token(container.get("id"), container.get("class")):
        return True
    parent_list = container.find_parent(["ol", "ul", "tbody", "table"])
    return parent_list is not None and _has_sticky_token(
        parent_list.get("id"), parent_list.get("class")
    )


def _is_important(item: ThreadListItem) -> bool:
    """True for announcement/rules threads carrying an IMPORTANT marker.

    These are moderator-tagged stickies (guidelines, request threads, index
    posts) that contain no photoset images. vBulletin lists them at the top of
    page 1 and counts them toward ``pp=PER_PAGE``; without this skip they would
    crowd out real photo sets and leave too few cards after filtering.
    """
    if item.prefix and _IMPORTANT_PREFIX_RE.search(item.prefix):
        return True
    if item.title and _IMPORTANT_TITLE_RE.search(item.title):
        return True
    return False


def _extract_meta(container, item: ThreadListItem) -> None:
    if container is None:
        return
    text = container.get_text(" ", strip=True)

    m = re.search(r"Replies?:\s*([\d,]+)", text, re.I)
    if m:
        item.replies = int(m.group(1).replace(",", ""))

    m = re.search(r"Views?:\s*([\d,]+)", text, re.I)
    if m:
        item.views = int(m.group(1).replace(",", ""))

    # Author — first member link
    for a in container.find_all("a", href=True):
        href = a["href"]
        if "member.php" in href or "/members/" in href:
            name = a.get_text(strip=True)
            if name:
                item.author = name
                break

    # Post date — parse the threadmeta "Started by NAME, DATE" label. The whole
    # container text would greedily attach Replies/Views/Last-Post to the date,
    # so we target the <span class="label"> block specifically (same vB4 markup
    # as the search results page).
    meta = container.select_one(".threadmeta") or container
    label = meta.select_one("span.label")
    if label is not None:
        ltext = label.get_text(" ", strip=True)
        m = re.search(r"Started by\s+.+?\s*,\s*(.+)", ltext, re.I | re.S)
        if m:
            item.posted_at = re.sub(r"\s+", " ", m.group(1)).strip()

    # Prefix
    for el in container.select(".prefix, .threadprefix, .prefixfield, .label"):
        val = el.get_text(strip=True)
        if not val or len(val) >= 40:
            continue
        # The threadmeta "Started by …" line also carries class "label"; skip it.
        if val.lower().startswith("started by"):
            continue
        item.prefix = val
        break


def parse_forum_html(html: str, forum_id: int, page: int) -> ForumPage:
    soup = BeautifulSoup(html, "lxml")
    base = get_settings().forum_base_url

    total_pages = page
    total_threads = 0
    for text in soup.stripped_strings:
        if total_pages == page:
            m = PAGE_OF_RE.search(text)
            if m:
                total_pages = int(m.group(2))
        if total_threads == 0:
            m = RESULTS_RE.search(text)
            if m:
                total_threads = int(m.group(3).replace(",", ""))

    threads: list[ThreadListItem] = []
    seen: set[int] = set()

    # Prefer the canonical thread-title anchors (class "title" / id
    # "thread_title_<id>"). These appear in document order within the main
    # thread list and are NOT duplicated by the bottom pagination/nav links,
    # so the resulting order matches the forum's "date added" order. Fall back
    # to a global <a> scan only if no title anchors are found.
    anchors = soup.select("a.title, a[id^='thread_title_']")
    if not anchors:
        anchors = soup.find_all("a", href=True)

    for a in anchors:
        m = THREAD_ID_RE.search(a["href"])
        if not m:
            continue
        tid = int(m.group(1))
        if tid in seen:
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 3:
            continue
        if title.lower() in SKIP_TITLES:
            continue
        seen.add(tid)

        item = ThreadListItem(
            thread_id=tid,
            title=title,
            forum_id=forum_id,
            url=urljoin(base, a["href"]),
        )
        container = _find_thread_container(a)
        _extract_meta(container, item)
        # Skip sticky/pinned threads — they repeat on every page and would
        # inflate the count past PER_PAGE. vBulletin themes vary, so detect
        # both a dedicated stickies list and a sticky class on the row itself.
        if _is_sticky(container):
            continue
        # Skip announcement/rules threads tagged IMPORTANT: they carry no
        # photoset content but consume PER_PAGE slots (vB lists them at the
        # top of page 1), which would leave too few real photo sets after the
        # downstream non-photoset filter drops them.
        if _is_important(item):
            continue
        threads.append(item)

    # Guarantee the per-page cap: vBulletin should honour pp=PER_PAGE, but a
    # stray sticky/related section could still slip through the filters above.
    if len(threads) > PER_PAGE:
        log.warning(
            "forumdisplay f=%s page=%d parsed %d threads (>PER_PAGE=%d); truncating",
            forum_id, page, len(threads), PER_PAGE,
        )
        threads = threads[:PER_PAGE]

    log.info(
        "forumdisplay f=%s page=%d → %d threads (total_pages=%d)",
        forum_id, page, len(threads), total_pages,
    )
    return ForumPage(
        forum_id=forum_id,
        page=page,
        total_pages=max(total_pages, page),
        total_threads=total_threads,
        threads=threads,
    )


SORT_PARAMS = {
    "new": {"sort": "dateline", "order": "desc"},
    "old": {"sort": "dateline", "order": "asc"},
}

# Threads per listing page (vBulletin honours the `pp` query param). A smaller
# page keeps the grid light and lets all card images load at once.
PER_PAGE = 12


async def fetch_forum_page(
    forum_id: int, page: int, *, sort: str = "default"
) -> ForumPage:
    """Fetch and parse one page of a forum's thread listing.

    sort: "default" = forum natural order (last post), "new" = newest
    threads first (dateline desc), "old" = oldest first (dateline asc).
    """
    from ..services.settings_service import get_forum_base_url

    base = await get_forum_base_url()
    # daysprune=-1 = "from the beginning" (show ALL threads). Without this,
    # vBulletin's forum default (100 days of recent activity) silently limits
    # the listing, so "oldest first" returned recently-bumped old threads
    # instead of the truly oldest ones.
    params: dict[str, str | int] = {"f": forum_id, "pp": PER_PAGE, "daysprune": -1}
    if page > 1:
        params["page"] = page
    params.update(SORT_PARAMS.get(sort, {}))
    url = f"{base}/forumdisplay.php"
    resp = await get_http().get(url, params=params)
    if resp.status_code != 200:
        raise RuntimeError(
            f"forumdisplay f={forum_id} page={page} sort={sort} "
            f"→ HTTP {resp.status_code}"
        )
    return parse_forum_html(resp.text, forum_id, page)
