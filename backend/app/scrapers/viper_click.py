"""Parse viper.click/vr.php XML — primary route for thread image metadata.

GET https://viper.click/vr.php?t=<threadId> returns clean XML:
    <images>
      <user hash="guest"/>               (real securitytoken when logged in)
      <forum title="Softcore Photo Sets"/>
      <thread id="16314164" title="..."/>
      <post id="264419505" number="1" title="..." imagecount="116">
        <image type="linked" thumb_url="..." main_url="..."/>
        ...
      </post>
    </images>

Both type="linked" and type="directlinked" images are processed. The
latter (often GIF collections posted as direct image URLs) carry no
thumb_url, so main_url is used as the thumbnail fallback.
The thumb_url is free — used for covers and hover previews without
downloading full-size images.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from ..config import get_settings
from .http import get_http

log = logging.getLogger("viper.click")


@dataclass
class ImageItem:
    main_url: str
    thumb_url: str


@dataclass
class PostItem:
    post_id: int
    number: int
    title: str
    image_count: int
    images: list[ImageItem] = field(default_factory=list)


@dataclass
class ThreadLookup:
    thread_id: int
    title: str
    forum_title: str
    security_token: str
    error: str = ""
    posts: list[PostItem] = field(default_factory=list)

    @property
    def total_images(self) -> int:
        return sum(len(p.images) for p in self.posts)

    def all_images(self) -> list[ImageItem]:
        out: list[ImageItem] = []
        for p in self.posts:
            out.extend(p.images)
        return out


def parse_thread_xml(xml_bytes: bytes) -> ThreadLookup:
    root = ET.fromstring(xml_bytes)

    error_el = root.find("error")
    error = error_el.get("details", "") if error_el is not None else ""

    user_el = root.find("user")
    token = user_el.get("hash", "guest") if user_el is not None else "guest"

    forum_el = root.find("forum")
    forum_title = forum_el.get("title", "") if forum_el is not None else ""

    thread_el = root.find("thread")
    thread_id = int(thread_el.get("id", "0")) if thread_el is not None else 0
    title = thread_el.get("title", "") if thread_el is not None else ""

    posts: list[PostItem] = []
    for pe in root.findall("post"):
        post = PostItem(
            post_id=int(pe.get("id", "0")),
            number=int(pe.get("number", "0")),
            title=pe.get("title", "") or title,
            image_count=int(pe.get("imagecount", "0")),
        )
        for ie in pe.findall("image"):
            itype = ie.get("type", "")
            if itype in ("linked", "directlinked"):
                main_url = ie.get("main_url", "")
                # directlinked images (often GIF collections posted as direct
                # image URLs) carry no thumb_url; fall back to main_url so cards
                # still get a cover/preview.
                thumb_url = ie.get("thumb_url", "") or main_url
                post.images.append(
                    ImageItem(main_url=main_url, thumb_url=thumb_url)
                )
        posts.append(post)

    return ThreadLookup(
        thread_id=thread_id,
        title=title,
        forum_title=forum_title,
        security_token=token,
        error=error,
        posts=posts,
    )


async def lookup_thread(thread_id: int) -> ThreadLookup:
    settings = get_settings()
    url = f"{settings.click_base_url}/vr.php"
    resp = await get_http().get(url, params={"t": thread_id})
    if resp.status_code != 200:
        log.error("vr.php?t=%s → HTTP %s", thread_id, resp.status_code)
        return ThreadLookup(
            thread_id=thread_id,
            title="",
            forum_title="",
            security_token="guest",
            error=f"HTTP {resp.status_code}",
        )
    try:
        result = parse_thread_xml(resp.content)
    except ET.ParseError as exc:
        log.error("vr.php?t=%s XML parse error: %s", thread_id, exc)
        return ThreadLookup(
            thread_id=thread_id,
            title="",
            forum_title="",
            security_token="guest",
            error=f"XML parse error: {exc}",
        )
    log.info(
        "vr.php?t=%s → %d posts, %d images",
        thread_id,
        len(result.posts),
        result.total_images,
    )
    return result
