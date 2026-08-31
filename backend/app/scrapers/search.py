"""Forum search via vBulletin 4 Advanced Search (search.php).

Flow:
  1. POST ``search.php?do=process`` with the query, selected forum ids and the
     result mode (threads vs posts). vBulletin answers with a 302 to
     ``search.php?searchid=<id>``; the body of the redirected page embeds the
     ``searchid`` (it is a stored DB row, so it is reusable for paging).
   2. Subsequent pages are fetched with ``search.php?searchid=<id>&page=<N>``.

Scope: vBulletin's do=process cannot filter on every sidebar forum at once
(passing all ids yields no searchid, and top-level *category* ids do not
expand into their children). Only batches of leaf forums are honoured reliably,
up to ~8-9 ids per request. We therefore emulate a sidebar-scoped search by
fanning the query out across several leaf-forum batches (see
``forums.SEARCH_SCOPES``) and k-way-merging the per-batch result streams by
date. An explicitly-scoped search (one or more categories selected) expands
those categories to their leaf forums and batches them the same way. The
searchid from each batch is reusable, so pages 2+ only fetch what each stream
has consumed.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..config import get_settings
from ..forums import ALL_FORUM_IDS, SEARCH_SCOPES, TOP_CATEGORY_IDS, ForumNode, get_node
from .http import RateLimiter, get_http

log = logging.getLogger("viper.search")

# Search requests bypass the global request limiter (which is tuned for forum
# browsing courtesy) and use a slightly faster dedicated limiter instead, since
# an unscoped search issues several sequential do=process/showresults calls.
_search_rate = RateLimiter(get_settings().search_request_limit)
# vBulletin stores the result of each do=process in its DB keyed by searchid,
# but issuing several do=process calls from the same session too quickly
# corrupts the in-flight redirect state — so we serialise just the POSTs.
_process_lock = asyncio.Lock()

THREAD_ID_RE = re.compile(r"threads/(\d+)")
POST_ID_RE = re.compile(r"[?&]p=(\d+)")
SEARCHID_RE = re.compile(r"searchid=(\d+)")
# Forum of a result thread lives in the "threadpostedin" block:
#   <div class="threadpostedin td"><a href="forums/304-Hardcore-Photo-Sets">…
FORUM_LINK_RE = re.compile(r'forums/(\d+)')
SECURITYTOKEN_RE = re.compile(r'SECURITYTOKEN\s*=\s*"([0-9a-f-]+)"')
SECURITYTOKEN_INPUT_RE = re.compile(r'name="securitytoken"\s+value="([0-9a-f-]+)"')
PAGE_OF_RE = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)", re.I)
# "Results 1 to 50 of 1234" — the exact per-batch match count. The batches are
# disjoint, so summing this across batches gives the exact merged total.
RESULTS_COUNT_RE = re.compile(r"Results\s+\d+\s+to\s+\d+\s+of\s+([\d,]+)", re.I)
TITLE_ONLY_RE = re.compile(r"thread_title_(\d+)")
REPLIES_RE = re.compile(r"Replies?:\s*([\d,]+)", re.I)
VIEWS_RE = re.compile(r"Views?:\s*([\d,]+)", re.I)
# "Started by NAME, DATE [TIME]" — applied ONLY to the threadmeta <span class="label">
# text, never to the whole container (which would greedily swallow
# Replies/Views/Last-Post/Forum into the date).
STARTED_LINE_RE = re.compile(r"Started by\s+(.+?)\s*,\s*(.+)", re.I | re.S)
SKIP_TITLES = frozenset({"last post", "go to last post", "reply", "view", "permalink"})

# vBulletin results per page (used to slice the merged stream).
_PAGE_SIZE = 60
# Cards shown per UI page (matches forumdisplay.PER_PAGE). The merge stream is
# sliced into _UI_PER_PAGE-wide pages on top of the _PAGE_SIZE-wide blocks.
_UI_PER_PAGE = 12
# Maximum leaf-forum ids per do=process request (vBulletin rejects larger
# batches with no searchid).
_MAX_BATCH = 8

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_VB_DATE_REL_RE = re.compile(r"(today|yesterday)\b\s*(\d{1,2}):(\d{2})?", re.I)
_VB_DATE_FULL_RE = re.compile(
    r"(\d{1,2})\w*\s+([A-Za-z]+)\s+(\d{4})(?:\s+(\d{1,2}):(\d{2}))?"
)


def _parse_vb_date(s: str) -> float:
    """Parse a vBulletin human date string ("Today 14:30", "Yesterday",
    "2nd August 2025 07:27") to epoch seconds. Returns 0 if unparseable, so
    undated results sort last under descending order and first under ascending."""
    if not s:
        return 0.0
    s = s.strip()
    m = _VB_DATE_REL_RE.match(s)
    if m:
        now = datetime.datetime.now()
        d = now if m.group(1).lower() == "today" else now - datetime.timedelta(days=1)
        try:
            d = d.replace(hour=int(m.group(2)), minute=int(m.group(3)),
                          second=0, microsecond=0)
        except (ValueError, TypeError):
            pass
        return d.timestamp()
    m = _VB_DATE_FULL_RE.search(s)
    if m:
        mon = _MONTHS.get(m.group(2).lower())
        if mon:
            try:
                d = datetime.datetime(int(m.group(3)), mon, int(m.group(1)),
                                      int(m.group(4) or 0), int(m.group(5) or 0))
                return d.timestamp()
            except ValueError:
                pass
    return 0.0


def _find_thread_container(anchor):
    """Walk up the DOM to the thread row/list-item (mirrors forumdisplay)."""
    for parent in anchor.parents:
        if parent.name in ("li", "tr"):
            pid = parent.get("id", "")
            if pid.startswith("thread_"):
                return parent
            if parent.select_one("a[href]") and THREAD_ID_RE.search(
                parent.select_one("a[href]").get("href", "") or ""
            ):
                return parent
        if parent.name in ("ol", "table"):
            break
    return anchor.find_parent(["li", "tr"])


@dataclass
class SearchResultItem:
    thread_id: int
    title: str
    forum_id: int = 0
    author: str = ""
    posted_at: str = ""
    replies: int = 0
    views: int = 0
    post_id: int = 0  # >0 in posts mode
    url: str = ""


@dataclass
class SearchPage:
    query: str
    mode: str
    page: int
    total_pages: int
    total_results: int = 0
    searchid: str = ""
    results: list[SearchResultItem] = field(default_factory=list)


async def _get_securitytoken(base: str) -> str:
    """Fetch the vBulletin securitytoken (guest or logged-in) from the search
    form. Required by do=process; without it the forum filter is ignored."""
    resp = await get_http().get(f"{base}/search.php")
    if resp.status_code != 200:
        return ""
    m = SECURITYTOKEN_RE.search(resp.text)
    if not m:
        m = SECURITYTOKEN_INPUT_RE.search(resp.text)
    return m.group(1) if m else ""


async def _submit_process(base: str, token: str, forum_ids: list[int], mode: str, query: str, order: str = "descending") -> str | None:
    """POST do=process and return the resulting searchid.

    Returns ``None`` when the server reports no matches (HTTP 200 but no
    searchid in the body) — this is a normal empty result, not an error.
    Raises ``RuntimeError`` only on a non-200 response.
    """
    # Build as a list of (key, value) tuples: vBulletin expects the forum
    # filter as repeated ``forumchoice[]`` keys, and curl_cffi mis-serialises
    # a dict with a list value, so we append each forum explicitly.
    data: list[tuple[str, object]] = [
        ("do", "process"),
        ("query", query),
        ("showposts", "1" if mode == "posts" else "0"),
        ("titleonly", "0"),
        # 0 = "Any Date" (search over all time; the form defaults to this).
        ("searchdate", "0"),
        ("childforums", "1"),
        ("contenttypeid", "1"),
        ("searchfromtype", "vBForum:Post"),
        ("beforeafter", "after"),
        ("sortby", "dateline"),
        # "descending" = newest first, "ascending" = oldest first.
        ("order", order),
        ("saveprefs", "1"),
        ("dosearch", "Search Now"),
    ]
    if token:
        data.append(("securitytoken", token))
    for fid in forum_ids:
        data.append(("forumchoice[]", fid))

    # Serialise do=process POSTs across the whole process (vBulletin session
    # state corrupts under concurrent searches) and use the dedicated limiter.
    async with _process_lock:
        await _search_rate.acquire()
        resp = await get_http().post(f"{base}/search.php", data=data, skip_rate=True)
    if resp.status_code != 200:
        raise RuntimeError(f"search.php?do=process → HTTP {resp.status_code}")
    m = SEARCHID_RE.search(resp.text)
    return m.group(1) if m else None


async def _fetch_results_page(searchid: str, page: int) -> str:
    from ..services.settings_service import get_forum_base_url

    base = await get_forum_base_url()
    params: dict[str, object] = {"do": "showresults", "searchid": searchid}
    if page > 1:
        params["page"] = page
    # showresults is a read-only lookup keyed by an explicit searchid, so it
    # is safe to run concurrently with other requests — but still respect the
    # dedicated search limiter and bypass the (slower) global one.
    await _search_rate.acquire()
    resp = await get_http().get(f"{base}/search.php", params=params, skip_rate=True)
    if resp.status_code != 200:
        raise RuntimeError(f"search.php?do=showresults → HTTP {resp.status_code}")
    return resp.text


def _parse_results(html: str, mode: str, searchid: str) -> SearchPage:
    soup = BeautifulSoup(html, "lxml")
    base = get_settings().forum_base_url

    total_pages = 1
    total_results = 0
    for text in soup.stripped_strings:
        m = PAGE_OF_RE.search(text)
        if m:
            total_pages = int(m.group(2))
        m = RESULTS_COUNT_RE.search(text)
        if m:
            total_results = int(m.group(1).replace(",", ""))
    # A single-page result set has no "Page X of Y" bar; infer it from the count.
    if total_pages == 1 and total_results:
        total_pages = max(1, (total_results + _PAGE_SIZE - 1) // _PAGE_SIZE)

    results: list[SearchResultItem] = []
    seen: set[int] = set()

    # Anchor links carry both the thread id (in href) and the title text,
    # plus a stable id="thread_title_<id>" in threads mode.
    if mode == "posts":
        # In posts mode each thread appears twice: a bare title link and a
        # post link carrying ?p=<postid>. Keep only the post links and dedup
        # by (thread_id, post_id) so every hit is a distinct post.
        anchors = [
            a for a in soup.find_all("a", href=True)
            if THREAD_ID_RE.search(a["href"]) and POST_ID_RE.search(a["href"])
        ]
        dedup_key = lambda tid, pid: (tid, pid)
    else:
        # Threads mode: use the title anchors; ignore the duplicate post links.
        anchors = soup.select("a.title, a[id^='thread_title_']")
        if not anchors:
            anchors = [
                a for a in soup.find_all("a", href=True)
                if THREAD_ID_RE.search(a["href"]) and not POST_ID_RE.search(a["href"])
            ]
        dedup_key = lambda tid, pid: tid

    for a in anchors:
        href = a.get("href", "")
        tm = THREAD_ID_RE.search(href)
        if not tm:
            continue
        tid = int(tm.group(1))
        pm = POST_ID_RE.search(href)
        pid = int(pm.group(1)) if pm else 0
        if dedup_key(tid, pid) in seen:
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 3 or title.lower() in SKIP_TITLES:
            continue
        item = SearchResultItem(
            thread_id=tid,
            title=title,
            url=urljoin(base, href),
        )
        item.post_id = pid
        # Walk up to the thread row/list-item and extract metadata, mirroring
        # the forumdisplay parser (vB4 search result rows reuse the same markup).
        container = _find_thread_container(a)
        if container is not None:
            ctext = container.get_text(" ", strip=True)
            flink = container.select_one('a[href^="forums/"]')
            if flink:
                fm = FORUM_LINK_RE.search(flink.get("href", "") or "")
                if fm:
                    item.forum_id = int(fm.group(1))
            m = REPLIES_RE.search(ctext)
            if m:
                item.replies = int(m.group(1).replace(",", ""))
            m = VIEWS_RE.search(ctext)
            if m:
                item.views = int(m.group(1).replace(",", ""))
            # Author + post date live in the threadmeta "Started by NAME, DATE"
            # label. Parsing it off the *whole* container text would greedily
            # attach Replies/Views/Last-Post/Forum to posted_at, so we target
            # the <span class="label"> (or .threadmeta) block specifically.
            meta = container.select_one(".threadmeta") or container
            label = meta.select_one("span.label")
            if label is not None:
                ltext = label.get_text(" ", strip=True)
                ms = STARTED_LINE_RE.search(ltext)
                if ms:
                    item.author = ms.group(1).strip()
                    item.posted_at = re.sub(r"\s+", " ", ms.group(2)).strip()
            if not item.author:
                uname = meta.select_one("a.username")
                if uname:
                    item.author = uname.get_text(strip=True)
            if not item.author:
                for la in container.find_all("a", href=True):
                    if "member.php" in la["href"] or "/members/" in la["href"]:
                        nm = la.get_text(strip=True)
                        if nm:
                            item.author = nm
                            break
        seen.add(dedup_key(tid, pid))
        results.append(item)

    return SearchPage(
        query="",
        mode=mode,
        page=1,
        total_pages=total_pages,
        total_results=total_results,
        searchid=searchid,
        results=results,
    )


def _descendant_leaves(fid: int) -> set[int]:
    """Return the thread-bearing leaf forums under *fid* (or *fid* itself if it
    is a leaf). Pure-container category ids are excluded because vBulletin does
    not expand them server-side."""
    node = get_node(fid)
    out: set[int] = set()

    def _walk(n: ForumNode) -> None:
        if n.forum_id not in TOP_CATEGORY_IDS and n.forum_id in ALL_FORUM_IDS:
            out.add(n.forum_id)
        for c in n.children:
            _walk(c)

    if node:
        _walk(node)
    elif fid in ALL_FORUM_IDS and fid not in TOP_CATEGORY_IDS:
        out.add(fid)
    return out


def _resolve_scopes(forum_ids: list[int]) -> list[list[int]]:
    """Return the leaf-forum batches to search.

    Unscoped (``forum_ids`` empty) → the pre-tuned ``SEARCH_SCOPES`` covering
    every sidebar forum. Scoped → expand each selected category/forum to its
    leaves and chunk into batches of at most ``_MAX_BATCH`` (vBulletin rejects
    larger batches). Every batch is disjoint, so no per-result client filter is
    needed and the per-batch ``total_pages`` sum exactly to the global count.
    """
    if not forum_ids:
        return [list(s) for s in SEARCH_SCOPES]
    leaves: set[int] = set()
    for fid in forum_ids:
        leaves |= _descendant_leaves(fid)
    ordered = sorted(leaves)
    if not ordered:
        return []
    return [ordered[i:i + _MAX_BATCH] for i in range(0, len(ordered), _MAX_BATCH)]


class _SearchSession:
    """K-way-merge of several vBulletin per-batch result streams.

    On first use ``_init`` runs one ``do=process`` per batch (serialised via
    ``_process_lock``) and primes page 1 of each, recording the per-batch
    ``total_pages``. ``get_page(N)`` lazily fills a globally date-sorted
    ``merged`` list (popping the best-dated head across batches, fetching the
    next page from a batch when its stream runs dry) until it can slice out
    the requested page. The searchids are reusable, so pages 2+ only fetch what
    each batch stream has consumed.
    """

    def __init__(self, query: str, mode: str, order: str,
                 scopes: list[list[int]]) -> None:
        self.query = query
        self.mode = mode
        self.order = order  # "descending" (newest first) or "ascending"
        self.scopes = scopes
        n = len(scopes)
        self.searchids: list[str | None] = [None] * n
        self.batch_total_results: list[int] = [0] * n
        self.streams: list[list[SearchResultItem]] = [[] for _ in range(n)]
        self.pos: list[int] = [0] * n
        self.pages_fetched: list[int] = [0] * n
        self.done: list[bool] = [False] * n
        self.merged: list[SearchResultItem] = []
        self._seen: set[int] = set()
        self.merged_done = False
        self.created_at = time.monotonic()
        self._initialized = False
        self._init_lock = asyncio.Lock()
        # Serialises merge mutation: _fill awaits network I/O, so two concurrent
        # get_page calls on the same session would interleave and corrupt the
        # shared stream/merge state.
        self._fill_lock = asyncio.Lock()

    async def init_once(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await self._init()

    async def _init(self) -> None:
        from ..services.settings_service import get_forum_base_url

        base = await get_forum_base_url()
        token = await _get_securitytoken(base)
        # Phase 1 — obtain a searchid per batch. do=process calls MUST be
        # serialised (vBulletin corrupts concurrent searches), which _process_lock
        # does inside _submit_process.
        for i, scope in enumerate(self.scopes):
            try:
                sid = await _submit_process(base, token, scope, self.mode,
                                            self.query, self.order)
            except RuntimeError as e:
                log.warning("search batch %s failed: %s", scope, e)
                sid = None
            self.searchids[i] = sid
            if sid is None:
                self.done[i] = True
        # Phase 2 — prime page 1 of each batch concurrently. showresults is a
        # read-only lookup keyed by an explicit searchid, so it is safe to run
        # in parallel (the _search_rate limiter still spaces the calls).
        await asyncio.gather(*(self._fetch_next(i)
                               for i in range(len(self.scopes))
                               if not self.done[i]))
        self._initialized = True

    async def _fetch_next(self, i: int) -> None:
        """Fetch the next page of batch *i* and append results to its stream."""
        if self.done[i] or self.searchids[i] is None:
            return
        self.pages_fetched[i] += 1
        p = self.pages_fetched[i]
        try:
            html = await _fetch_results_page(self.searchids[i], p)
        except RuntimeError as e:
            log.warning("search batch %s page %d fetch failed: %s",
                        self.scopes[i], p, e)
            self.done[i] = True
            return
        pg = _parse_results(html, self.mode, self.searchids[i] or "")
        if self.batch_total_results[i] == 0:
            self.batch_total_results[i] = pg.total_results or len(pg.results)
        if not pg.results:
            self.done[i] = True
            return
        self.streams[i].extend(pg.results)
        # vBulletin pads the last page or reports it via "of N"; stop once we
        # have fetched every result this batch reported.
        if len(self.streams[i]) >= self.batch_total_results[i]:
            self.done[i] = True

    def _key(self, item: SearchResultItem) -> tuple[int]:
        # Sort by the monotonic id that reflects the result's date: thread_id
        # in threads mode (thread creation date), post_id in posts mode (the
        # matched post's date). Both increase with time, so this avoids the
        # fragile human date-string parsing that used to jumble the merge when
        # dates failed to parse (returned 0.0) or only had day granularity.
        # vBulletin sorts each batch stream by dateline, which matches id order.
        oid = item.post_id if item.post_id else item.thread_id
        return (-oid,) if self.order == "descending" else (oid,)

    async def _fill(self, n: int) -> None:
        """Grow ``merged`` until it holds at least *n* items (or all batches
        are exhausted)."""
        if self.merged_done:
            return
        nscopes = len(self.scopes)
        while len(self.merged) < n:
            best_i = -1
            best_key: tuple[float, int] | None = None
            for i in range(nscopes):
                if self.pos[i] >= len(self.streams[i]):
                    if not self.done[i]:
                        await self._fetch_next(i)
                    if self.pos[i] >= len(self.streams[i]):
                        continue  # batch exhausted
                cand = self.streams[i][self.pos[i]]
                k = self._key(cand)
                if best_key is None or k < best_key:
                    best_key = k
                    best_i = i
            if best_i < 0:
                self.merged_done = True
                break
            winner = self.streams[best_i][self.pos[best_i]]
            self.pos[best_i] += 1
            # Defensive dedup (batches are disjoint, but a guest session could
            # return overlapping global results).
            if winner.thread_id in self._seen:
                continue
            self._seen.add(winner.thread_id)
            self.merged.append(winner)

    @property
    def total_pages(self) -> int:
        """Exact global page count. The batches are disjoint, so the merged
        total equals the sum of per-batch result counts; each page holds
        ``_PAGE_SIZE`` items."""
        total = sum(self.batch_total_results)
        return max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE) if total else 1

    @property
    def total_results(self) -> int:
        """Total merged result count (sum of disjoint per-batch counts)."""
        return sum(self.batch_total_results)

    async def get_page(self, page: int) -> list[SearchResultItem]:
        await self.init_once()
        async with self._fill_lock:
            await self._fill(page * _PAGE_SIZE)
            start = (page - 1) * _PAGE_SIZE
            return self.merged[start:start + _PAGE_SIZE]


# Cached sessions keyed by (query, mode, order, scopes). Searchids are reusable
# for a short window, so paging back/forward or switching sort temporarily reuses
# a session instead of re-running do=process for every batch.
_session_cache: dict[tuple, _SearchSession] = {}
_SESSION_TTL = 120.0


async def _get_session(query: str, mode: str, order: str,
                       scopes: list[list[int]]) -> _SearchSession:
    key = (query.lower(), mode, order,
           tuple(tuple(s) for s in scopes))
    now = time.monotonic()
    # Expire stale sessions.
    for k in list(_session_cache):
        if now - _session_cache[k].created_at > _SESSION_TTL:
            del _session_cache[k]
    sess = _session_cache.get(key)
    if sess is None:
        sess = _SearchSession(query, mode, order, scopes)
        _session_cache[key] = sess
    return sess


async def search_forum(
    query: str,
    forum_ids: list[int],
    mode: str = "threads",
    page: int = 1,
    order: str = "descending",
) -> SearchPage:
    """Run a forum search and return one page of results.

    ``forum_ids`` are the selected categories/forums (top-level category ids or
    specific forum ids); their descendant *leaf* forums are batched and searched
    server-side. An empty ``forum_ids`` searches every sidebar forum (via
    ``forums.SEARCH_SCOPES``). ``mode`` is ``"threads"`` or ``"posts"``.
    ``page`` is 1-based. ``order`` is ``"descending"`` (newest first) or
    ``"ascending"`` (oldest first).
    """
    query = query.strip()
    if len(query) < 2:
        return SearchPage(query=query, mode=mode, page=page, total_pages=1,
                          results=[])

    scopes = _resolve_scopes(forum_ids)
    if not scopes:
        return SearchPage(query=query, mode=mode, page=page, total_pages=1,
                          results=[])

    session = await _get_session(query, mode, order, scopes)
    # The k-way merge materialises in _PAGE_SIZE (60) blocks, but the UI shows
    # _UI_PER_PAGE (12) cards per page. Map the UI page onto the merge stream:
    #   ui 1..5 → merge block 1 (offsets 0..48), ui 6..10 → merge block 2, …
    blocks_per_merge = _PAGE_SIZE // _UI_PER_PAGE  # 5
    merge_page = (page - 1) // blocks_per_merge + 1
    offset = ((page - 1) * _UI_PER_PAGE) % _PAGE_SIZE
    merged = await session.get_page(merge_page)
    results = merged[offset:offset + _UI_PER_PAGE]
    # Defensive: guarantee the page is internally ordered by the same id key,
    # in case the k-way merge drifted across streams.
    results.sort(
        key=lambda it: it.post_id or it.thread_id,
        reverse=(order == "descending"),
    )
    ui_total_pages = max(
        1, (session.total_results + _UI_PER_PAGE - 1) // _UI_PER_PAGE
    )
    return SearchPage(
        query=query,
        mode=mode,
        page=page,
        total_pages=ui_total_pages,
        results=results,
    )
