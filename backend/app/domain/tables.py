"""Tabellen: Typumwandlung, Pflicht/Unique/Min/Max, on_delete (L 2.2). Implementierung: Task 1.3 (P1)."""
from typing import Any

from app.schemas.tables import ColumnType


def coerce_value(value: Any, type_: ColumnType) -> Any:
    """Wandelt in den Spaltentyp um (z. B. "12,50" -> 12.5 bei currency). Wirft ValueError mit Meldung pro Feld."""
    ...
