"""Echtzeit-Verteilung (Task 1.5): Hub, LISTEN/NOTIFY, Snapshot/Nachholen, Rechte, ack/reject, Präsenz.

Die Tests treiben den WebSocket-Endpunkt (`app.api.ws.ws`) mit einem Fake-Socket direkt an und laufen gegen
Postgres (Standard: Host-Port 5433, überschreibbar mit TEST_DATABASE_URL). Ops laufen durch die echte Pipeline
mit Dummy-Handlern. Testdaten tragen den Marker `zz15` und werden danach entfernt.
"""
import asyncio
import json
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.websockets import WebSocketDisconnect

from app import config
from app.api import ws as ws_module
from app.auth import create_access_token
from app.db import session as db
from app.ops import pipeline
from app.ops.errors import PipelineError
from app.ops.handlers import HANDLERS, register
from app.realtime import hub, presence
from app.schemas.common import Actor
from app.schemas.ws import PresenceState

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock_test")
USERS = {"anna": ("usr_zz15anna", "einkauf"), "ben": ("usr_zz15ben", "mitarbeiter"),
         "cy": ("usr_zz15cy", "mitarbeiter")}
TIMEOUT = 5


def zid(prefix: str) -> str:
    return f"{prefix}_zz15{uuid.uuid4().hex[:10]}"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def env(monkeypatch):
    eng = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with eng.connect() as c:
            await c.execute(text("SELECT 1 FROM batches LIMIT 1"))
    except Exception:
        pytest.skip("Postgres nicht erreichbar")
    maker = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(db, "SessionLocal", maker)
    monkeypatch.setattr(pipeline, "SessionLocal", maker)
    monkeypatch.setattr(config.settings, "database_url", DB_URL)
    monkeypatch.setattr(hub, "_RECONNECT_DELAY", 0.2)
    monkeypatch.setattr(hub, "_TICK", 0.1)
    async with eng.begin() as c:
        for key, (uid, role) in USERS.items():
            await c.execute(text("""INSERT INTO users (id, name, email, active) VALUES (:i, :n, :e, true)
                                    ON CONFLICT (id) DO NOTHING"""),
                            {"i": uid, "n": key.title(), "e": f"{uid}@example.local"})
            await c.execute(text("""INSERT INTO roles (id, workspace_id, key, name) VALUES (:i, 'ws_demo', :k, :k)
                                    ON CONFLICT (workspace_id, key) DO NOTHING"""), {"i": f"rol_zz15{role}", "k": role})
            await c.execute(text("""INSERT INTO member_roles (workspace_id, member_id, role_id)
                                    SELECT 'ws_demo', :m, id FROM roles WHERE workspace_id = 'ws_demo' AND key = :k
                                    ON CONFLICT DO NOTHING"""), {"m": uid, "k": role})
    presence.reset()
    await hub.start_listener()
    assert await hub.wait_ready(), "LISTEN-Verbindung kam nicht zustande"
    yield eng
    await hub.stop_listener()
    presence.reset()
    async with eng.begin() as c:
        for stmt in (
            "DELETE FROM oplog WHERE channel LIKE '%zz15%' OR batch_id LIKE '%zz15%'",
            "DELETE FROM batches WHERE batch_id LIKE '%zz15%'",
            "DELETE FROM channels WHERE id LIKE '%zz15%'",
            "DELETE FROM tasks WHERE run_id LIKE '%zz15%'",
            "DELETE FROM runs WHERE id LIKE '%zz15%'",
            "DELETE FROM workflows WHERE id LIKE '%zz15%'",
            "DELETE FROM rows WHERE id LIKE '%zz15%'",
            "DELETE FROM tables WHERE id LIKE '%zz15%'",
            "DELETE FROM blocks WHERE id LIKE '%zz15%'",
            "DELETE FROM documents WHERE id LIKE '%zz15%'",
            "DELETE FROM member_roles WHERE member_id LIKE 'usr_zz15%'",
            "DELETE FROM users WHERE id LIKE 'usr_zz15%'",
        ):
            await c.execute(text(stmt))
    await eng.dispose()


