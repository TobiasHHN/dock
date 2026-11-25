"""Gemeinsame Typen: IDs, Werte, Akteure, Fehler (anwendungslogik.md 1, 5.8, 6, 7.5)."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# Alle IDs sind Präfix + ULID und werden vom Client erzeugt (L 1).
# Überall, wo ein Objekt referenziert wird, ist auch der Key erlaubt (z. B. "bestellungen.kostenstelle").
Id = str
Ref = str  # ID oder Key
Value = Any  # JSON-Wert einer Zelle / eines Feldes


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Actor(BaseModel):
    """Akteur (L 5.8). Wird immer serverseitig aus der Authentifizierung bestimmt, nie vom Client übernommen."""

    type: Literal["user", "agent", "system"]
    id: str  # usr_…, agt_… oder "workflow" | "scheduler"
    on_behalf_of: str | None = None  # nur bei type=agent
    name: str | None = None  # Anzeigename, nur für die Ausgabe


ErrorCode = Literal[
    "CONFLICT",  # base-Version veraltet, details enthält den aktuellen Stand
    "IN_USE",  # Löschschutz, details enthält die Verwendungen
    "BLOCK_IN_USE",  # Mensch tippt gerade im Block (L 7.5)
    "NOT_FOUND",
    "FORBIDDEN",
    "VALIDATION",  # details.errors: { pfad: meldung }
    "TASK_DONE",
    "TASK_CLAIMED",
    "IMPORT_INVALID",
    "IMPORT_USED",
]


class ApiError(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None
