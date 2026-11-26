"""Workflow-Engine für Runs und Aufgaben (Task 4.2, L 5.4, L 5.8, L 5.9).

Reine Unit-Tests (`can_act`, `parse_iso_duration`) ohne DB sowie Postgres-Integrationstests für den kompletten
Bestellprozess (Happy Path + Ablehnung), Startberechtigung, Vier-Augen-Prinzip (`exclude_starter`, `exclude_steps`),
`expr`-Assignees mit `lookup`, `unassigned`-Fallback, Wildcard-Übergang `*`, Wiederholungsbesuch, `run.cancel`,
`task.claim`/`release`/`reassign` und sofortige Wirkung von `user.set_roles`.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain import tasks as T
from app.domain import workflows as W
from app.ops import pipeline
from app.ops.context import OpContext
from app.ops.errors import PipelineError
from app.schemas.common import Actor
from app.schemas.ops import OpBatch
from app.schemas.workflows import Task, TaskCandidates

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock")

ANNA = Actor(type="user", id="usr_zz42anna", name="Anna Einkauf")
BEN = Actor(type="user", id="usr_zz42ben", name="Ben Mitarbeiter")
CHEF1 = Actor(type="user", id="usr_zz42chef1", name="Chef Eins")
CHEF2 = Actor(type="user", id="usr_zz42chef2", name="Chef Zwei")
CHEF_AGENT = Actor(type="agent", id="agt_zz42ass", on_behalf_of="usr_zz42chef1", name="Chef-Assistent")


def zid(prefix: str) -> str:
    return f"{prefix}_zz42{uuid.uuid4().hex[:10]}"


def zkey(name: str) -> str:
    return f"zz42{name}{uuid.uuid4().hex[:6]}"


# ── Reine Unit-Tests (ohne DB) ───────────────────────────────────────────────


def _task(*, status="open", users=(), roles=(), excluded=(), claimed_by=None) -> Task:
    return Task(
        id="tsk_1",
        run_id="run_1",
        step="genehmigung",
        status=status,
        candidates=TaskCandidates(users=list(users), roles=list(roles)),
        excluded=list(excluded),
        claimed_by=claimed_by,
        created_at=datetime.now(timezone.utc),
    )


def test_can_act_rules():
    # User-Kandidat
    assert T.can_act(BEN, [], _task(users=[BEN.id])) is True
    assert T.can_act(ANNA, [], _task(users=[BEN.id])) is False

    # Rollen-Kandidat
    assert T.can_act(CHEF1, ["rol_tl", "teamleitung"], _task(roles=["rol_tl"])) is True
    assert T.can_act(BEN, ["mitarbeiter"], _task(roles=["rol_tl"])) is False

    # Agent on_behalf_of: zählt wie die vertretene Person (inkl. Ausschluss)
    assert T.can_act(CHEF_AGENT, ["rol_tl"], _task(roles=["rol_tl"])) is True
    assert T.can_act(CHEF_AGENT, ["rol_tl"], _task(roles=["rol_tl"], excluded=[CHEF1.id])) is False

    # Excluded trotz passender Rolle
    assert T.can_act(CHEF1, ["rol_tl"], _task(roles=["rol_tl"], excluded=[CHEF1.id])) is False

    # Claim durch mich vs. jemand anderen
    claimed_by_1 = _task(roles=["rol_tl"], claimed_by=CHEF1)
    assert T.can_act(CHEF1, ["rol_tl"], claimed_by_1) is True
    assert T.can_act(CHEF_AGENT, ["rol_tl"], claimed_by_1) is True
    assert T.can_act(CHEF2, ["rol_tl"], claimed_by_1) is False

    # Abgeschlossene oder abgebrochene Aufgabe
    assert T.can_act(CHEF1, ["rol_tl"], _task(status="done", roles=["rol_tl"])) is False
    assert T.can_act(CHEF1, ["rol_tl"], _task(status="cancelled", roles=["rol_tl"])) is False


def test_parse_iso_duration():
    assert W.parse_iso_duration("P2D") == timedelta(days=2)
    assert W.parse_iso_duration("P3D") == timedelta(days=3)
    assert W.parse_iso_duration("PT4H") == timedelta(hours=4)
    assert W.parse_iso_duration("P1W") == timedelta(days=7)
    assert W.parse_iso_duration("P1DT12H") == timedelta(days=1, hours=12)
    with pytest.raises(ValueError):
        W.parse_iso_duration("2 Tage")


# ── Postgres-Fixture & Hilfen ────────────────────────────────────────────────


@pytest_asyncio.fixture
async def engine(monkeypatch):
    eng = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with eng.connect() as c:
            await c.execute(text("SELECT 1 FROM batches LIMIT 1"))
    except Exception:
        pytest.skip("Postgres nicht erreichbar")
    sm = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", sm)

    async def fake_enqueue(kind, id_):
        pass

    monkeypatch.setattr(pipeline, "enqueue_reembed", fake_enqueue)

    async with eng.begin() as c:
        for actor, role in ((ANNA, "einkauf"), (BEN, "mitarbeiter")):
            await c.execute(
                text("""INSERT INTO users (id, name, email, active) VALUES (:id, :name, :email, true)
                        ON CONFLICT (id) DO NOTHING"""),
                {"id": actor.id, "name": actor.name, "email": f"{actor.id}@zz42.local"},
            )
            await c.execute(
                text("""INSERT INTO roles (id, workspace_id, key, name) VALUES (:i, 'ws_demo', :k, :k)
                        ON CONFLICT (workspace_id, key) DO NOTHING"""),
                {"i": f"rol_zz42{role}", "k": role},
            )
            await c.execute(
                text("""INSERT INTO member_roles (workspace_id, member_id, role_id)
                        SELECT 'ws_demo', :m, id FROM roles WHERE workspace_id = 'ws_demo' AND key = :k
                        ON CONFLICT DO NOTHING"""),
                {"m": actor.id, "k": role},
            )
        for u in (CHEF1, CHEF2):
            await c.execute(
                text("""INSERT INTO users (id, name, email, active) VALUES (:id, :name, :email, true)
                        ON CONFLICT (id) DO NOTHING"""),
                {"id": u.id, "name": u.name, "email": f"{u.id}@zz42.local"},
            )
        await c.execute(
            text("""INSERT INTO agents (id, workspace_id, name, active) VALUES (:id, 'ws_demo', :name, true)
                    ON CONFLICT (id) DO NOTHING"""),
            {"id": CHEF_AGENT.id, "name": CHEF_AGENT.name},
        )
    yield eng, sm

    async with eng.begin() as c:
        for stmt in (
            "DELETE FROM oplog WHERE batch_id LIKE '%zz42%'",
            "DELETE FROM batches WHERE batch_id LIKE '%zz42%'",
            "DELETE FROM channels WHERE id LIKE '%zz42%'",
            'DELETE FROM "references" WHERE source_id LIKE \'%zz42%\' OR target_id LIKE \'%zz42%\'',
            "DELETE FROM notifications WHERE run_id LIKE '%zz42%' OR recipient_id LIKE '%zz42%'",
            "DELETE FROM run_events WHERE run_id LIKE '%zz42%'",
            "DELETE FROM tasks WHERE run_id LIKE '%zz42%'",
            "DELETE FROM runs WHERE id LIKE '%zz42%' OR workflow_id LIKE '%zz42%'",
            "DELETE FROM workflows WHERE id LIKE '%zz42%'",
            "DELETE FROM documents WHERE id LIKE '%zz42%'",
            "DELETE FROM tables WHERE id LIKE '%zz42%'",
            "DELETE FROM member_roles WHERE member_id LIKE '%zz42%' OR role_id LIKE '%zz42%'",
            "DELETE FROM roles WHERE id LIKE '%zz42%'",
            "DELETE FROM agents WHERE id LIKE '%zz42%'",
            "DELETE FROM users WHERE id LIKE '%zz42%'",
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


async def do_complete_task(sm, task_id: str, button: dict, values: dict, results: dict, actor: Actor) -> dict:
    async with sm() as s:
        async with s.begin():
            ctx = OpContext(session=s, actor=actor)
            return await W.complete_task(ctx, task_id, button, values, results, actor)


def order_process_ops():
    """Kompletter Bestellprozess aus L 10.1 mit frischen zz42-IDs."""
    wf, wf_key = zid("wf"), zkey("bestell")
    tl, tl_key = zid("rol"), zkey("tl")
    s1, s2, s3 = zid("doc"), zid("doc"), zid("doc")
    best, art = zid("tbl"), zid("tbl")
    c_name, c_ks = zid("col"), zid("col")
    c_aname, c_apreis, c_abest = zid("col"), zid("col"), zid("col")

    def form_doc(doc_id, step_key, buttons, fields_children):
        return {
            "op": "doc.create",
            "id": doc_id,
            "title": step_key,
            "owner": {"workflow": wf, "step": step_key},
            "blocks": [
                {
                    "id": zid("blk"),
                    "type": "form",
                    "props": {"actions": [], "buttons": buttons},
                    "children": fields_children,
                }
            ],
        }

    definition = {
        "start": "erfassen",
        "starters": [],
        "managers": [{"kind": "role", "role": "einkauf"}],
        "run_title": "{{concat(\"Bestellung KS \", coalesce(run.steps.erfassen.values.kostenstelle, \"…\"), \" – \", run.starter.name)}}",
        "steps": [
            {"key": "erfassen", "name": "Bestellung erfassen", "status_label": "In Erfassung",
             "document": s1, "assignees": [{"kind": "starter"}]},
            {"key": "genehmigung", "name": "Genehmigung", "status_label": "Wartet auf Genehmigung",
             "document": s2, "assignees": [{"kind": "role", "role": tl_key}],
             "exclude_starter": True, "due_in": "P2D"},
            {"key": "bestellung", "name": "Bestellung auslösen", "status_label": "Wird bestellt",
             "document": s3, "assignees": [{"kind": "role", "role": "einkauf"}], "due_in": "P3D"},
        ],
        "transitions": [
            {"from": "erfassen", "on": "submitted", "to": "genehmigung"},
            {"from": "genehmigung", "on": "approved", "to": "bestellung"},
            {"from": "genehmigung", "on": "rejected", "to": "end"},
            {"from": "bestellung", "on": "ordered", "to": "end"},
        ],
    }

    ops = [
        {"op": "role.create", "id": tl, "key": tl_key, "name": "Teamleitung"},
        {"op": "table.create", "id": best, "key": zkey("best"), "name": "Bestellungen",
         "columns": [{"id": c_name, "key": "name", "name": "Name", "type": {"kind": "text"}},
                     {"id": c_ks, "key": "kostenstelle", "name": "KS", "type": {"kind": "text"}}]},
        {"op": "table.create", "id": art, "key": zkey("art"), "name": "Artikel",
         "columns": [{"id": c_aname, "key": "artikelname", "name": "Artikel", "type": {"kind": "text"}},
                     {"id": c_apreis, "key": "preis", "name": "Preis", "type": {"kind": "number", "decimals": 2}},
                     {"id": c_abest, "key": "bestellung", "name": "Bestellung", "type": {"kind": "text"}}]},
        {"op": "workflow.create", "id": wf, "key": wf_key, "name": "Bestellprozess", "definition": definition},
        form_doc(s1, "erfassen", [{"id": "submit", "label": "Eingereicht", "actions": [], "outcome": "submitted"}], [
            {"id": zid("blk"), "type": "field", "props": {"key": "name", "label": "Name", "input": "text"}},
            {"id": zid("blk"), "type": "field", "props": {"key": "kostenstelle", "label": "KS", "input": "text"}},
        ]),
        form_doc(s2, "genehmigung", [
            {"id": "approve", "label": "Genehmigt", "actions": [], "outcome": "approved"},
            {"id": "reject", "label": "Abgelehnt", "actions": [], "outcome": "rejected", "require": ["kommentar"]},
        ], [
            {"id": zid("blk"), "type": "field", "props": {"key": "kommentar", "label": "Kommentar", "input": "textarea"}},
        ]),
        form_doc(s3, "bestellung", [{"id": "ordered", "label": "Bestellt", "actions": [], "outcome": "ordered"}], [
            {"id": zid("blk"), "type": "field", "props": {"key": "lieferanten_nr", "label": "Nr.", "input": "text"}},
        ]),
        {"op": "workflow.publish", "workflow": wf},
    ]
    return {"wf": wf, "wf_key": wf_key, "tl": tl, "tl_key": tl_key, "ops": ops}


# ── Integrationstests ────────────────────────────────────────────────────────


async def test_order_process_happy_path(engine):
    eng, sm = engine
    ex = order_process_ops()
    await run_ops(*ex["ops"])
    await add_member(eng, CHEF1.id, ex["tl"])
    await add_member(eng, CHEF2.id, ex["tl"])
    # Ben bekommt auch die Rolle Teamleitung, um das Vier-Augen-Prinzip zu testen!
    await add_member(eng, BEN.id, ex["tl"])

    run_id = zid("run")
    res = await run_ops({"op": "run.start", "id": run_id, "workflow": ex["wf_key"]}, actor=BEN)
    start_out = res.results["0"]
    assert start_out["status"] == "active" and start_out["current_step"] == "erfassen"
    t1_id = start_out["task_id"]

    run_row = (await q(eng, "SELECT title, status, current_step FROM runs WHERE id = :r", r=run_id))[0]
    assert run_row["title"] == "Bestellung KS … – Ben Mitarbeiter"

    # Schritt 1: Ben erledigt erfassen
    out1 = await do_complete_task(
        sm, t1_id,
        {"id": "submit", "label": "Eingereicht", "outcome": "submitted"},
        {"name": "Ben", "kostenstelle": "4711"},
        {"order": {"id": "row_1"}},
        BEN,
    )
    assert out1["status"] == "active" and out1["current_step"] == "genehmigung"
    t2_id = out1["task_id"]

    # Titel wurde mit Kostenstelle neu ausgewertet
    run_row = (await q(eng, "SELECT title FROM runs WHERE id = :r", r=run_id))[0]
    assert run_row["title"] == "Bestellung KS 4711 – Ben Mitarbeiter"

    # Vier-Augen-Prinzip: Ben darf trotz Rolle Teamleitung nicht übernehmen oder genehmigen
    with pytest.raises(PipelineError) as exc:
        await run_ops({"op": "task.claim", "task": t2_id}, actor=BEN)
    assert exc.value.error.code == "FORBIDDEN"
    with pytest.raises(PipelineError) as exc2:
        await do_complete_task(sm, t2_id, {"id": "approve", "label": "Genehmigt", "outcome": "approved"}, {}, {}, BEN)
    assert exc2.value.error.code == "FORBIDDEN"

    # Chef1 übernimmt -> Chef2 ist blockiert
    await run_ops({"op": "task.claim", "task": t2_id}, actor=CHEF1)
    with pytest.raises(PipelineError) as exc_claim:
        await run_ops({"op": "task.claim", "task": t2_id}, actor=CHEF2)
    assert exc_claim.value.error.code == "TASK_CLAIMED"
    with pytest.raises(PipelineError) as exc_comp:
        await do_complete_task(sm, t2_id, {"id": "approve", "label": "Genehmigt", "outcome": "approved"}, {}, {}, CHEF2)
    assert exc_comp.value.error.code == "TASK_CLAIMED"
    with pytest.raises(PipelineError) as exc_rel:
        await run_ops({"op": "task.release", "task": t2_id}, actor=CHEF2)
    assert exc_rel.value.error.code == "FORBIDDEN"

    # Chef1 gibt frei, Chef-Agent im Auftrag von Chef1 genehmigt
    await run_ops({"op": "task.release", "task": t2_id}, actor=CHEF1)
    out2 = await do_complete_task(
        sm, t2_id, {"id": "approve", "label": "Genehmigt", "outcome": "approved"},
        {"kommentar": "Passt."}, {}, CHEF_AGENT,
    )
    assert out2["current_step"] == "bestellung"
    t3_id = out2["task_id"]

    t3 = (await q(eng, "SELECT due_at, candidate_roles FROM tasks WHERE id = :id", id=t3_id))[0]
    assert t3["due_at"] is not None
    assert len(t3["candidate_roles"]) == 1

    # Schritt 3: Anna (einkauf) schließt ab
    out3 = await do_complete_task(
        sm, t3_id, {"id": "ordered", "label": "Bestellt", "outcome": "ordered"},
        {"lieferanten_nr": "L-99"}, {}, ANNA,
    )
    assert out3 == {"status": "completed", "current_step": None, "result": {"outcome": "ordered", "label": "Bestellt"}}

    final_run = (await q(eng, "SELECT status, current_step, result, ended_at, steps FROM runs WHERE id = :r", r=run_id))[0]
    assert final_run["status"] == "completed" and final_run["current_step"] is None
    assert final_run["result"] == {"outcome": "ordered", "label": "Bestellt"}
    assert final_run["ended_at"] is not None
    assert final_run["steps"]["genehmigung"]["completed_by"]["on_behalf_of"] == CHEF1.id

    events = [r["type"] for r in await q(eng, "SELECT type FROM run_events WHERE run_id = :r ORDER BY at, id", r=run_id)]
    assert events == [
        "started", "step_entered", "step_completed", "step_entered",
        "task_claimed", "task_released", "step_completed", "step_entered",
        "step_completed", "completed",
    ]

    # Doppeltes Abschließen liefert TASK_DONE
    with pytest.raises(PipelineError) as exc_done:
        await do_complete_task(sm, t3_id, {"id": "ordered", "label": "Bestellt", "outcome": "ordered"}, {}, {}, ANNA)
    assert exc_done.value.error.code == "TASK_DONE"


async def test_order_process_rejection(engine):
    eng, sm = engine
    ex = order_process_ops()
    await run_ops(*ex["ops"])
    await add_member(eng, CHEF1.id, ex["tl"])

    run_id = zid("run")
    t1 = (await run_ops({"op": "run.start", "id": run_id, "workflow": ex["wf"]}, actor=BEN)).results["0"]["task_id"]
    t2 = (await do_complete_task(sm, t1, {"id": "submit", "label": "Eingereicht", "outcome": "submitted"},
                                 {"kostenstelle": "9999"}, {}, BEN))["task_id"]
    out = await do_complete_task(
        sm, t2, {"id": "reject", "label": "Abgelehnt", "outcome": "rejected"},
        {"kommentar": "Zu teuer"}, {}, CHEF1,
    )
    assert out == {"status": "completed", "current_step": None, "result": {"outcome": "rejected", "label": "Abgelehnt"}}


async def test_starters_and_unpublished_workflow(engine):
    eng, _ = engine
    wf, doc = zid("wf"), zid("doc")
    definition = {
        "start": "s1",
        "starters": [{"kind": "role", "role": "einkauf"}],
        "managers": [{"kind": "role", "role": "einkauf"}],
        "steps": [{"key": "s1", "name": "S1", "document": doc, "assignees": [{"kind": "starter"}]}],
        "transitions": [{"from": "s1", "on": "done", "to": "end"}],
    }
    await run_ops(
        {"op": "workflow.create", "id": wf, "key": zkey("st"), "name": "Starters", "definition": definition},
        {"op": "doc.create", "id": doc, "title": "S1", "owner": {"workflow": wf, "step": "s1"},
         "blocks": [{"id": zid("blk"), "type": "form", "props": {
             "actions": [], "buttons": [{"id": "ok", "label": "OK", "outcome": "done"}]}, "children": []}]},
    )

    # Unveröffentlicht -> VALIDATION
    with pytest.raises(PipelineError) as exc_unpub:
        await run_ops({"op": "run.start", "id": zid("run"), "workflow": wf}, actor=ANNA)
    assert exc_unpub.value.error.code == "VALIDATION"

    await run_ops({"op": "workflow.publish", "workflow": wf})
    # Ben hat nicht Rolle einkauf -> FORBIDDEN
    with pytest.raises(PipelineError) as exc_forb:
        await run_ops({"op": "run.start", "id": zid("run"), "workflow": wf}, actor=BEN)
    assert exc_forb.value.error.code == "FORBIDDEN"

    # Anna darf starten
    res = await run_ops({"op": "run.start", "id": zid("run"), "workflow": wf}, actor=ANNA)
    assert res.results["0"]["status"] == "active"


async def test_exclude_steps(engine):
    eng, sm = engine
    wf, d1, d2 = zid("wf"), zid("doc"), zid("doc")
    definition = {
        "start": "a",
        "managers": [{"kind": "user", "user": ANNA.id}],
        "steps": [
            {"key": "a", "name": "A", "document": d1, "assignees": [{"kind": "user", "user": BEN.id}]},
            {"key": "b", "name": "B", "document": d2,
             "assignees": [{"kind": "user", "user": BEN.id}, {"kind": "user", "user": CHEF1.id}],
             "exclude_steps": ["a"]},
        ],
        "transitions": [{"from": "a", "on": "go", "to": "b"}, {"from": "b", "on": "end", "to": "end"}],
    }
    await run_ops(
        {"op": "workflow.create", "id": wf, "key": zkey("exs"), "name": "ExcludeSteps", "definition": definition},
        {"op": "doc.create", "id": d1, "title": "A", "owner": {"workflow": wf, "step": "a"},
         "blocks": [{"id": zid("blk"), "type": "form", "props": {
             "actions": [], "buttons": [{"id": "go", "label": "Go", "outcome": "go"}]}, "children": []}]},
        {"op": "doc.create", "id": d2, "title": "B", "owner": {"workflow": wf, "step": "b"},
         "blocks": [{"id": zid("blk"), "type": "form", "props": {
             "actions": [], "buttons": [{"id": "end", "label": "End", "outcome": "end"}]}, "children": []}]},
        {"op": "workflow.publish", "workflow": wf},
    )
    run_id = zid("run")
    t1 = (await run_ops({"op": "run.start", "id": run_id, "workflow": wf}, actor=ANNA)).results["0"]["task_id"]
    t2 = (await do_complete_task(sm, t1, {"id": "go", "label": "Go", "outcome": "go"}, {}, {}, BEN))["task_id"]
    row = (await q(eng, "SELECT candidate_users, excluded FROM tasks WHERE id = :id", id=t2))[0]
    assert BEN.id in row["excluded"]
    assert row["candidate_users"] == [CHEF1.id]

    with pytest.raises(PipelineError) as exc:
        await do_complete_task(sm, t2, {"id": "end", "label": "End", "outcome": "end"}, {}, {}, BEN)
    assert exc.value.error.code == "FORBIDDEN"


async def test_expr_assignee_lookup_and_unassigned_fallback(engine):
    eng, sm = engine
    tbl, c_num, c_ver = zid("tbl"), zid("col"), zid("col")
    tbl_key = zkey("ks")
    wf, d1, d2 = zid("wf"), zid("doc"), zid("doc")
    definition = {
        "start": "s1",
        "managers": [{"kind": "user", "user": ANNA.id}],
        "steps": [
            {"key": "s1", "name": "S1", "document": d1, "assignees": [{"kind": "starter"}]},
            {"key": "s2", "name": "S2", "document": d2, "assignees": [
                {"kind": "expr", "expr": f"{{{{lookup(\"{tbl_key}\", \"nummer\", run.steps.s1.values.ks, \"verantwortlich\")}}}}"}
            ]},
        ],
        "transitions": [{"from": "s1", "on": "ok", "to": "s2"}, {"from": "s2", "on": "done", "to": "end"}],
    }
    await run_ops(
        {"op": "table.create", "id": tbl, "key": tbl_key, "name": "Kostenstellen", "columns": [
            {"id": c_num, "key": "nummer", "name": "Nummer", "type": {"kind": "text"}},
            {"id": c_ver, "key": "verantwortlich", "name": "Verantwortlich", "type": {"kind": "user"}},
        ]},
        {"op": "row.insert", "table": tbl, "rows": [
            {"id": zid("row"), "values": {"nummer": "4711", "verantwortlich": CHEF1.id}},
        ]},
        {"op": "workflow.create", "id": wf, "key": zkey("expr"), "name": "ExprWF", "definition": definition},
        {"op": "doc.create", "id": d1, "title": "S1", "owner": {"workflow": wf, "step": "s1"},
         "blocks": [{"id": zid("blk"), "type": "form", "props": {
             "actions": [], "buttons": [{"id": "ok", "label": "OK", "outcome": "ok"}]},
             "children": [{"id": zid("blk"), "type": "field", "props": {"key": "ks", "label": "KS", "input": "text"}}]}]},
        {"op": "doc.create", "id": d2, "title": "S2", "owner": {"workflow": wf, "step": "s2"},
         "blocks": [{"id": zid("blk"), "type": "form", "props": {
             "actions": [], "buttons": [{"id": "done", "label": "Done", "outcome": "done"}]}, "children": []}]},
        {"op": "workflow.publish", "workflow": wf},
    )

    # Treffer: CHEF1 wird zugewiesen
    r1 = zid("run")
    t1 = (await run_ops({"op": "run.start", "id": r1, "workflow": wf}, actor=BEN)).results["0"]["task_id"]
    t2 = (await do_complete_task(sm, t1, {"id": "ok", "label": "OK", "outcome": "ok"}, {"ks": "4711"}, {}, BEN))["task_id"]
    task_row = (await q(eng, "SELECT candidate_users FROM tasks WHERE id = :id", id=t2))[0]
    assert task_row["candidate_users"] == [CHEF1.id]

    # Kein Treffer -> Fallback auf managers (ANNA) + Event unassigned
    r2 = zid("run")
    t1b = (await run_ops({"op": "run.start", "id": r2, "workflow": wf}, actor=BEN)).results["0"]["task_id"]
    t2b = (await do_complete_task(sm, t1b, {"id": "ok", "label": "OK", "outcome": "ok"}, {"ks": "0000"}, {}, BEN))["task_id"]
    task_row_b = (await q(eng, "SELECT candidate_users FROM tasks WHERE id = :id", id=t2b))[0]
    assert task_row_b["candidate_users"] == [ANNA.id]
    evts = [r["type"] for r in await q(eng, "SELECT type FROM run_events WHERE run_id = :r ORDER BY at, id", r=r2)]
    assert "unassigned" in evts


async def test_wildcard_and_revisit(engine):
    eng, sm = engine
    wf, d1, d2 = zid("wf"), zid("doc"), zid("doc")
    definition = {
        "start": "s1",
        "managers": [{"kind": "user", "user": ANNA.id}],
        "steps": [
            {"key": "s1", "name": "S1", "document": d1, "assignees": [{"kind": "starter"}]},
            {"key": "s2", "name": "S2", "document": d2, "assignees": [{"kind": "user", "user": CHEF1.id}]},
        ],
        "transitions": [
            {"from": "s1", "on": "*", "to": "s2"},
            {"from": "s2", "on": "back", "to": "s1"},
            {"from": "s2", "on": "ok", "to": "end"},
        ],
    }
    await run_ops(
        {"op": "workflow.create", "id": wf, "key": zkey("wild"), "name": "Wild", "definition": definition},
        {"op": "doc.create", "id": d1, "title": "S1", "owner": {"workflow": wf, "step": "s1"},
         "blocks": [{"id": zid("blk"), "type": "form", "props": {
             "actions": [], "buttons": [{"id": "go", "label": "Go", "outcome": "anything"}]}, "children": []}]},
        {"op": "doc.create", "id": d2, "title": "S2", "owner": {"workflow": wf, "step": "s2"},
         "blocks": [{"id": zid("blk"), "type": "form", "props": {
             "actions": [], "buttons": [{"id": "back", "label": "Zurück", "outcome": "back"},
                                        {"id": "ok", "label": "OK", "outcome": "ok"}]}, "children": []}]},
        {"op": "workflow.publish", "workflow": wf},
    )
    run_id = zid("run")
    t1 = (await run_ops({"op": "run.start", "id": run_id, "workflow": wf}, actor=BEN)).results["0"]["task_id"]
    t2 = (await do_complete_task(sm, t1, {"id": "go", "label": "Go", "outcome": "anything"}, {"v": 1}, {}, BEN))["task_id"]
    # Zurück zu s1
    t1_again = (await do_complete_task(sm, t2, {"id": "back", "label": "Zurück", "outcome": "back"}, {}, {}, CHEF1))["task_id"]
    t2_again = (await do_complete_task(sm, t1_again, {"id": "go", "label": "Go", "outcome": "anything"}, {"v": 2}, {}, BEN))["task_id"]
    await do_complete_task(sm, t2_again, {"id": "ok", "label": "OK", "outcome": "ok"}, {}, {}, CHEF1)

    row = (await q(eng, "SELECT steps FROM runs WHERE id = :r", r=run_id))[0]
    assert row["steps"]["s1"]["values"] == {"v": 2}
    evts = [r["type"] for r in await q(eng, "SELECT type FROM run_events WHERE run_id = :r ORDER BY at, id", r=run_id)]
    assert evts.count("step_completed") == 4


async def test_cancel_and_reassign_and_immediate_role_effect(engine):
    eng, sm = engine
    wf, doc = zid("wf"), zid("doc")
    role_id, role_key = zid("rol"), zkey("pruefer")
    definition = {
        "start": "s1",
        "managers": [{"kind": "user", "user": ANNA.id}],
        "starter_can_cancel": False,
        "steps": [
            {"key": "s1", "name": "S1", "document": doc, "assignees": [{"kind": "role", "role": role_key}]},
        ],
        "transitions": [{"from": "s1", "on": "ok", "to": "end"}],
    }
    await run_ops(
        {"op": "role.create", "id": role_id, "key": role_key, "name": "Prüfer"},
        {"op": "workflow.create", "id": wf, "key": zkey("can"), "name": "CancelReassign", "definition": definition},
        {"op": "doc.create", "id": doc, "title": "S1", "owner": {"workflow": wf, "step": "s1"},
         "blocks": [{"id": zid("blk"), "type": "form", "props": {
             "actions": [], "buttons": [{"id": "ok", "label": "OK", "outcome": "ok"}]}, "children": []}]},
        {"op": "workflow.publish", "workflow": wf},
    )

    # Run 1: starter_can_cancel=False -> Ben darf nicht abbrechen, Anna (Manager) schon
    r1 = zid("run")
    t1 = (await run_ops({"op": "run.start", "id": r1, "workflow": wf}, actor=BEN)).results["0"]["task_id"]
    with pytest.raises(PipelineError) as exc_cancel:
        await run_ops({"op": "run.cancel", "run": r1, "reason": "Doch nicht"}, actor=BEN)
    assert exc_cancel.value.error.code == "FORBIDDEN"

    await run_ops({"op": "run.cancel", "run": r1, "reason": "Storniert"}, actor=ANNA)
    assert (await q(eng, "SELECT status FROM runs WHERE id = :r", r=r1))[0]["status"] == "cancelled"
    assert (await q(eng, "SELECT status FROM tasks WHERE id = :t", t=t1))[0]["status"] == "cancelled"

    # Abgebrochenen Run erneut abbrechen -> VALIDATION
    with pytest.raises(PipelineError) as exc_again:
        await run_ops({"op": "run.cancel", "run": r1}, actor=ANNA)
    assert exc_again.value.error.code == "VALIDATION"

    # Run 2: Umverteilen + sofortige Rollenwirkung
    r2 = zid("run")
    await add_member(eng, CHEF1.id, role_id)
    t2 = (await run_ops({"op": "run.start", "id": r2, "workflow": wf}, actor=BEN)).results["0"]["task_id"]

    # CHEF2 bekommt Rolle nachträglich -> sieht und bearbeitet sofort
    await run_ops({"op": "user.set_roles", "user": CHEF2.id, "add": [role_id]})
    await run_ops({"op": "task.claim", "task": t2}, actor=CHEF2)

    # Nicht-Manager darf nicht umverteilen
    with pytest.raises(PipelineError) as exc_reas:
        await run_ops({"op": "task.reassign", "task": t2, "assignees": [{"kind": "user", "user": BEN.id}]}, actor=CHEF2)
    assert exc_reas.value.error.code == "FORBIDDEN"

    # Manager (ANNA) verteilt an BEN um -> Claim wird aufgehoben, Event reassigned, BEN kann abschließen
    await run_ops({"op": "task.reassign", "task": t2, "assignees": [{"kind": "user", "user": BEN.id}]}, actor=ANNA)
    t2_row = (await q(eng, "SELECT candidate_users, candidate_roles, claimed_by FROM tasks WHERE id = :t", t=t2))[0]
    assert t2_row["candidate_users"] == [BEN.id] and t2_row["candidate_roles"] == [] and t2_row["claimed_by"] is None
    out = await do_complete_task(sm, t2, {"id": "ok", "label": "OK", "outcome": "ok"}, {}, {}, BEN)
    assert out["status"] == "completed"


async def test_agent_on_behalf_of_starter_name_in_run_title(engine):
    eng, _ = engine
    ex = order_process_ops()
    await run_ops(*ex["ops"])
    ben_agent = Actor(type="agent", id="agt_zz42ben", on_behalf_of=BEN.id, name="Bens Assistent")
    async with eng.begin() as c:
        await c.execute(
            text("INSERT INTO agents (id, workspace_id, name, active) VALUES (:id, 'ws_demo', :name, true) "
                 "ON CONFLICT (id) DO NOTHING"),
            {"id": ben_agent.id, "name": ben_agent.name},
        )
    run_id = zid("run")
    await run_ops({"op": "run.start", "id": run_id, "workflow": ex["wf_key"]}, actor=ben_agent)
    row = (await q(eng, "SELECT title, started_by_id FROM runs WHERE id = :r", r=run_id))[0]
    assert row["started_by_id"] == BEN.id
    assert "Ben Mitarbeiter" in row["title"]
    assert "Bens Assistent" not in row["title"]