@pytest.fixture(autouse=True)
def handlers(monkeypatch):
    saved = dict(HANDLERS)

    async def table_create(ctx, op):
        await ctx.session.execute(
            text("INSERT INTO tables (id, workspace_id, key, name) VALUES (:i, :ws, :k, :n)"),
            {"i": op.id, "ws": ctx.workspace_id, "k": op.key, "n": op.name})
        await ctx.touch("table", op.id, f"table:{op.id}", created=True)
        return {"id": op.id}

    async def row_insert(ctx, op):
        for row in op.rows:
            await ctx.session.execute(
                text("INSERT INTO rows (id, table_id, position, values) VALUES (:i, :t, 'a0', CAST(:v AS jsonb))"),
                {"i": row.id, "t": op.table, "v": json.dumps(row.values)})
            await ctx.touch("row", row.id, created=True)
        await ctx.touch("table", op.table, f"table:{op.table}")
        return {"ids": [r.id for r in op.rows]}

    register("table.create")(table_create)
    register("row.insert")(row_insert)
    monkeypatch.setattr("app.ops.handlers._loaded", True)
    monkeypatch.setattr(pipeline, "enqueue_reembed", lambda *_: asyncio.sleep(0))
    yield
    HANDLERS.clear()
    HANDLERS.update(saved)


class Client:
    """Ein verbundener Browser: Fake-Socket + laufender Endpunkt."""

    def __init__(self, who: str | None, token: str | None = None, header_token: str | None = None):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.close_code: int | None = None
        self.headers: dict[str, str] = {}
        self.who = who
        self.token = token
        if who and token is None:
            uid, role = USERS[who]
            self.token = create_access_token(uid, [role])
        if header_token:
            self.headers["authorization"] = "Bearer " + header_token
        self.task = asyncio.ensure_future(ws_module.ws(self, token=self.token))

    # Socket-Schnittstelle, die der Endpunkt benutzt
    async def accept(self):
        pass

    async def receive_json(self):
        item = await self.inbox.get()
        if item is None:
            raise WebSocketDisconnect(1000)
        return item

    async def send_json(self, data):
        await self.outbox.put(data)

    async def close(self, code=1000, reason=None):
        self.close_code = code
        await self.outbox.put(None)

    # Test-Schnittstelle
    def send(self, **msg):
        self.inbox.put_nowait(msg)

    async def recv(self):
        item = await asyncio.wait_for(self.outbox.get(), TIMEOUT)
        assert item is not None, f"Verbindung geschlossen ({self.close_code})"
        return item

    async def recv_type(self, type_: str, **match):
        for _ in range(50):
            msg = await self.recv()
            if msg["type"] == type_ and all(msg.get(k) == v for k, v in match.items()):
                return msg
        raise AssertionError(f"keine Nachricht {type_} {match}")

    async def expect_silence(self, seconds=0.4):
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(self.outbox.get(), seconds)

    async def disconnect(self):
        self.inbox.put_nowait(None)
        await asyncio.wait_for(self.task, TIMEOUT)


def batch(*ops, batch_id=None):
    return {"batch_id": batch_id or zid("b"), "ops": list(ops)}


def new_table(tid):
    return {"op": "table.create", "id": tid, "key": tid, "name": "T",
            "columns": [{"id": zid("col"), "key": "name", "name": "Name", "type": {"kind": "text"}}]}


def insert_row(table, row_id=None):
    return {"op": "row.insert", "table": table, "rows": [{"id": row_id or zid("row"), "values": {}}]}


async def make_table(env) -> str:
    tid = zid("tbl")
    await pipeline.apply_batch(
        pipeline.OpBatch.model_validate(batch(new_table(tid))), Actor(type="system", id="workflow"))
    return tid


# ── Anmeldung ────────────────────────────────────────────────────────────────


async def test_ws_without_or_with_bad_token_is_closed(env):
    for client in (Client(None), Client(None, token="kaputt")):
        with pytest.raises(AssertionError, match="4401"):
            await client.recv()
        await asyncio.wait_for(client.task, TIMEOUT)


