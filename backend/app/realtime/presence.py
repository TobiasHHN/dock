"""Präsenz: `editing`, Verfall nach 30 s, Verteilung über `pg_notify('presence', …)` (T 2.7, L 7.5).
Implementierung: Task 1.5 (P1)."""
from app.schemas.common import Actor
from app.schemas.ws import PresenceState


async def update(channel: str, actor: Actor, state: PresenceState) -> None:
    """Setzt den Zustand eines Akteurs im Kanal und verteilt ihn an alle Instanzen."""
    ...


def editing_by(channel: str, block_id: str) -> Actor | None:
    """Wer bearbeitet den Block gerade? Grundlage für `BLOCK_IN_USE` bei Agenten-Schreibzugriffen."""
    ...
