"""Forum category tree definition.

The full structure of viper.to (vBulletin 4), discovered by scraping
``forum.php``.  Top-level *categories* are pure containers (no threads);
their children are *forums* (have threads).  Some forums have a nested
*Archive* sub-forum.

Community (3) and Support (16) are intentionally excluded — they contain
no browsable photo content.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ForumNode:
    forum_id: int
    title: str
    slug: str
    # Nested sub-forums (e.g. an Archive). Empty for leaf forums.
    children: tuple["ForumNode", ...] = ()


def _slug(title: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-")
    return s.lower() or "forum"


def _n(fid: int, title: str, *children: ForumNode) -> ForumNode:
    return ForumNode(fid, title, _slug(title), children)


# Top-level categories → forums → (optional) archive.
# Order matches the forum home page.  Community (3) and Support (16) omitted.
FORUM_TREE: list[ForumNode] = [
    _n(25, "Performers",
       _n(161, "Celebrity Collections"),
       _n(242, "Pornstar Collections"),
       _n(380, "Social Media Models"),
    ),
    _n(348, "External Services",
        _n(372, "OnlyFans Photos"),
        _n(268, "Scene Photos"),
     ),
    _n(235, "Adult Photo Sets",
       _n(302, "Softcore Photo Sets",
          _n(236, "Softcore Photo Sets Archive")),
       _n(303, "Artistic Photo Sets",
          _n(237, "Artistic Photo Sets Archive")),
       _n(304, "Hardcore Photo Sets",
          _n(238, "Hardcore Photo Sets Archive")),
       _n(305, "Lesbian Photo Sets",
          _n(239, "Lesbian Photo Sets Archive")),
       _n(307, "Fetish Photo Sets",
          _n(240, "Fetish Photo Sets Archive")),
       _n(306, "Alternative Photo Sets",
          _n(277, "Alternative Photo Sets Archive")),
    ),
    _n(233, "Adult Content Collections",
       _n(243, "Adult Photo Collections"),
       _n(241, "Adult Photo Link Drop"),
       _n(234, "Amateur Photo Collections"),
       _n(227, "Magazine Publications"),
    ),
    _n(388, "Transsexual Content",
       _n(308, "Transsexual Photo Sets",
          _n(291, "Transsexual Photo Sets Archive")),
        _n(389, "Transsexual Photo Collections"),
     ),
     _n(384, "Gay Content",
        _n(385, "Gay Photo Sets"),
        _n(387, "Gay Photo Collections"),
     ),
    _n(244, "Miscellaneous Content",
       _n(246, "Adult Comics"),
       _n(319, "Adult Games"),
       _n(245, "Adult Stories"),
       _n(273, "Adult Magazines"),
       _n(285, "Adult Video Feed"),
       _n(394, "AI Generated Material"),
        _n(249, "Animated Images"),
        _n(248, "Fake Material"),
        _n(149, "Uncategorized Material"),
     ),
    _n(274, "Non-Nude Content",
        _n(275, "Non-Nude Photo Collections"),
        _n(247, "Non-Nude Photo Sets"),
     ),
]


def _collect_ids(node: ForumNode, acc: set[int]) -> None:
    acc.add(node.forum_id)
    for child in node.children:
        _collect_ids(child, acc)


# Every forum id appearing in the tree (categories + forums + archives).
ALL_FORUM_IDS: set[int] = set()
for _top in FORUM_TREE:
    _collect_ids(_top, ALL_FORUM_IDS)

# Top-level category ids (the "Sections" shown in the sidebar). Used as the
# default search scope so that an unscoped search stays within the forums our
# app actually presents.
TOP_CATEGORY_IDS: list[int] = [n.forum_id for n in FORUM_TREE]


# Leaf-forum batches used to emulate a sidebar-scoped search.
#
# vBulletin's do=process cannot scope to all sidebar forums at once: passing
# every id yields no searchid, and passing a top-level *category* id does not
# expand into its children.  Only batches of leaf (thread-bearing) forums are
# honoured reliably, and only up to ~8-9 ids per request.  These five disjoint
# batches cover every leaf forum in the sidebar (including archives).  An
# unscoped search is fanned out across them and the per-batch result streams
# are k-way-merged by date (see scrapers/search.py).
SEARCH_SCOPES: list[list[int]] = [
    [161, 242, 380, 372, 268, 308, 291, 389],   # Performers + External + Transsexual
    [243, 241, 234, 227, 385, 387, 275, 247],    # Adult Content Collections + Gay + Non-Nude
    [302, 236, 303, 237, 304, 238],              # Adult Photo Sets (1/2)
    [305, 239, 307, 240, 306, 277],              # Adult Photo Sets (2/2)
    [246, 319, 245, 273, 285, 394, 249, 248, 149],  # Miscellaneous
]


def _threaded_ids(node: ForumNode, acc: list[int]) -> None:
    """Collect every thread-bearing forum id (forums + archives, not categories)."""
    if node.forum_id not in TOP_CATEGORY_IDS:
        acc.append(node.forum_id)
    for child in node.children:
        _threaded_ids(child, acc)


_threaded: list[int] = []
for _top in FORUM_TREE:
    _threaded_ids(_top, _threaded)

# Self-check: the search scopes must cover every thread-bearing forum exactly once.
_scope_union: set[int] = set()
for _batch in SEARCH_SCOPES:
    _scope_union.update(_batch)
assert _scope_union == set(_threaded), (
    "SEARCH_SCOPES must cover every thread-bearing forum exactly once; "
    f"missing={set(_threaded)-_scope_union} extra={_scope_union-set(_threaded)}"
)

# Map of every navigable forum id → node (categories included so direct
# deep-links don't 404, though the sidebar only links to leaf forums).
_NODES_BY_ID: dict[int, ForumNode] = {}


def _index_nodes(node: ForumNode) -> None:
    _NODES_BY_ID[node.forum_id] = node
    for child in node.children:
        _index_nodes(child)


for _top in FORUM_TREE:
    _index_nodes(_top)


def get_node(forum_id: int) -> ForumNode | None:
    return _NODES_BY_ID.get(forum_id)


def is_known_forum(forum_id: int) -> bool:
    return forum_id in ALL_FORUM_IDS
