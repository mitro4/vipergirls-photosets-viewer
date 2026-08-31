"""Filename sanitization — mirrors vripper's PathUtils.sanitize.

Replaces path separators, shell-special chars, and control characters with
underscore so that image-host-supplied titles are safe for the filesystem.
Dots are preserved (needed for file extensions).
"""
from __future__ import annotations

import re

# Forbidden: backslash, slash, pipe, colon, question, asterisk, quote,
# angle brackets, and control chars (0x00-0x1f, 0x7f).
_FORBIDDEN = re.compile(r'[\\/|:*?*"<>\x00-\x1f\x7f]')


def sanitize_filename(name: str) -> str:
    """Replace forbidden characters with ``_`` and strip whitespace/dots."""
    name = _FORBIDDEN.sub("_", name).strip().strip(".")
    return name or "image"


def ordered_filename(idx: int, name: str, *, width: int = 3) -> str:
    """Prefix a sanitized filename with a zero-padded ordering index.

    ``ordered_filename(0, "photo.jpg")`` → ``"001_photo.jpg"``
    """
    safe = sanitize_filename(name)
    if "." in safe:
        base, _, ext = safe.rpartition(".")
        return f"{idx + 1:0{width}d}_{base}.{ext}"
    return f"{idx + 1:0{width}d}_{safe}"


_VALID_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}


def ext_from_url(url: str) -> str:
    """Extract a file extension from *url*, defaulting to ``.jpg``."""
    tail = url.rsplit("/", 1)[-1].split("?")[0].split("#")[0]
    if "." in tail:
        ext = tail.rsplit(".", 1)[-1].lower()
        if ext in _VALID_EXTS:
            return f".{ext}"
    return ".jpg"


def numbered_filename(idx: int, ext: str = ".jpg", *, width: int = 3) -> str:
    """Generate a purely numbered filename: ``001`` → ``"001.jpg"``."""
    return f"{idx + 1:0{width}d}{ext}"