async def test_token_in_authorization_header(env):
    client = Client(None, header_token=create_access_token(USERS["ben"][0], ["mitarbeiter"]))
    client.send(type="subscribe", channel="workspace")
    assert (await client.recv())["type"] == "snapshot"
    await client.disconnect()


# ── Verteilung ───────────────────────────────────────────────────────────────


async def test_two_clients_see_each_others_changes(env):
    tid = await make_table(env)
    anna, ben = Client("anna"), Client("ben")
    for c in (anna, ben):
        c.send(type="subscribe", channel=f"table:{tid}")
        snap = await c.recv_type("snapshot")
        assert snap["seq"] == 1 and snap["data"]["table"]["id"] == tid and snap["data"]["rows"] == []

    b1 = batch(insert_row(tid, zid("row")))
    anna.send(type="ops", batch=b1)
    ack = await anna.recv_type("ack")
    assert ack["batch_id"] == b1["batch_id"] and ack["seq"] == {f"table:{tid}": 2}
    seen = await ben.recv_type("ops")
    assert seen["channel"] == f"table:{tid}" and seen["seq"] == 2 and seen["batch_id"] == b1["batch_id"]
    assert seen["actor"]["id"] == USERS["anna"][0] and seen["ops"][0]["op"] == "row.insert"
    echo = await anna.recv_type("ops")  # auch der Absender bekommt seq 2 (sonst hätte er eine Lücke)
    assert echo["seq"] == 2 and echo["batch_id"] == b1["batch_id"]

    b2 = batch(insert_row(tid))
    ben.send(type="ops", batch=b2)
    await ben.recv_type("ack")
    assert (await anna.recv_type("ops", batch_id=b2["batch_id"]))["seq"] == 3
    await anna.disconnect(); await ben.disconnect()


async def test_reconnect_with_since_catches_up_gaplessly(env):
    tid = await make_table(env)
    anna, ben = Client("anna"), Client("ben")
    anna.send(type="subscribe", channel=f"table:{tid}")
    assert (await anna.recv_type("snapshot"))["seq"] == 1
    await anna.disconnect()

    ben.send(type="subscribe", channel=f"table:{tid}")
    await ben.recv_type("snapshot")
    ids = []
    for _ in range(3):
        b = batch(insert_row(tid))
        ids.append(b["batch_id"])
        ben.send(type="ops", batch=b)
        await ben.recv_type("ack")

    anna = Client("anna")  # Reconnect mit letzter bekannter seq
    anna.send(type="subscribe", channel=f"table:{tid}", since=1)
    got = [await anna.recv() for _ in range(3)]
    assert [(m["type"], m["seq"], m["batch_id"]) for m in got] == [("ops", 2 + i, ids[i]) for i in range(3)]
    b4 = batch(insert_row(tid))
    ben.send(type="ops", batch=b4)
    live = await anna.recv_type("ops")
    assert live["seq"] == 5 and live["batch_id"] == b4["batch_id"]
    await anna.expect_silence()  # nichts doppelt
    await anna.disconnect(); await ben.disconnect()


async def test_since_current_sends_nothing_and_unplausible_since_gives_snapshot(env, monkeypatch):
    tid = await make_table(env)
    c = Client("anna")
    c.send(type="subscribe", channel=f"table:{tid}", since=1)
    await c.expect_silence()
    c.send(type="subscribe", channel=f"table:{tid}", since=99)  # Client ist dem Server voraus -> Snapshot
    assert (await c.recv_type("snapshot"))["seq"] == 1
    for _ in range(3):
        c.send(type="ops", batch=batch(insert_row(tid)))
        await c.recv_type("ack")
    monkeypatch.setattr(hub, "CATCHUP_LIMIT", 2)  # Lücke 3 > 2 -> Snapshot statt Nachholen
    c.send(type="subscribe", channel=f"table:{tid}", since=1)
    snap = await c.recv_type("snapshot")
    assert snap["seq"] == 4 and len(snap["data"]["rows"]) == 3
    await c.disconnect()


