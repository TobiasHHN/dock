"""Aufgaben: Zuständige auflösen (L 5.9), can_act, Claim/Release/Reassign. Implementierung: Task 4.2 (P4)."""
from typing import Any

from app.schemas.common import Actor
from app.schemas.workflows import Step, Task, TaskCandidates


async def resolve_assignees(ctx: Any, step: Step, run: dict[str, Any]) -> tuple[TaskCandidates, list[str]]:
    """Löst `step.assignees` auf: starter/user -> users, role bleibt Rolle, expr -> Ausdruck auswerten.
    Rückgabe: (candidates, excluded) mit exclude_starter und exclude_steps. Keine Kandidaten -> managers."""
    ...


def can_act(actor: Actor, actor_roles: list[str], task: Task) -> bool:
    """can_act(actor, task) aus L 5.9. Bei `on_behalf_of` wird die vertretene Person geprüft."""
    ...


async def claim(ctx: Any, task_id: str, actor: Actor) -> None:
    """`task.claim`. Wirft TASK_CLAIMED, wenn schon übernommen."""
    ...


async def release(ctx: Any, task_id: str, actor: Actor) -> None:
    ...


async def reassign(ctx: Any, task_id: str, assignees: list[Any], actor: Actor) -> None:
    ...
