"""Referenz-Index und Löschschutz (L 9). Implementierung: Task 1.2/1.3 (P1)."""
from typing import Any


async def update(ctx: Any, touched: list[Any]) -> None:
    """Pflegt die Tabelle `references` für alle in diesem Batch geänderten Quellen."""
    ...


async def usages(ctx: Any, kind: str, id_: str) -> list[dict[str, Any]]:
    """Wo wird Tabelle/Spalte/Rolle/Dokument verwendet? Grundlage für `IN_USE`-Fehler."""
    ...
