"""Workflows und Runs: Validierung (L 5.7), Veröffentlichen (L 5.3), Ablauf (L 5.4).
Implementierung: Tasks 4.1 (validate/publish), 4.2 (start_run, enter_step, complete_task, cancel_run)."""
from typing import Any

from app.schemas.common import Actor
from app.schemas.workflows import ValidationResult, WorkflowDefinition


async def validate_workflow(ctx: Any, definition: WorkflowDefinition) -> ValidationResult:
    """Alle Fehler und Warnungen aus L 5.7 (Struktur, Zuständigkeit, Daten) in agentenlesbarer Form."""
    ...


async def publish_workflow(ctx: Any, workflow_id: str) -> int:
    """Prüft (nur Fehler blockieren), friert die Schritt-Dokumente ein, legt Version n+1 an. Rückgabe: Versionsnummer."""
    ...


async def start_run(ctx: Any, run_id: str, workflow: str, input: dict[str, Any] | None, actor: Actor) -> None:
    """Handler für `run.start` (L 5.4): Startberechtigung, Run anlegen, Event `started`, `enter_step(start)`."""
    ...


async def enter_step(ctx: Any, run_id: str, step: str) -> None:
    """Run auf Schritt setzen, Aufgabe anlegen (tasks.create_task), Event `step_entered`, Titel neu auswerten."""
    ...


async def complete_task(ctx: Any, task_id: str, button: dict[str, Any], values: dict[str, Any],
                        results: dict[str, Any], actor: Actor) -> None:
    """Nach `form.submit` im Run: Aufgabe `done`, `run.steps[step]` speichern, Übergang nach Outcome,
    Ende oder `enter_step`. Wird von `forms.submit_form` aufgerufen (Task 4.3)."""
    ...


async def cancel_run(ctx: Any, run_id: str, reason: str | None, actor: Actor) -> None:
    ...