async def test_snapshot_workspace_and_missing_since_log_gap(env):
    tid = await make_table(env)
    c = Client("ben")
    c.send(type="subscribe", channel="workspace")
    snap = await c.recv_type("snapshot")
    assert any(t["id"] == tid for t in snap["data"]["tables"]) and "roles" in snap["data"]
    # Log-Lücke (z. B. aufgeräumt) -> Snapshot statt lückenhaftem Nachholen
    async with env.begin() as conn:
        await conn.execute(text("DELETE FROM oplog WHERE channel = :c AND seq = 1"), {"c": f"table:{tid}"})
    c.send(type="ops", batch=batch(insert_row(tid)))
    await c.recv_type("ack")
    c.send(type="subscribe", channel=f"table:{tid}", since=0)
    assert (await c.recv_type("snapshot"))["seq"] == 2
    await c.disconnect()


async def test_listener_reconnect_delivers_missed_ops(env):
    tid = await make_table(env)
    ben = Client("ben")
    ben.send(type="subscribe", channel=f"table:{tid}")
    await ben.recv_type("snapshot")
    await hub._pg.close()  # LISTEN-Verbindung bricht weg, während jemand schreibt
    await pipeline.apply_batch(pipeline.OpBatch.model_validate(batch(insert_row(tid))),
                               Actor(type="system", id="workflow"))
    msg = await ben.recv_type("ops")
    assert msg["seq"] == 2
    await ben.disconnect()


# ── Rechte ───────────────────────────────────────────────────────────────────


async def test_subscribe_without_permission_is_rejected(env):
    async with env.begin() as c:
        await c.execute(text("INSERT INTO documents (id, workspace_id, title) VALUES (:i, 'ws_demo', 'D')"),
                        {"i": "doc_zz15a"})
        await c.execute(text("""INSERT INTO workflows (id, workspace_id, key, name, draft)
                                VALUES ('wf_zz15', 'ws_demo', 'wfzz15', 'W', '{}')"""))
        await c.execute(text("""INSERT INTO runs (id, workflow_id, version, title, status, started_by, started_by_id)
                                VALUES ('run_zz15', 'wf_zz15', 1, 'R', 'active', '{}', :u)"""),
                        {"u": USERS["ben"][0]})
    ben, cy, anna = Client("ben"), Client("cy"), Client("anna")

    cy.send(type="subscribe", channel=f"user:{USERS['ben'][0]}")
    rej = await cy.recv_type("reject")
    assert rej["batch_id"] == f"subscribe:user:{USERS['ben'][0]}" and rej["error"]["code"] == "FORBIDDEN"
    cy.send(type="subscribe", channel="run:run_zz15")
    assert (await cy.recv_type("reject"))["error"]["code"] == "FORBIDDEN"
    cy.send(type="subscribe", channel="doc:doc_gibt_es_nicht")
    assert (await cy.recv_type("reject"))["error"]["code"] == "NOT_FOUND"
    cy.send(type="subscribe", channel="bogus:1")
    assert (await cy.recv_type("reject"))["error"]["code"] == "VALIDATION"
    await cy.expect_silence()  # kein Snapshot, kein Abo
    assert "run:run_zz15" not in hub._subscribers

    for c, channel in ((ben, "run:run_zz15"), (anna, "run:run_zz15"), (ben, f"user:{USERS['ben'][0]}"),
                       (cy, "doc:doc_zz15a")):
        c.send(type="subscribe", channel=channel)
        assert (await c.recv_type("snapshot"))["channel"] == channel

    async with env.begin() as c:  # Aufgabe mit cy als Kandidat -> cy darf den Run lesen
        await c.execute(text("""INSERT INTO tasks (id, run_id, step, status, candidate_users)
                                VALUES ('tsk_zz15', 'run_zz15', 's', 'open', ARRAY[:u])"""), {"u": USERS["cy"][0]})
    cy.send(type="subscribe", channel="run:run_zz15")
    snap = await cy.recv_type("snapshot", channel="run:run_zz15")
    assert snap["data"]["run"]["id"] == "run_zz15" and snap["data"]["task"]["id"] == "tsk_zz15"
    cy.send(type="subscribe", channel=f"user:{USERS['cy'][0]}")
    user_snap = await cy.recv_type("snapshot")
    assert [t["id"] for t in user_snap["data"]["tasks"]] == ["tsk_zz15"]
    for c in (ben, cy, anna):
        await c.disconnect()


