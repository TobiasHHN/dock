"""Statusansicht, Listen, Kommentare und Live-Benachrichtigungen (Task 4.4, L 5.10, T 4, T 5.7, L 8.1).

Testdaten tragen den Marker `zz44` und werden nach jedem Test vollständig entfernt.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import config
from app.api import ws as ws_module
from app.auth import CurrentUser, create_access_token, current_user
from app.db import session as db_mod
from app.db.session import get_session
from app.main import app
from app.ops import pipeline
from app.ops.errors import PipelineError
from app.realtime import hub, presence
from app.schemas.common import Actor
from app.schemas.ops import OpBatch
from tests.test_form_run import build_order_process

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock")

ANNA = Actor(type="user", id="usr_zz44anna", name="Anna Einkauf")
BEN = Actor(type="user", id="usr_zz44ben", name="Ben Mitarbeiter")
CHEF1 = Actor(type="user", id="usr_zz44chef1", name="Chef Eins")
CHEF2 = Actor(type="user", id="usr_zz44chef2", name="Chef Zwei")
FREMD = Actor(type="user", id="usr_zz44fremd", name="Fremd Person")
BEN_AGENT = Actor(type="agent", id="agt_zz44ben", on_behalf_of="usr_zz44ben", name="Bens Assistent")


def zid(prefix: str) -> str:
    return f"{prefix}_zz44{uuid.uuid4().hex[:10]}"


def zkey(name: str) -> str:
    return f"zz44{name}{uuid.uuid4().hex[:6]}"


class FakeSocket:
    def __init__(self, incoming: list[dict]):
        self._in = asyncio.Queue()
        for m in incoming:
            self._in.put_nowait(m)
        self.sent: asyncio.Queue = asyncio.Queue()
        self.accepted = False
        self.closed_code: int | None = None
        self.headers = {}
        self.query_params = {}

    async def accept(self):
        self.accepted = True

    async def close(self, code: int = 1000):
        self.closed_code = code

    async def send_json(self, data: dict):
        await self.sent.put(data)

    async def receive_json(self):
        return await self._in.get()

    async def next_msg(self, timeout: float = 5.0) -> dict:
        return await asyncio.wait_for(self.sent.get(), timeout)


@pytest_asyncio.fixture
async def env(monkeypatch):
    eng = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with eng.connect() as c:
            await c.execute(text("SELECT 1 FROM batches LIMIT 1"))
    except Exception:
        pytest.skip("Postgres nicht erreichbar")
    sm = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "SessionLocal", sm)
    monkeypatch.setattr(pipeline, "SessionLocal", sm)
    monkeypatch.setattr(config.settings, "database_url", DB_URL)
    monkeypatch.setattr(hub, "_RECONNECT_DELAY", 0.2)
    monkeypatch.setattr(hub, "_TICK", 0.1)

    async def fake_enqueue(kind, id_):
        pass

    monkeypatch.setattr(pipeline, "enqueue_reembed", fake_enqueue)

    async with eng.begin() as c:
        for actor, role in ((ANNA, "einkauf"), (BEN, "mitarbeiter")):
            await c.execute(
                text("""INSERT INTO users (id, name, email, active) VALUES (:id, :name, :email, true)
                        ON CONFLICT (id) DO NOTHING"""),
                {"id": actor.id, "name": actor.name, "email": f"{actor.id}@zz44.local"},
            )
            await c.execute(
                text("""INSERT INTO roles (id, workspace_id, key, name) VALUES (:i, 'ws_demo', :k, :k)
                        ON CONFLICT (workspace_id, key) DO NOTHING"""),
                {"i": f"rol_zz44{role}", "k": role},
            )
            await c.execute(
                text("""INSERT INTO member_roles (workspace_id, member_id, role_id)
                        SELECT 'ws_demo', :m, id FROM roles WHERE workspace_id = 'ws_demo' AND key = :k
                        ON CONFLICT DO NOTHING"""),
                {"m": actor.id, "k": role},
            )
        for u in (CHEF1, CHEF2, FREMD):
            await c.execute(
                text("""INSERT INTO users (id, name, email, active) VALUES (:id, :name, :email, true)
                        ON CONFLICT (id) DO NOTHING"""),
                {"id": u.id, "name": u.name, "email": f"{u.id}@zz44.local"},
            )
        await c.execute(
            text("""INSERT INTO agents (id, workspace_id, name, active) VALUES (:id, 'ws_demo', :name, true)
                    ON CONFLICT (id) DO NOTHING"""),
            {"id": BEN_AGENT.id, "name": BEN_AGENT.name},
        )
    presence.reset()
    await hub.start_listener()
    assert await hub.wait_ready(), "LISTEN-Verbindung kam nicht zustande"
    yield eng, sm
    await hub.stop_listener()
    presence.reset()

    async with eng.begin() as c:
        for stmt in (
            "DELETE FROM oplog WHERE batch_id LIKE '%zz44%' OR channel LIKE '%zz44%'",
            "DELETE FROM batches WHERE batch_id LIKE '%zz44%'",
            "DELETE FROM channels WHERE id LIKE '%zz44%'",
            "DELETE FROM form_drafts WHERE form_block LIKE '%zz44%' OR scope LIKE '%zz44%'",
            "DELETE FROM form_submissions WHERE id LIKE '%zz44%' OR form_block LIKE '%zz44%'",
            'DELETE FROM "references" WHERE source_id LIKE \'%zz44%\' OR target_id LIKE \'%zz44%\'',
            "DELETE FROM notifications WHERE run_id LIKE '%zz44%' OR recipient_id LIKE '%zz44%'",
            "DELETE FROM run_events WHERE run_id LIKE '%zz44%'",
            "DELETE FROM tasks WHERE run_id LIKE '%zz44%'",
            "DELETE FROM runs WHERE id LIKE '%zz44%' OR workflow_id LIKE '%zz44%'",
            "DELETE FROM workflows WHERE id LIKE '%zz44%'",
            "DELETE FROM documents WHERE id LIKE '%zz44%'",
            "DELETE FROM row_links WHERE from_row IN (SELECT id FROM rows WHERE table_id LIKE '%zz44%') "
            "OR to_row IN (SELECT id FROM rows WHERE table_id LIKE '%zz44%')",
            "DELETE FROM rows WHERE id LIKE '%zz44%' OR table_id LIKE '%zz44%'",
            "DELETE FROM tables WHERE id LIKE '%zz44%'",
            "DELETE FROM member_roles WHERE member_id LIKE '%zz44%' OR role_id LIKE '%zz44%'",
            "DELETE FROM roles WHERE id LIKE '%zz44%'",
            "DELETE FROM agents WHERE id LIKE '%zz44%'",
            "DELETE FROM users WHERE id LIKE '%zz44%'",
        ):
            await c.execute(text(stmt))
    await eng.dispose()


async def q(engine, sql, **params):
    async with engine.connect() as c:
        return (await c.execute(text(sql), params)).mappings().all()


async def run_ops(*ops, actor=ANNA):
    return await pipeline.apply_batch(OpBatch.model_validate({"batch_id": zid("b"), "ops": list(ops)}), actor)


async def add_member(engine, member: str, role_id: str):
    async with engine.begin() as c:
        await c.execute(
            text("INSERT INTO member_roles (workspace_id, member_id, role_id) VALUES ('ws_demo', :m, :r) "
                 "ON CONFLICT DO NOTHING"),
            {"m": member, "r": role_id},
        )


def _zz44_order_process():
    """Nutzt build_order_process aus test_form_run, ersetzt Präfix-Marker durch zz44 für sauberes Cleanup."""
    raw = json.dumps(build_order_process()).replace("_zz43", "_zz44").replace("zz43", "zz44")
    return json.loads(raw)


def _api_client(sm, holder: dict[str, CurrentUser]):
    async def session():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[current_user] = lambda: holder["user"]
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_status_view_lists_tasks_and_comments(env):
    eng, sm = env
    ex = _zz44_order_process()
    await run_ops(*ex["ops"])
    await add_member(eng, CHEF1.id, ex["tl"])
    await add_member(eng, CHEF2.id, ex["tl"])
    await add_member(eng, BEN.id, ex["tl"])  # Ben darf trotzdem nicht genehmigen (Vier-Augen)

    run_id = zid("run")
    await run_ops({"op": "run.start", "id": run_id, "workflow": ex["wf_key"]}, actor=BEN_AGENT)
    await run_ops(
        {"op": "form.submit", "submission_id": zid("sub"), "form_block": ex["f1"], "button": "submit", "run": run_id,
         "values": {"name": "Ben Mitarbeiter", "kostenstelle": "4711",
                    "artikel": [{"artikelname": "Monitor", "preis": 299, "anzahl": 2}]}},
        actor=BEN_AGENT,
    )

    holder = {"user": CurrentUser(id=BEN.id, name=BEN.name, email="b@zz44.local", roles=["mitarbeiter", ex["tl_key"]])}
    try:
        async with _api_client(sm, holder) as client:
            # GET /api/runs/{run}: L 5.10-Struktur
            r = await client.get(f"/api/runs/{run_id}")
            assert r.status_code == 200
            view = r.json()
            assert view["id"] == run_id
            assert view["workflow"] == {"id": ex["wf"], "name": "Bestellprozess", "version": 1}
            assert view["status"] == "active"
            assert view["current"]["step"] == "genehmigung"
            assert view["current"]["label"] == "Wartet auf Genehmigung"
            assert view["current"]["candidates"]["roles"] == [{"key": ex["tl_key"], "name": "Teamleitung"}]
            assert view["current"]["due_at"] is not None
            assert [s["step"] for s in view["steps"]] == ["erfassen", "genehmigung", "bestellung"]
            assert [s["state"] for s in view["steps"]] == ["done", "active", "pending"]
            assert view["steps"][0]["by"] == "Bens Assistent im Auftrag von Ben Mitarbeiter"
            assert view["steps"][0]["label"] == "Eingereicht"
            assert [e["type"] for e in view["events"]] == ["started", "step_entered", "step_completed", "step_entered"]

            # GET /api/runs: Meine Anträge (auch bei Agent-Start)
            my_runs = (await client.get("/api/runs", params={"started_by": "me", "workflow": ex["wf_key"]})).json()
            assert [x["id"] for x in my_runs] == [run_id]
            assert my_runs[0]["status_label"] == "Wartet auf Genehmigung"

            # Fremder darf Run nicht sehen
            holder["user"] = CurrentUser(id=FREMD.id, name=FREMD.name, email="f@zz44.local", roles=[])
            assert (await client.get(f"/api/runs/{run_id}")).status_code == 403
            assert (await client.get("/api/runs/run_zz44nix")).status_code == 404
            assert (await client.get("/api/runs", params={"started_by": "any", "workflow": ex["wf_key"]})).json() == []

            # Vier-Augen: Ben sieht tsk_2 nicht in GET /api/tasks
            holder["user"] = CurrentUser(id=BEN.id, name=BEN.name, email="b@zz44.local", roles=["mitarbeiter", ex["tl_key"]])
            assert (await client.get("/api/tasks", params={"workflow": ex["wf_key"]})).json() == []

            # Chef1 sieht Aufgabe und übernimmt sie -> Chef2 sieht sie mit can_act=False und claimed_by_name
            holder["user"] = CurrentUser(id=CHEF1.id, name=CHEF1.name, email="c1@zz44.local", roles=[ex["tl_key"]])
            tasks1 = (await client.get("/api/tasks", params={"workflow": ex["wf_key"]})).json()
            assert len(tasks1) == 1 and tasks1[0]["can_act"] is True
            t2_id = tasks1[0]["task"]["id"]

            detail = (await client.get(f"/api/tasks/{t2_id}")).json()
            assert detail["form_block"] == ex["f2"]
            assert detail["can_act"] is True
            assert [b["id"] for b in detail["buttons"]] == ["approve", "reject"]
            assert "Bestellung von Ben Mitarbeiter für Kostenstelle 4711, Summe: 299" in detail["document_markdown"]
            assert detail["fields"][0]["key"] == "kommentar"

            await run_ops({"op": "task.claim", "task": t2_id}, actor=CHEF1)
            holder["user"] = CurrentUser(id=CHEF2.id, name=CHEF2.name, email="c2@zz44.local", roles=[ex["tl_key"]])
            tasks2 = (await client.get("/api/tasks", params={"workflow": ex["wf_key"]})).json()
            assert len(tasks2) == 1 and tasks2[0]["can_act"] is False and tasks2[0]["claimed_by_name"] == CHEF1.name
            detail2 = (await client.get(f"/api/tasks/{t2_id}")).json()
            assert detail2["can_act"] is False and detail2["buttons"] == []

            # run.comment: Chef2 darf kommentieren, Fremder nicht, leerer Text -> VALIDATION
            with pytest.raises(PipelineError) as exc_f:
                await run_ops({"op": "run.comment", "run": run_id, "text": "Hallo"}, actor=FREMD)
            assert exc_f.value.error.code == "FORBIDDEN"
            with pytest.raises(PipelineError) as exc_v:
                await run_ops({"op": "run.comment", "run": run_id, "text": "   "}, actor=CHEF2)
            assert exc_v.value.error.code == "VALIDATION"

            await run_ops({"op": "run.comment", "run": run_id, "text": "Brauchen wir 2?"}, actor=CHEF2)
            holder["user"] = CurrentUser(id=BEN.id, name=BEN.name, email="b@zz44.local", roles=["mitarbeiter"])
            evts = (await client.get(f"/api/runs/{run_id}")).json()["events"]
            assert evts[-1]["type"] == "comment" and evts[-1]["text"] == "Brauchen wir 2?"
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(current_user, None)


async def test_notifications_and_live_websocket_delivery_to_role(env):
    eng, sm = env
    ex = _zz44_order_process()
    await run_ops(*ex["ops"])
    await add_member(eng, CHEF1.id, ex["tl"])
    await add_member(eng, CHEF2.id, ex["tl"])

    run_id = zid("run")
    await run_ops({"op": "run.start", "id": run_id, "workflow": ex["wf_key"]}, actor=BEN)

    # Beide Chefs verbinden sich via WebSocket und abonnieren user:<id>
    s_chef1 = FakeSocket([{"type": "subscribe", "channel": f"user:{CHEF1.id}"}])
    s_chef2 = FakeSocket([{"type": "subscribe", "channel": f"user:{CHEF2.id}"}])
    task1 = asyncio.create_task(ws_module.ws(s_chef1, token=create_access_token(CHEF1.id, [ex["tl_key"]])))
    task2 = asyncio.create_task(ws_module.ws(s_chef2, token=create_access_token(CHEF2.id, [ex["tl_key"]])))

    try:
        snap1 = await s_chef1.next_msg()
        snap2 = await s_chef2.next_msg()
        assert snap1["type"] == "snapshot" and snap2["type"] == "snapshot"

        # Ben reicht erfassen ein -> Aufgabe geht an Rolle tl (CHEF1 + CHEF2)
        await run_ops(
            {"op": "form.submit", "submission_id": zid("sub"), "form_block": ex["f1"], "button": "submit", "run": run_id,
             "values": {"name": "Ben", "kostenstelle": "4711",
                        "artikel": [{"artikelname": "Monitor", "preis": 100, "anzahl": 1}]}},
            actor=BEN,
        )

        # Beide Rollenmitglieder bekommen live die Benachrichtigung (und das ops-Event)
        async def wait_notification(sock: FakeSocket) -> dict:
            for _ in range(5):
                msg = await sock.next_msg()
                if msg.get("type") == "notification":
                    return msg
            raise AssertionError("Keine Live-Benachrichtigung erhalten")

        n1 = await wait_notification(s_chef1)
        n2 = await wait_notification(s_chef2)
        assert n1["notification"]["type"] == "step_entered"
        assert n1["notification"]["run_id"] == run_id
        assert n2["notification"]["type"] == "step_entered"

        # Ben (Antragsteller) hat Benachrichtigung für step_completed bekommen
        holder = {"user": CurrentUser(id=BEN.id, name=BEN.name, email="b@zz44.local", roles=["mitarbeiter"])}
        try:
            async with _api_client(sm, holder) as client:
                ben_notes = (await client.get("/api/notifications", params={"unread": "true"})).json()
                assert any(n["type"] == "step_completed" and n["run_id"] == run_id for n in ben_notes)

                # Markieren als gelesen
                nid = ben_notes[0]["id"]
                read_res = await client.post(f"/api/notifications/{nid}/read")
                assert read_res.status_code == 200 and read_res.json()["read_at"] is not None
                unread_after = (await client.get("/api/notifications", params={"unread": "true"})).json()
                assert all(n["id"] != nid for n in unread_after)

                # Fremde Benachrichtigung -> 403
                holder["user"] = CurrentUser(id=CHEF1.id, name=CHEF1.name, email="c1@zz44.local", roles=[ex["tl_key"]])
                assert (await client.post(f"/api/notifications/{nid}/read")).status_code == 403
        finally:
            app.dependency_overrides.pop(get_session, None)
            app.dependency_overrides.pop(current_user, None)
    finally:
        task1.cancel()
        task2.cancel()
        await asyncio.gather(task1, task2, return_exceptions=True)


async def test_unassigned_and_cancelled_notifications(env):
    eng, _ = env
    wf, doc = zid("wf"), zid("doc")
    definition = {
        "start": "s1",
        "managers": [{"kind": "user", "user": ANNA.id}],
        "steps": [
            {"key": "s1", "name": "S1", "document": doc, "assignees": [{"kind": "user", "user": BEN.id}],
             "exclude_starter": True},
        ],
        "transitions": [{"from": "s1", "on": "ok", "to": "end"}],
    }
    await run_ops(
        {"op": "workflow.create", "id": wf, "key": zkey("unass"), "name": "Unassigned", "definition": definition},
        {"op": "doc.create", "id": doc, "title": "S1", "owner": {"workflow": wf, "step": "s1"},
         "blocks": [{"id": zid("blk"), "type": "form", "props": {
             "actions": [], "buttons": [{"id": "ok", "label": "OK", "outcome": "ok"}]}, "children": []}]},
        {"op": "workflow.publish", "workflow": wf},
    )
    run_id = zid("run")
    await run_ops({"op": "run.start", "id": run_id, "workflow": wf}, actor=BEN)
    anna_notes = await q(eng, "SELECT type FROM notifications WHERE recipient_id = :u AND run_id = :r",
                         u=ANNA.id, r=run_id)
    assert {"step_entered", "unassigned"} <= {n["type"] for n in anna_notes}

    await run_ops({"op": "run.cancel", "run": run_id, "reason": "Abbruch"}, actor=ANNA)
    ben_notes = await q(eng, "SELECT type FROM notifications WHERE recipient_id = :u AND run_id = :r",
                        u=BEN.id, r=run_id)
    assert any(n["type"] == "cancelled" for n in ben_notes)
