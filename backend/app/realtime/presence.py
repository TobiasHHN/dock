"""Präsenz: `editing`, Verfall nach 30 s, Verteilung über `pg_notify('presence', …)` (T 2.7, L 7.5).

Der Zustand liegt nur im Speicher (nicht in der DB). Jede Instanz hält die Einträge ihrer eigenen Verbindungen
und die der anderen Instanzen, die über `pg_notify('presence', …)` eintreffen. Ein Eintrag lebt, solange die
Verbindung den Kanal abonniert hat (`remove` beim Abbestellen oder Trennen). Nur `editing` verfällt nach
30 Sekunden ohne neue Präsenz-Nachricht; der Client schickt dafür beim Tippen regelmäßig seinen Zustand.

Für Agenten-Schreibzugriffe (L 7.5) gibt es zwei Einstiegspunkte:

- `editing_by(channel, block_id)`: wer bearbeitet den Block gerade (oder `None`)?
- `check_block_free(channel, block_id, actor)`: wirft `PipelineError("BLOCK_IN_USE", …)`, wenn ein Agent auf
  einen Block schreiben will, den gerade eine andere Person bearbeitet. Die Block-Handler (1.4) rufen das
  vor dem Schreiben auf, mit dem Kanal des Dokuments (`f"doc:{doc_id}"`).
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.ops.errors import PipelineError
from app.schemas.common import Actor
from app.schemas.ws import PresenceActor, PresenceState

EDITING_TTL = 30.0  # Sekunden
INSTANCE_ID = uuid.uuid4().hex  # unterscheidet eigene von fremden NOTIFYs

Sink = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class _Entry:
    actor: Actor
    state: PresenceState
    editing_at: float | None  # monotone Zeit der letzten Meldung mit `editing`


_entries: dict[str, dict[str, _Entry]] = {}  # Kanal -> Schlüssel -> Eintrag
_sink: Sink | None = None  # vom Hub gesetzt: lokal verteilen + pg_notify; Argumente: Kanal, NOTIFY-Payload


def bind(sink: Sink | None) -> None:
    """Der Hub meldet sich hier an, damit Änderungen an Abonnenten und andere Instanzen gehen."""
    global _sink
    _sink = sink


def _key(actor: Actor, conn_id: str | None) -> str:
    return conn_id or f"{actor.type}:{actor.id}"


def _editing(entry: _Entry, now: float) -> str | None:
    if entry.state.editing and entry.editing_at is not None and now - entry.editing_at <= EDITING_TTL:
        return entry.state.editing
    return None


def actors(channel: str) -> list[PresenceActor]:
    """Alle Anwesenden im Kanal; abgelaufenes `editing` wird als `None` ausgegeben."""
    now = time.monotonic()
    return [
        PresenceActor(actor=entry.actor, state=entry.state.model_copy(update={"editing": _editing(entry, now)}))
        for entry in _entries.get(channel, {}).values()
    ]


async def update(channel: str, actor: Actor, state: PresenceState, *, conn_id: str | None = None) -> None:
    """Setzt den Zustand eines Akteurs im Kanal und verteilt ihn an alle Instanzen.
    `conn_id` trennt mehrere Verbindungen desselben Akteurs (zwei Tabs); ohne sie zählt der Akteur einmal."""
    key = _key(actor, conn_id)
    _entries.setdefault(channel, {})[key] = _Entry(
        actor=actor, state=state, editing_at=time.monotonic() if state.editing else None)
    await _emit(channel, key, actor, state)


async def remove(channel: str, actor: Actor, *, conn_id: str | None = None) -> None:
    """Entfernt den Eintrag (Abbestellen, Verbindung getrennt)."""
    key = _key(actor, conn_id)
    if _entries.get(channel, {}).pop(key, None) is None:
        return
    if not _entries[channel]:
        del _entries[channel]
    await _emit(channel, key, actor, None)


def editing_by(channel: str, block_id: str) -> Actor | None:
    """Wer bearbeitet den Block gerade? Grundlage für `BLOCK_IN_USE` bei Agenten-Schreibzugriffen."""
    now = time.monotonic()
    for entry in _entries.get(channel, {}).values():
        if _editing(entry, now) == block_id:
            return entry.actor
    return None


def check_block_free(channel: str, block_id: str, actor: Actor) -> None:
    """Wirft `BLOCK_IN_USE`, wenn `actor` ein Agent ist und eine andere Person den Block gerade bearbeitet.
    Menschen und das System werden nicht ausgebremst (L 7.5: Schutz vor überschreibenden Agenten)."""
    if actor.type != "agent":
        return
    editor = editing_by(channel, block_id)
    if editor is None or (editor.type == actor.type and editor.id == actor.id):
        return
    who = editor.name or editor.id
    raise PipelineError("BLOCK_IN_USE", f"{who} bearbeitet diesen Block gerade",
                        {"block": block_id, "editing": editor.model_dump(mode="json", exclude_none=True)})


def sweep() -> list[str]:
    """Löscht abgelaufenes `editing` und gibt die Kanäle zurück, deren Anzeige sich dadurch ändert."""
    now = time.monotonic()
    changed: list[str] = []
    for channel, entries in _entries.items():
        touched = False
        for entry in entries.values():
            if entry.state.editing and _editing(entry, now) is None:
                entry.state = entry.state.model_copy(update={"editing": None})
                entry.editing_at = None
                touched = True
        if touched:
            changed.append(channel)
    return changed


# ── Verteilung ───────────────────────────────────────────────────────────────


async def _emit(channel: str, key: str, actor: Actor, state: PresenceState | None) -> None:
    if _sink is None:
        return
    await _sink(channel, {
        "i": INSTANCE_ID, "channel": channel, "key": key,
        "actor": actor.model_dump(mode="json", exclude_none=True),
        "state": state.model_dump(mode="json") if state is not None else None,
    })


def apply_remote(payload: dict[str, Any]) -> str | None:
    """Übernimmt eine NOTIFY-Meldung einer anderen Instanz. Gibt den Kanal zurück, wenn sich etwas geändert hat."""
    if payload.get("i") == INSTANCE_ID:
        return None
    channel, key = payload["channel"], payload["key"]
    if payload.get("state") is None:
        gone = _entries.get(channel, {}).pop(key, None)
        if channel in _entries and not _entries[channel]:
            del _entries[channel]
        return channel if gone is not None else None
    state = PresenceState.model_validate(payload["state"])
    _entries.setdefault(channel, {})[key] = _Entry(
        actor=Actor.model_validate(payload["actor"]), state=state,
        editing_at=time.monotonic() if state.editing else None)
    return channel


def reset() -> None:
    """Nur für Tests."""
    _entries.clear()