# ── ack / reject ─────────────────────────────────────────────────────────────


async def test_reject_and_idempotent_ack(env):
    ben = Client("ben")
    tid = zid("tbl")
    b = batch(new_table(tid))  # Ben hat keine Rolle einkauf
    ben.send(type="ops", batch=b)
    rej = await ben.recv_type("reject")
    assert rej["batch_id"] == b["batch_id"] and rej["error"]["code"] == "FORBIDDEN"

    anna = Client("anna")
    ok = batch(new_table(tid), batch_id=zid("b"))
    anna.send(type="ops", batch=ok)
    first = await anna.recv_type("ack")
    anna.send(type="ops", batch=ok)  # Wiederholung mit gleicher batch_id
    assert (await anna.recv_type("ack")) == first

    ben.send(type="ops", batch={"batch_id": "b_zz15bad", "ops": [{"op": "row.explode"}]})
    bad = await ben.recv_type("reject")
    assert bad["batch_id"] == "b_zz15bad" and bad["error"]["code"] == "VALIDATION"
    ben.send(type="quatsch")
    assert (await ben.recv_type("reject"))["batch_id"] == "invalid"
    await ben.disconnect(); await anna.disconnect()


async def test_unsubscribe_stops_events(env):
    tid = await make_table(env)
    anna, ben = Client("anna"), Client("ben")
    for c in (anna, ben):
        c.send(type="subscribe", channel=f"table:{tid}")
        await c.recv_type("snapshot")
    ben.send(type="unsubscribe", channel=f"table:{tid}")
    await asyncio.sleep(0.1)
    anna.send(type="ops", batch=batch(insert_row(tid)))
    await anna.recv_type("ack")
    await anna.recv_type("ops")
    await ben.expect_silence()
    await anna.disconnect(); await ben.disconnect()


# ── Präsenz ──────────────────────────────────────────────────────────────────


async def test_presence_editing_and_block_in_use(env):
    async with env.begin() as c:
        await c.execute(text("INSERT INTO documents (id, workspace_id, title) VALUES ('doc_zz15p', 'ws_demo', 'D')"))
    ch = "doc:doc_zz15p"
    anna, ben = Client("anna"), Client("ben")
    anna.send(type="subscribe", channel=ch)
    await anna.recv_type("snapshot")
    pres = await anna.recv_type("presence")
    assert [a["actor"]["id"] for a in pres["actors"]] == [USERS["anna"][0]]
    ben.send(type="subscribe", channel=ch)
    await ben.recv_type("snapshot")
    assert len((await ben.recv_type("presence"))["actors"]) == 2

    ben.send(type="presence", channel=ch, state={"cursor": {"block": "blk_7", "offset": 3}, "editing": "blk_7"})
    seen = await anna.recv_type("presence")
    while not any(a["state"]["editing"] for a in seen["actors"]):
        seen = await anna.recv_type("presence")
    editor = presence.editing_by(ch, "blk_7")
    assert editor is not None and editor.id == USERS["ben"][0]

    agent = Actor(type="agent", id="agt_zz15", on_behalf_of=USERS["anna"][0], name="Assistent")
    with pytest.raises(PipelineError) as exc:
        presence.check_block_free(ch, "blk_7", agent)
    assert exc.value.error.code == "BLOCK_IN_USE" and "Ben" in exc.value.error.message
    presence.check_block_free(ch, "blk_other", agent)  # anderer Block ist frei
    presence.check_block_free(ch, "blk_7", Actor(type="user", id=USERS["anna"][0]))  # Menschen nie blockiert

    ben.send(type="presence", channel="doc:nicht_abonniert", state={})
    assert (await ben.recv_type("reject"))["error"]["code"] == "FORBIDDEN"

    await ben.disconnect()  # Trennen räumt Präsenz auf
    left = await anna.recv_type("presence")
    while len(left["actors"]) != 1:
        left = await anna.recv_type("presence")
    assert presence.editing_by(ch, "blk_7") is None
    await anna.disconnect()


