"""Excel -> Ops (L 8.3, T 2.9). Reine Funktion ohne FastAPI/DB. Implementierung: Task 3.6 (P3)."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImportResult:
    ops: list[dict[str, Any]] = field(default_factory=list)
    created: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def parse_xlsx(data: bytes, sheet: str | None = None) -> ImportResult:
    """Blatt -> `table.create` + `row.insert`; Typableitung aus den Werten; Limits 10 MB / 10 000 Zeilen / 100 Spalten."""
    ...
