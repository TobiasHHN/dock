"""Statusansicht, Events, Benachrichtigungen (L 5.10). Implementierung: Task 4.4 (P4)."""
from typing import Any

from app.schemas.common import Actor
from app.schemas.workflows import RunStatusView


async def build_status_view(ctx: Any, run_id: str, viewer: Actor) -> RunStatusView:
    """Statusansicht (gleich für Browser und `get_run`). Prüft, ob der Betrachter den Run sehen darf."""
    ...


async def record_event(ctx: Any, run_id: str, type: str, actor: Actor, **fields: Any) -> None:
    """Schreibt ein `run_events`-Event und erzeugt Benachrichtigungen nach der Tabelle in L 5.10."""
    ...
