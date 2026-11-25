"""Dokumente: Blockbaum, Verschachtelungsregeln (L 3). Implementierung: Task 1.4 (P1)."""
from typing import Any

# Welche Kinder ein Blocktyp haben darf (L 3.2). Wird in Task 1.4 geprüft.
ALLOWED_CHILDREN: dict[str, set[str]] = {
    "list": {"list_item"},
    "list_item": {"list"},
    "quote": {"paragraph", "heading", "list"},
    "form": {"heading", "paragraph", "list", "quote", "code", "divider", "image", "table_view", "field",
             "line_items", "workflow"},
}


def check_nesting(parent_type: str | None, child_type: str) -> None:
    """Wirft ValueError, wenn `child_type` unter `parent_type` nicht erlaubt ist (z. B. `field` nur in `form`)."""
    ...


def flat_to_tree(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ...
