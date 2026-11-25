"""Blöcke ⇄ Markdown mit Direktiven (L 8.2). Implementierung: Task 1.4 (P1)."""
from typing import Any


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Markdown mit Block-IDs `{#blk_…}`; Actions/Buttons stehen nur im JSON."""
    ...


def markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    """Gegenstück: Markdown (inkl. `:::form`, `::field`, `::line_items`) -> Blöcke mit neuen IDs."""
    ...
