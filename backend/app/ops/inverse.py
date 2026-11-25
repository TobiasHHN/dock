"""Inverse Ops für Undo (T 2.2, T 6). Stretch (F16), Implementierung: Task 3.F6."""
from typing import Any


def invert(ops: list[dict[str, Any]], before: dict[str, Any]) -> list[dict[str, Any]]:
    """Erzeugt zu einem angewendeten Batch die inversen Ops (wird im Op-Log gespeichert)."""
    ...
