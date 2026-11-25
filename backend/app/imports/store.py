"""Vorbereitete Imports (T 2.9). Implementierung: Task 3.6 (P3)."""
from typing import Any

from app.schemas.api import ImportPlan


async def save_plan(ctx: Any, source: str, ops: list[dict[str, Any]], created: dict[str, Any],
                    warnings: list[str]) -> ImportPlan:
    """Speichert die Ops unter einer neuen `import_id` (1 h gültig) und gibt `{import_id, created, warnings}` zurück."""
    ...


async def take_ops(ctx: Any, import_id: str, actor: Any) -> list[dict[str, Any]]:
    """Für den Handler `import.include`: prüft Akteur und Gültigkeit, markiert den Import als verbraucht
    (`IMPORT_USED` bei zweitem Versuch) und liefert die Ops."""
    ...
