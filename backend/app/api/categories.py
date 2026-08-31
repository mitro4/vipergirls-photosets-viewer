"""GET /api/categories — navigation tree of forum sections.

Built from the static FORUM_TREE (all sections except Community/Support).
Top-level categories become groups; their direct children become categories;
nested children (archives) become ``CategoryOut.children``.
"""
from __future__ import annotations

from fastapi import APIRouter

from ..forums import FORUM_TREE, ForumNode
from ..models import CategoryGroupOut, CategoryOut

router = APIRouter()


def _node_to_category(node: ForumNode, group: str, parent_id: int | None) -> CategoryOut:
    return CategoryOut(
        forum_id=node.forum_id,
        title=node.title,
        slug=node.slug,
        parent_id=parent_id,
        group=group,
        children=[_node_to_category(c, group, node.forum_id) for c in node.children],
    )


@router.get("/categories", response_model=list[CategoryGroupOut])
async def get_categories() -> list[CategoryGroupOut]:
    result: list[CategoryGroupOut] = []
    for top in FORUM_TREE:
        cats = [_node_to_category(child, top.title, top.forum_id) for child in top.children]
        result.append(
            CategoryGroupOut(name=top.title, forum_id=top.forum_id, categories=cats)
        )
    return result