async def test_editing_expires(env, monkeypatch):
    actor = Actor(type="user", id=USERS["ben"][0], name="Ben")
    await presence.update("doc:zz15", actor, PresenceState(editing="blk_1"), conn_id="c1")
    assert presence.editing_by("doc:zz15", "blk_1") == actor
    monkeypatch.setattr(presence, "EDITING_TTL", 0.05)
    await asyncio.sleep(0.1)
    assert presence.editing_by("doc:zz15", "blk_1") is None
    assert presence.actors("doc:zz15")[0].state.editing is None
    presence.check_block_free("doc:zz15", "blk_1", Actor(type="agent", id="agt_x"))
    assert presence.sweep() == ["doc:zz15"]


async def test_presence_is_replicated_between_instances(env, monkeypatch):
    """Eine fremde Instanz meldet Präsenz per NOTIFY; die eigene übernimmt sie, ignoriert aber eigene Echos."""
    ch = "doc:zz15x"
    other = {"i": "andere-instanz", "channel": ch, "key": "k1",
             "actor": {"type": "user", "id": "usr_zz15ben", "name": "Ben"}, "state": {"editing": "blk_9"}}
    await hub._notify("presence", other)
    for _ in range(50):
        if presence.editing_by(ch, "blk_9"):
            break
        await asyncio.sleep(0.05)
    assert presence.editing_by(ch, "blk_9").id == "usr_zz15ben"
    await hub._notify("presence", {**other, "state": None})
    for _ in range(50):
        if not presence.editing_by(ch, "blk_9"):
            break
        await asyncio.sleep(0.05)
    assert presence.editing_by(ch, "blk_9") is None
    # eigene NOTIFYs (gleiche Instanz-ID) werden nicht doppelt angewendet
    assert presence.apply_remote({**other, "i": presence.INSTANCE_ID}) is None


async def test_publish_with_seq_notifies_and_without_goes_local(env):
    tid = await make_table(env)
    c = Client("anna")
    c.send(type="subscribe", channel=f"table:{tid}")
    await c.recv_type("snapshot")
    await hub.publish(f"table:{tid}", {"type": "hinweis", "text": "hallo"})
    assert (await c.recv_type("hinweis"))["channel"] == f"table:{tid}"
    # Eintrag steht im Log, NOTIFY kam von außerhalb der Pipeline
    async with env.begin() as conn:
        await conn.execute(text("INSERT INTO channels (id, seq) VALUES (:c, 2) ON CONFLICT (id) DO UPDATE SET seq = 2"),
                           {"c": f"table:{tid}"})
        await conn.execute(text("""INSERT INTO oplog (channel, seq, batch_id, actor, ops)
                                   VALUES (:c, 2, 'b_zz15pub', '{"type":"system","id":"scheduler"}', '[]')"""),
                           {"c": f"table:{tid}"})
    await hub.publish(f"table:{tid}", {"seq": 2})
    msg = await c.recv_type("ops")
    assert msg["seq"] == 2 and msg["batch_id"] == "b_zz15pub" and msg["actor"]["id"] == "scheduler"
    await c.disconnect()


def test_snapshot_row_keeps_text_type_columns():
    """2.I2: run_events.type / notifications.type sind Text, kein JSON (sonst scheitern user:/run:-Snapshots)."""
    from app.realtime.snapshots import _row

    out = _row({"type": "task_created", "payload": '{"run": "run_1"}', "text": "Hallo"})
    assert out == {"type": "task_created", "payload": {"run": "run_1"}, "text": "Hallo"}
