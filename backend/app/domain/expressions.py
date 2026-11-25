"""Ausdrücke `{{ }}` (L 4.5, T 2.1). Implementierung: Task 3.2 (P3). Fixtures: spec/fixtures/expressions/."""
from typing import Any


def evaluate(expr: str, context: dict[str, Any]) -> Any:
    """Wertet einen Text aus. Besteht er nur aus einem `{{ … }}`-Ausdruck, bleibt der Typ erhalten, sonst Text.
    `context`: fields, item, results, run, user, now, today (+ Tabellenzugriff für `lookup`).
    Wirft ExpressionError bei unbekannten Pfaden oder Funktionen."""
    ...


def find_paths(expr: str) -> list[str]:
    """Alle Pfade in einem Text, z. B. für `validate_form` und `validate_workflow` (Tippfehler finden)."""
    ...


class ExpressionError(ValueError):
    pass
