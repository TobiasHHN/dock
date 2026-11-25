"""Formulare: Button-Sichtbarkeit (L 4.3), Absenden (L 4.6). Implementierung: Task 3.3 (P3)."""
from typing import Any

from app.schemas.common import Actor
from app.schemas.ops import FormSubmit


async def visible_buttons(form_block: str, user: Actor, run: str | None = None) -> list[dict[str, Any]]:
    """Regel aus L 4.3: explizite Buttons oder automatischer „Speichern“, Recht `submit`, im Run: aktiver Schritt,
    `can_act` und kein wartender Sub-Run."""
    ...


async def submit_form(ctx: Any, op: FormSubmit) -> dict[str, Any]:
    """Handler für `form.submit` (L 4.6): Sichtbarkeit prüfen, Werte aus Entwurf/`values`, Felder prüfen,
    Actions in einer Transaktion (erzeugt weitere Ops im selben Batch), Submission speichern (Doppelabsendung
    erkennen), im Run `workflows.complete_task` aufrufen. Rückgabe: `{results, errors?, run?}`."""
    ...


def validate_form(blocks: list[dict[str, Any]], form_block: str) -> list[dict[str, Any]]:
    """Warnungen für Formulare (L 5.7 Daten, Task 3.5): Tippfehler in Ausdrücken, nicht befüllte Pflichtspalten,
    unbekannte Spalten. Eintrag: `{block, field, message}`."""
    ...
