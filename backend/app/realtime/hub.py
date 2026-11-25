"""Realtime-Hub (T 2.7, L 7): Verbindungen, Abonnements, Verteilung der Ops aus dem Op-Log.

Ablauf einer Änderung:
  Pipeline schreibt `oplog` und `pg_notify('ops', {channel, seq})` in ihrer Transaktion -> Postgres liefert
  beim Commit -> jede Instanz hört mit EINER asyncpg-Verbindung (`start_listener`) -> liest die Zeile aus dem
  Op-Log -> schickt sie an ihre lokalen Abonnenten des Kanals.

Lückenlosigkeit: Jedes Abonnement merkt sich `last_seq`, die letzte an diesen Client gesendete `seq`.
`_deliver` sendet immer alles aus dem Op-Log in `(last_seq, seq]`, in Reihenfolge. Damit sind verspätete,
doppelte oder verlorene NOTIFYs (auch nach einem Verbindungsabbruch der LISTEN-Verbindung) unschädlich, und
Nachholen ab `since` ist derselbe Weg. Pro Abonnement serialisiert ein Lock Abo-Aufbau und Zustellung.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import asyncpg
from fastapi import WebSocket
from pydantic import BaseModel
from sqlalchemy import text

from app.auth import CurrentUser
from app.config import settings
from app.db import session as db
from app.ops.errors import PipelineError
from app.ops.pipeline import apply_batch
from app.realtime import access, presence, snapshots
from app.schemas.ops import OpBatch
from app.schemas.ws import AckMsg, PresenceBroadcastMsg, PresenceMsg, PresenceState, RejectMsg, SnapshotMsg

log = logging.getLogger(__name__)

CATCHUP_LIMIT = 1000  # größere Lücken -> Snapshot (T 2.7)
PRESENCE_CHANNELS = ("doc", "run")  # Kanäle mit Präsenz (L 7.2)
_RECONNECT_DELAY = 2.0
_SWEEP_EVERY = 5.0  # Prüfung der Verbindung und Ablauf von `editing`
_TICK = 1.0  # so schnell fällt ein Verbindungsabbruch auf


@dataclass
class _Sub:
    last_seq: int | None = None  # None: Abo wird gerade aufgebaut
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class Connection:
    socket: WebSocket
    user: CurrentUser
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    subs: dict[str, _Sub] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    ops_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    worker: asyncio.Task | None = None
    closed: bool = False

    @property
    def actor(self):
        return self.user.actor

    async def send(self, message: BaseModel | dict[str, Any]) -> None:
        payload = message.model_dump(mode="json") if isinstance(message, BaseModel) else message
        async with self.send_lock:
            try:
                await self.socket.send_json(payload)
            except Exception:  # Socket ist weg; die Lese-Schleife in api/ws.py räumt auf
                self.closed = True


_subscribers: dict[str, dict[str, Connection]] = {}  # Kanal -> Verbindungs-ID -> Verbindung
_tasks: set[asyncio.Task] = set()
_listener_task: asyncio.Task | None = None
_pg: asyncpg.Connection | None = None
_ready: asyncio.Event | None = None


def _spawn(coro) -> None:
    task = asyncio.ensure_future(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# ── Verbindung ───────────────────────────────────────────────────────────────


async def connect(socket: WebSocket, user: CurrentUser) -> Connection:
    conn = Connection(socket=socket, user=user)
    conn.worker = asyncio.ensure_future(_ops_worker(conn))
    return conn


async def disconnect(conn: Connection) -> None:
    conn.closed = True
    if conn.worker:
        conn.worker.cancel()
    for channel in list(conn.subs):
        await unsubscribe(conn, channel)


# ── Abonnements ──────────────────────────────────────────────────────────────


async def subscribe(conn: Connection, channel: str, since: int | None = None) -> None:
    """Prüft das Leserecht, schickt Snapshot (ohne `since`, zu alt oder unplausibel) oder holt ab `since` nach.
    Abgelehnt wird mit `reject` (batch_id `subscribe:<kanal>`), das Abo besteht dann nicht."""
    try:
        async with db.SessionLocal() as s:
            user = conn.user.model_copy(update={"roles": (await access.load_roles(s, conn.user.id))[0]})
            await access.check_read(s, user, channel)
        conn.user = user
    except PipelineError as exc:
        await conn.send(RejectMsg(batch_id=f"subscribe:{channel}", error=exc.error))
        return

    sub = conn.subs.get(channel)
    if sub is None:
        sub = conn.subs[channel] = _Sub()
        _subscribers.setdefault(channel, {})[conn.id] = conn
    async with sub.lock:
        sub.last_seq = None
        try:
            caught_up = since is not None and await _catch_up(conn, channel, sub, since)
            if not caught_up:
                seq, data = await snapshots.build(channel, conn.user)
                await conn.send(SnapshotMsg(channel=channel, seq=seq, data=data))
                sub.last_seq = seq
        except PipelineError as exc:
            await _drop(conn, channel)
            await conn.send(RejectMsg(batch_id=f"subscribe:{channel}", error=exc.error))
            return
        except Exception:
            log.exception("subscribe %s fehlgeschlagen", channel)
            await _drop(conn, channel)
            await conn.send(RejectMsg(batch_id=f"subscribe:{channel}", error=PipelineError(
                "VALIDATION", "Abonnement fehlgeschlagen").error))
            return

    if channel.partition(":")[0] in PRESENCE_CHANNELS:
        await presence.update(channel, conn.actor, PresenceState(), conn_id=conn.id)
        await conn.send(_presence_msg(channel))
    # Ops, die während des Aufbaus eintrafen, hat `_deliver` am Lock abgewartet. Falls die NOTIFYs vor dem
    # Registrieren kamen, holt dieser Aufruf sie nach.
    _spawn(_deliver_latest(conn, channel))


async def _catch_up(conn: Connection, channel: str, sub: _Sub, since: int) -> bool:
    """Sendet `oplog (since, current]`. False -> Snapshot nötig (zu alt, Lücke im Log, Client ist voraus)."""
    async with db.SessionLocal() as s:
        current = int((await s.execute(text("SELECT seq FROM channels WHERE id = :c"),
                                       {"c": channel})).scalar_one_or_none() or 0)
        if since < 0 or since > current or current - since > CATCHUP_LIMIT:
            return False
        rows = await _read_oplog(s, channel, since, current)
    if len(rows) != current - since:  # Log wurde aufgeräumt -> nicht lückenlos
        return False
    sub.last_seq = since
    for row in rows:
        await conn.send(_ops_event(channel, row))
        sub.last_seq = row["seq"]
    return True


async def unsubscribe(conn: Connection, channel: str) -> None:
    if channel not in conn.subs:
        return
    await _drop(conn, channel)
    if channel.partition(":")[0] in PRESENCE_CHANNELS:
        await presence.remove(channel, conn.actor, conn_id=conn.id)


async def _drop(conn: Connection, channel: str) -> None:
    conn.subs.pop(channel, None)
    subs = _subscribers.get(channel)
    if subs is not None:
        subs.pop(conn.id, None)
        if not subs:
            del _subscribers[channel]


# ── Ops vom Client ───────────────────────────────────────────────────────────


def submit_ops(conn: Connection, batch: OpBatch) -> None:
    """Reiht den Batch ein. Pro Verbindung laufen Batches nacheinander (Reihenfolge der optimistischen Liste)."""
    conn.ops_queue.put_nowait(batch)


async def _ops_worker(conn: Connection) -> None:
    while True:
        batch: OpBatch = await conn.ops_queue.get()
        try:
            result = await apply_batch(batch, conn.actor)
        except PipelineError as exc:
            await conn.send(RejectMsg(batch_id=batch.batch_id, error=exc.error))
        except Exception:
            log.exception("apply_batch %s fehlgeschlagen", batch.batch_id)
            await conn.send(RejectMsg(batch_id=batch.batch_id, error=PipelineError(
                "VALIDATION", "Interner Fehler beim Ausführen des Batches").error))
        else:
            await conn.send(AckMsg(batch_id=result.batch_id, seq=result.seq, results=result.results))


# ── Präsenz ──────────────────────────────────────────────────────────────────


async def update_presence(conn: Connection, msg: PresenceMsg) -> None:
    """Präsenz nur in Kanälen, die die Verbindung abonniert hat."""
    if msg.channel not in conn.subs or msg.channel.partition(":")[0] not in PRESENCE_CHANNELS:
        await conn.send(RejectMsg(batch_id=f"presence:{msg.channel}", error=PipelineError(
            "FORBIDDEN", "Präsenz nur in abonnierten doc- und run-Kanälen").error))
        return
    await presence.update(msg.channel, conn.actor, msg.state, conn_id=conn.id)


def _presence_msg(channel: str) -> PresenceBroadcastMsg:
    return PresenceBroadcastMsg(channel=channel, actors=presence.actors(channel))


async def _presence_sink(channel: str, payload: dict[str, Any]) -> None:
    await _broadcast_presence(channel)
    await _notify("presence", payload)


async def _broadcast_presence(channel: str) -> None:
    message = _presence_msg(channel)
    for conn in list(_subscribers.get(channel, {}).values()):
        if conn.subs.get(channel) is not None and conn.subs[channel].last_seq is not None:
            await conn.send(message)


presence.bind(_presence_sink)


# ── Verteilung der Ops ───────────────────────────────────────────────────────


async def publish(channel: str, event: dict[str, Any]) -> None:
    """Veröffentlicht ein Ereignis auf einem Kanal (`doc:`, `table:`, `run:`, `user:`, `workspace`).
    Mit `event["seq"]` (Eintrag steht im Op-Log): `pg_notify('ops', {channel, seq})`, jede Instanz liest den
    Eintrag und verteilt ihn. Die Op-Pipeline macht das selbst in ihrer Transaktion, `publish` ist für alle
    anderen Quellen. Ohne `seq` (flüchtiges Ereignis, z. B. ein Hinweis): wird unverändert an die lokalen
    Abonnenten des Kanals gesendet."""
    seq = event.get("seq")
    if isinstance(seq, int):
        await _notify("ops", {"channel": channel, "seq": seq})
        return
    for conn in list(_subscribers.get(channel, {}).values()):
        await conn.send({**event, "channel": channel})


async def _notify(topic: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload)
    if _pg is not None and not _pg.is_closed():
        try:
            await _pg.execute("SELECT pg_notify($1, $2)", topic, body)
            return
        except Exception:
            log.warning("pg_notify über Listener-Verbindung fehlgeschlagen, nutze Sitzung", exc_info=True)
    try:
        async with db.SessionLocal() as s:
            await s.execute(text("SELECT pg_notify(:t, :p)"), {"t": topic, "p": body})
            await s.commit()
    except Exception:
        log.warning("pg_notify('%s') fehlgeschlagen; andere Instanzen erfahren es nicht", topic, exc_info=True)


async def _read_oplog(s, channel: str, after: int, upto: int) -> list[dict[str, Any]]:
    rows = (await s.execute(
        text("""SELECT seq, batch_id, actor, ops FROM oplog
                WHERE channel = :c AND seq > :a AND seq <= :u ORDER BY seq"""),
        {"c": channel, "a": after, "u": upto})).mappings().all()
    return [dict(r) for r in rows]


def _loads(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _ops_event(channel: str, row: dict[str, Any]) -> dict[str, Any]:
    return {"type": "ops", "channel": channel, "seq": row["seq"], "batch_id": row["batch_id"],
            "actor": _loads(row["actor"]), "ops": _loads(row["ops"])}


async def _deliver(channel: str, seq: int) -> None:
    """Verteilt `oplog (last_seq, seq]` an jeden lokalen Abonnenten."""
    conns = list(_subscribers.get(channel, {}).values())
    if not conns:
        return
    for conn in conns:
        _spawn(_deliver_to(conn, channel, seq))


async def _deliver_latest(conn: Connection, channel: str) -> None:
    async with db.SessionLocal() as s:
        seq = (await s.execute(text("SELECT seq FROM channels WHERE id = :c"), {"c": channel})).scalar_one_or_none()
    if seq:
        await _deliver_to(conn, channel, int(seq))


async def _deliver_to(conn: Connection, channel: str, seq: int) -> None:
    sub = conn.subs.get(channel)
    if sub is None:
        return
    async with sub.lock:
        if sub.last_seq is None or sub.last_seq >= seq or conn.closed:
            return
        try:
            async with db.SessionLocal() as s:
                rows = await _read_oplog(s, channel, sub.last_seq, seq)
        except Exception:
            log.exception("Op-Log lesen (%s, %s) fehlgeschlagen", channel, seq)
            return
        for row in rows:
            await conn.send(_ops_event(channel, row))
            sub.last_seq = row["seq"]


# ── LISTEN ───────────────────────────────────────────────────────────────────


def _dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


def _on_notify(_conn, _pid, topic: str, payload: str) -> None:
    try:
        data = json.loads(payload)
        if topic == "ops":
            _spawn(_deliver(data["channel"], int(data["seq"])))
        elif topic == "presence":
            changed = presence.apply_remote(data)
            if changed:
                _spawn(_broadcast_presence(changed))
    except Exception:
        log.exception("Ungültige NOTIFY-Nachricht auf '%s': %r", topic, payload)


async def _resync_all() -> None:
    """Nach (Wieder-)Verbinden der LISTEN-Verbindung: alles nachliefern, was inzwischen committet wurde."""
    for channel in list(_subscribers):
        async with db.SessionLocal() as s:
            seq = (await s.execute(text("SELECT seq FROM channels WHERE id = :c"),
                                   {"c": channel})).scalar_one_or_none()
        if seq:
            await _deliver(channel, int(seq))


async def _run_listener() -> None:
    global _pg
    while True:
        conn = None
        try:
            conn = await asyncpg.connect(_dsn())
            await conn.add_listener("ops", _on_notify)
            await conn.add_listener("presence", _on_notify)
            _pg = conn
            await _resync_all()
            if _ready is not None:
                _ready.set()
            last_check = time.monotonic()
            while not conn.is_closed():
                await asyncio.sleep(_TICK)
                if time.monotonic() - last_check >= _SWEEP_EVERY:
                    last_check = time.monotonic()
                    await conn.execute("SELECT 1")  # erkennt tote Verbindungen
                    for channel in presence.sweep():
                        await _broadcast_presence(channel)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("LISTEN-Verbindung verloren oder nicht möglich (%s), neuer Versuch in %ss", exc,
                        _RECONNECT_DELAY)
        finally:
            _pg = None
            if conn is not None:
                try:
                    await conn.close(timeout=2)
                except Exception:
                    pass
        await asyncio.sleep(_RECONNECT_DELAY)


async def start_listener() -> None:
    """Startet die LISTEN-Schleife (eine asyncpg-Verbindung je Instanz). Wird beim App-Start aufgerufen und
    wartet nicht auf die Datenbank; bei Verbindungsverlust verbindet sie sich neu und liefert Verpasstes nach."""
    global _listener_task, _ready
    if _listener_task is not None and not _listener_task.done():
        return
    _ready = asyncio.Event()
    _listener_task = asyncio.ensure_future(_run_listener())


async def wait_ready(timeout: float = 5.0) -> bool:
    """True, sobald die LISTEN-Verbindung steht (für Tests und Start-Skripte)."""
    if _ready is None:
        return False
    try:
        await asyncio.wait_for(_ready.wait(), timeout)
        return True
    except asyncio.TimeoutError:
        return False


async def stop_listener() -> None:
    global _listener_task
    task, _listener_task = _listener_task, None
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
