"""Word -> Ops (L 8.3, T 2.9). Reine Funktion ohne FastAPI/DB. Implementierung: Task 3.7 (P3)."""
from .xlsx import ImportResult


def parse_docx(data: bytes, title: str | None = None, owner: dict[str, str] | None = None,
               bind_table: str | None = None) -> ImportResult:
    """Überschriften, Absätze, Listen, Felder („Bezeichnung: ____“), Kontrollkästchen, Tabellen -> `doc.create`."""
    ...
