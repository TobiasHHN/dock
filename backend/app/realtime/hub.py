"""Realtime-Hub (T 2.7, L 7). Implementierung: Task 1.5 (P1)."""
from typing import Any


async def publish(channel: str, event: dict[str, Any]) -> None:
    """Veröffentlicht ein Ereignis auf einem Kanal (`doc:`, `table:`, `run:`, `user:`, `workspace`).
    Intern: Op-Log lesen, `pg_notify('ops', {channel, seq})`, jede Instanz verteilt an ihre Abonnenten.
    Alle anderen Module rufen nur diese Funktion auf, nie direkt `pg_notify`."""
    ...


async def start_listener() -> None:
    """Startet die LISTEN-Schleife (eine asyncpg-Verbindung je Instanz). Wird beim App-Start aufgerufen."""
    ...
