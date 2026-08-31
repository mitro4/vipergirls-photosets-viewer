"""Pydantic response schemas."""
from __future__ import annotations

from pydantic import BaseModel


class CategoryOut(BaseModel):
    forum_id: int
    title: str
    slug: str
    parent_id: int | None
    group: str
    thread_count: int = 0
    # Nested sub-forums (e.g. an Archive) shown indented under this forum.
    children: list["CategoryOut"] = []


CategoryOut.model_rebuild()


class CategoryGroupOut(BaseModel):
    name: str
    forum_id: int | None
    categories: list[CategoryOut]


class ForumConfigOut(BaseModel):
    """Public runtime configuration exposed to the UI."""

    forum_url: str
    click_url: str


class ThreadSummary(BaseModel):
    id: int
    title: str
    forum_id: int
    prefix: str = ""
    author: str = ""
    posted_at: str = ""
    replies: int = 0
    views: int = 0
    cover_url: str = ""
    preview_urls: list[str] = []
    # Database row IDs of the first images — used to build proxy URLs
    # (/api/image/{id}?size=medium) for high-quality card previews.
    image_ids: list[int] = []
    image_count: int = 0
    has_previews: bool = False


class SearchResult(ThreadSummary):
    """A forum search hit. ``post_id`` is set in posts mode; ``mode`` echoes
    the search mode. Thread-level metadata (covers, previews) is shared with
    ThreadSummary so the same card component can render it."""

    post_id: int = 0
    mode: str = "threads"


class ThreadListOut(BaseModel):
    forum_id: int
    page: int
    total_pages: int
    threads: list[ThreadSummary]


class SearchResultsPage(BaseModel):
    """Paginated envelope for /api/search.

    ``total_pages`` is parsed from vBulletin's pagination bar ("Page X of Y").
    Single-page result sets carry no such bar, in which case the backend
    reports ``total_pages = 1``. The frontend uses it to disable the Next
    button on the last page instead of letting the user navigate to an empty
    page (vBulletin's searchids expire, so an out-of-range page is empty, not
    a duplicate of page 1).
    """

    query: str
    mode: str
    page: int
    total_pages: int
    results: list[SearchResult]


class ImageOut(BaseModel):
    id: int = 0
    idx: int
    post_id: int = 0
    main_url: str
    thumb_url: str = ""
    host: str = ""


class ThreadDetailOut(BaseModel):
    id: int
    title: str
    forum_id: int
    forum_title: str = ""
    author: str = ""
    image_count: int = 0
    post_count: int = 0
    images: list[ImageOut] = []


class PostOut(BaseModel):
    post_id: int
    index: int
    title: str = ""
    image_count: int = 0
    images: list[ImageOut] = []


class PostPageOut(BaseModel):
    thread_id: int
    page: int
    total_pages: int
    post_count: int
    posts: list[PostOut] = []


class CoverOut(BaseModel):
    thread_id: int
    title: str
    cover_url: str
    preview_urls: list[str]
    image_ids: list[int] = []
    image_count: int


class LoginRequest(BaseModel):
    username: str
    password: str = ""
    password_md5: str = ""


class AuthStatus(BaseModel):
    logged_in: bool
    username: str


class HealthOut(BaseModel):
    status: str
    db: str
