"""Image-host registry — identification and resolver lookup.

16 inline image hosts (same as vripper). Stage 5 adds the full resolvers;
this module currently provides host identification by URL substring match.
"""
from __future__ import annotations

# (host_id, display_name, url_substring)
HOST_TABLE: list[tuple[int, str, str]] = [
    (0, "acidimg.cc", "acidimg.cc"),
    (1, "dpic.me", "dpic.me"),
    (2, "imagebam.com", "imagebam.com"),
    (3, "imagetwist.com", "imagetwist.com"),
    (4, "imagevenue.com", "imagevenue.com"),
    (5, "imagezilla.net", "imagezilla.net"),
    (6, "imgbox.com", "imgbox.com"),
    (7, "imgspice.com", "imgspice.com"),
    (8, "imx.to", "imx.to"),
    (9, "pimpandhost.com", "pimpandhost.com"),
    # "pixhost" (not "pixhost.to") so the pixhost.cc mirror is identified too;
    # no other host substring contains "pixhost".
    (10, "pixhost.to", "pixhost"),
    (11, "pixroute.com", "pixroute.com"),
    (12, "pixxxels.cc", "pixxxels.cc"),
    (13, "postimg.cc", "postimg.cc"),
    (14, "turboimagehost.com", "turboimagehost.com"),
    (15, "vipr.im", "vipr.im"),
]

_SUBSTR_TO_NAME: dict[str, str] = {sub: name for _, name, sub in HOST_TABLE}


def identify_host(url: str) -> str:
    """Return the host display name whose URL substring matches, or ''."""
    for substr, name in _SUBSTR_TO_NAME.items():
        if substr in url:
            return name
    return ""
