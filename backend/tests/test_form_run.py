"""Verbindung Formular ↔ Run (Task 4.3, L 4.3, L 4.4, L 4.6, L 5.3).

End-to-End Bestellprozess über echte `form.submit`- und `draft.*`-Ops, Vier-Augen-Prinzip, Schreibschutz
abgeschlossener Schritte, eingefrorene Schritt-Dokumente und `GET /api/documents/{doc}?run=`.
Testdaten tragen den Marker `zz43` und werden nach jedem Test entfernt.
"""
from __future__ import annotations

import json
import os
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import CurrentUser, current_user
from app.db.session import get_session
from app.domain import forms as F
from app.main import app
from app.ops import pipeline
from app.ops.errors import PipelineError
from app.schemas.common import Actor
from app.schemas.ops import OpBatch

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock")

ANNA = Actor(type="user", id="usr_zz43anna", name="Anna Einkauf")
BEN = Actor(type="user", id="usr_zz43ben", name="Ben Mitarbeiter")
CHEF1 = Actor(type="user", id="usr_zz43chef1", name="Chef Eins")
CHEF2 = Actor(type="user", id="usr_zz43chef2", name="Chef Zwei")
CHEF_AGENT = Actor(type="agent", id="agt_zz43ass", on_behalf_of="usr_zz43chef1", name="Chef-Assistent")


def zid(prefix: str) -> str:
    return f"{prefix}_zz43{uuid.uuid4().hex[:10]}"


def zkey(name: str) -> str:
    return f"zz43{name}{uuid.uuid4().hex[:6]}"


def j(value):
    return json.loads(value) if isinstance(value, str) else value


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
                {"id": actor.id, "name": actor.name, "email": f"{actor.id}@zz43.local"},
            )
            await c.execute(
                text("""INSERT INTO roles (id, workspace_id, key, name) VALUES (:i, 'ws_demo', :k, :k)
                        ON CONFLICT (workspace_id, key) DO NOTHING"""),
                {"i": f"rol_zz43{role}", "k": role},
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
                {"id": u.id, "name": u.name, "email": f"{u.id}@zz43.local"},
            )
        await c.execute(
            text("""INSERT INTO agents (id, workspace_id, name, active) VALUES (:id, 'ws_demo', :name, true)
                    ON CONFLICT (id) DO NOTHING"""),
            {"id": CHEF_AGENT.id, "name": CHEF_AGENT.name},
        )
    yield eng, sm

    async with eng.begin() as c:
        for stmt in (
            "DELETE FROM oplog WHERE batch_id LIKE '%zz43%'",
            "DELETE FROM batches WHERE batch_id LIKE '%zz43%'",
            "DELETE FROM channels WHERE id LIKE '%zz43%'",
            "DELETE FROM form_drafts WHERE form_block LIKE '%zz43%' OR scope LIKE '%zz43%'",
            "DELETE FROM form_submissions WHERE id LIKE '%zz43%' OR form_block LIKE '%zz43%'",
            'DELETE FROM "references" WHERE source_id LIKE \'%zz43%\' OR target_id LIKE \'%zz43%\'',
            "DELETE FROM notifications WHERE run_id LIKE '%zz43%' OR recipient_id LIKE '%zz43%'",
            "DELETE FROM run_events WHERE run_id LIKE '%zz43%'",
            "DELETE FROM tasks WHERE run_id LIKE '%zz43%'",
            "DELETE FROM runs WHERE id LIKE '%zz43%' OR workflow_id LIKE '%zz43%'",
            "DELETE FROM workflows WHERE id LIKE '%zz43%'",
            "DELETE FROM documents WHERE id LIKE '%zz43%'",
            "DELETE FROM row_links WHERE from_row IN (SELECT id FROM rows WHERE table_id LIKE '%zz43%') OR to_row IN (SELECT id FROM rows WHERE table_id LIKE '%zz43%')",
            "DELETE FROM rows WHERE id LIKE '%zz43%' OR table_id LIKE '%zz43%'",
            "DELETE FROM tables WHERE id LIKE '%zz43%'",
            "DELETE FROM member_roles WHERE member_id LIKE '%zz43%' OR role_id LIKE '%zz43%'",
            "DELETE FROM roles WHERE id LIKE '%zz43%'",
            "DELETE FROM agents WHERE id LIKE '%zz43%'",
            "DELETE FROM users WHERE id LIKE '%zz43%'",
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


def build_order_process():
    """Kompletter Bestellprozess (L 10.1) mit echten Tabellen und Actions."""
    wf, wf_key = zid("wf"), zkey("bestell")
    tl, tl_key = zid("rol"), zkey("tl")
    best, art = zid("tbl"), zid("tbl")
    bkey, akey = zkey("best"), zkey("art")
    s1, s2, s3 = zid("doc"), zid("doc"), zid("doc")
    f1, f2, f3 = zid("blk"), zid("blk"), zid("blk")
    cb = {k: zid("col") for k in ("name", "ks", "status", "gen", "komm", "lnr", "lt", "run")}
    ca = {k: zid("col") for k in ("name", "preis", "nr", "anz", "best")}

    order_ref = "{{run.steps.erfassen.results.order.id}}"
    select = {"kind": "select", "options": [
        {"id": o, "label": o.capitalize()} for o in ("eingereicht", "genehmigt", "abgelehnt", "bestellt")
    ]}

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
        {"op": "table.create", "id": best, "key": bkey, "name": "Bestellungen", "columns": [
            {"id": cb["name"], "key": "name", "name": "Name", "type": {"kind": "text"}, "required": True},
            {"id": cb["ks"], "key": "kostenstelle", "name": "Kostenstelle", "type": {"kind": "text"}, "required": True},
            {"id": cb["status"], "key": "status", "name": "Status", "type": select, "default": "eingereicht"},
            {"id": cb["gen"], "key": "genehmigt_von", "name": "Genehmigt von", "type": {"kind": "user"}},
            {"id": cb["komm"], "key": "kommentar", "name": "Kommentar", "type": {"kind": "long_text"}},
            {"id": cb["lnr"], "key": "lieferanten_nr", "name": "Bestellnr. Lieferant", "type": {"kind": "text"}},
            {"id": cb["lt"], "key": "liefertermin", "name": "Liefertermin", "type": {"kind": "date"}},
            {"id": cb["run"], "key": "run", "name": "Vorgang", "type": {"kind": "text"}},
        ]},
        {"op": "table.create", "id": art, "key": akey, "name": "Artikel", "columns": [
            {"id": ca["name"], "key": "artikelname", "name": "Artikelname", "type": {"kind": "text"}, "required": True},
            {"id": ca["preis"], "key": "preis", "name": "Preis", "type": {"kind": "currency", "currency": "EUR"}, "required": True},
            {"id": ca["nr"], "key": "artikelnummer", "name": "Artikelnummer", "type": {"kind": "text"}},
            {"id": ca["anz"], "key": "anzahl", "name": "Anzahl", "type": {"kind": "integer", "min": 1}, "required": True},
            {"id": ca["best"], "key": "bestellung", "name": "Bestellung",
             "type": {"kind": "reference", "table": best, "on_delete": "cascade"}, "required": True},
        ]},
        {"op": "workflow.create", "id": wf, "key": wf_key, "name": "Bestellprozess", "definition": definition},
        {"op": "doc.create", "id": s1, "title": "Bestellung erfassen", "owner": {"workflow": wf, "step": "erfassen"},
         "blocks": [
             {"id": zid("blk"), "type": "heading", "props": {"level": 1, "content": [{"t": "text", "text": "Bestellung erfassen"}]}},
             {"id": f1, "type": "form", "props": {
                 "actions": [
                     {"key": "order", "type": "create_row", "table": best, "values": {
                         cb["name"]: "{{fields.name}}", cb["ks"]: "{{fields.kostenstelle}}",
                         cb["status"]: "eingereicht", cb["run"]: "{{run.id}}"}},
                     {"key": "items", "type": "create_rows", "table": art, "for_each": "{{fields.artikel}}", "values": {
                         ca["name"]: "{{item.artikelname}}", ca["preis"]: "{{item.preis}}",
                         ca["nr"]: "{{item.artikelnummer}}", ca["anz"]: "{{item.anzahl}}",
                         ca["best"]: "{{results.order.id}}"}},
                 ],
                 "buttons": [{"id": "submit", "label": "Eingereicht", "style": "primary",
                              "actions": ["order", "items"], "outcome": "submitted"}],
             }, "children": [
                 {"id": zid("blk"), "type": "field", "props": {"key": "name", "label": "Name", "column": cb["name"], "default": "{{user.name}}"}},
                 {"id": zid("blk"), "type": "field", "props": {"key": "kostenstelle", "label": "Kostenstelle", "column": cb["ks"]}},
                 {"id": zid("blk"), "type": "line_items", "props": {"key": "artikel", "label": "Artikel", "min_rows": 1, "columns": [
                     {"key": "artikelname", "column": ca["name"]},
                     {"key": "preis", "column": ca["preis"]},
                     {"key": "artikelnummer", "column": ca["nr"]},
                     {"key": "anzahl", "column": ca["anz"]},
                 ]}},
             ]},
         ]},
        {"op": "doc.create", "id": s2, "title": "Genehmigung", "owner": {"workflow": wf, "step": "genehmigung"},
         "blocks": [
             {"id": zid("blk"), "type": "paragraph", "props": {"content": [
                 {"t": "text", "text": "Bestellung von "},
                 {"t": "value", "expr": "{{run.steps.erfassen.values.name}}"},
                 {"t": "text", "text": " für Kostenstelle "},
                 {"t": "value", "expr": "{{run.steps.erfassen.values.kostenstelle}}"},
                 {"t": "text", "text": ", Summe: "},
                 {"t": "value", "expr": "{{sum(run.steps.erfassen.values.artikel, \"preis\")}}"},
             ]}},
             {"id": zid("blk"), "type": "table_view", "props": {
                 "table": art, "columns": [ca["name"], ca["nr"], ca["anz"], ca["preis"]],
                 "filter": [{"column": ca["best"], "op": "eq", "value": order_ref}], "editable": False}},
             {"id": f2, "type": "form", "props": {
                 "actions": [
                     {"key": "approve", "type": "update_row", "table": best, "row": order_ref,
                      "values": {cb["status"]: "genehmigt", cb["gen"]: "{{user.id}}", cb["komm"]: "{{fields.kommentar}}"}},
                     {"key": "reject", "type": "update_row", "table": best, "row": order_ref,
                      "values": {cb["status"]: "abgelehnt", cb["komm"]: "{{fields.kommentar}}"}},
                 ],
                 "buttons": [
                     {"id": "approve", "label": "Genehmigt", "style": "primary", "actions": ["approve"], "outcome": "approved"},
                     {"id": "reject", "label": "Abgelehnt", "style": "danger", "actions": ["reject"],
                      "outcome": "rejected", "require": ["kommentar"]},
                 ],
             }, "children": [
                 {"id": zid("blk"), "type": "field", "props": {"key": "kommentar", "label": "Kommentar", "input": "textarea"}},
             ]},
         ]},
        {"op": "doc.create", "id": s3, "title": "Bestellung auslösen", "owner": {"workflow": wf, "step": "bestellung"},
         "blocks": [
             {"id": zid("blk"), "type": "paragraph", "props": {"content": [
                 {"t": "text", "text": "Genehmigt von "},
                 {"t": "value", "expr": "{{run.steps.genehmigung.completed_by.name}}"},
                 {"t": "text", "text": "."},
             ]}},
             {"id": f3, "type": "form", "props": {
                 "actions": [
                     {"key": "ordered", "type": "update_row", "table": best, "row": order_ref,
                      "values": {cb["status"]: "bestellt", cb["lnr"]: "{{fields.lieferanten_nr}}",
                                 cb["lt"]: "{{fields.liefertermin}}"}},
                 ],
                 "buttons": [{"id": "ordered", "label": "Bestellt", "style": "primary",
                              "actions": ["ordered"], "outcome": "ordered"}],
             }, "children": [
                 {"id": zid("blk"), "type": "field", "props": {"key": "lieferanten_nr", "label": "Bestellnummer",
                                                               "column": cb["lnr"], "required": True}},
                 {"id": zid("blk"), "type": "field", "props": {"key": "liefertermin", "label": "Liefertermin",
                                                               "column": cb["lt"]}},
             ]},
         ]},
        {"op": "workflow.publish", "workflow": wf},
    ]
    return {
        "wf": wf, "wf_key": wf_key, "tl": tl, "tl_key": tl_key,
        "best": best, "art": art, "cb": cb, "ca": ca,
        "s1": s1, "s2": s2, "s3": s3, "f1": f1, "f2": f2, "f3": f3, "ops": ops,
    }


async def test_order_process_end_to_end_via_form_submit(engine):
    eng, sm = engine
    ex = build_order_process()
    await run_ops(*ex["ops"])
    await add_member(eng, CHEF1.id, ex["tl"])
    await add_member(eng, CHEF2.id, ex["tl"])
    await add_member(eng, BEN.id, ex["tl"])  # Ben hat Rolle TL -> Vier-Augen muss trotzdem greifen

    run_id = zid("run")
    await run_ops({"op": "run.start", "id": run_id, "workflow": ex["wf_key"]}, actor=BEN)

    # visible_buttons im Schritt erfassen
    async with sm() as s:
        assert [b["id"] for b in await F.visible_buttons(ex["f1"], BEN, run=run_id, session=s)] == ["submit"]
        assert await F.visible_buttons(ex["f1"], CHEF1, run=run_id, session=s) == []
        assert await F.visible_buttons(ex["f1"], ANNA, run=run_id, session=s) == []

    # Chef darf Run-Entwurf im Schritt erfassen nicht bearbeiten
    with pytest.raises(PipelineError) as exc_draft:
        await run_ops({"op": "draft.set", "form_block": ex["f1"], "scope": {"run": run_id},
                       "key": "kostenstelle", "value": "9999"}, actor=CHEF1)
    assert exc_draft.value.error.code == "FORBIDDEN"

    # Ben füllt Run-Entwurf aus und sendet ab
    await run_ops(
        {"op": "draft.set", "form_block": ex["f1"], "scope": {"run": run_id}, "key": "kostenstelle", "value": "4711"},
        {"op": "draft.item_insert", "form_block": ex["f1"], "scope": {"run": run_id}, "key": "artikel",
         "item": {"id": "li_zz43_1", "values": {"artikelname": "Dell Monitor", "preis": "299,00", "anzahl": 2}}},
        {"op": "draft.item_insert", "form_block": ex["f1"], "scope": {"run": run_id}, "key": "artikel",
         "item": {"id": "li_zz43_2", "values": {"artikelname": "USB-C Kabel", "preis": "19,50", "anzahl": 1}}},
        actor=BEN,
    )
    sub1_id = zid("sub")
    res1 = await run_ops(
        {"op": "form.submit", "submission_id": sub1_id, "form_block": ex["f1"], "button": "submit", "run": run_id},
        actor=BEN,
    )
    out1 = res1.results["0"]
    assert out1["run"]["status"] == "active" and out1["run"]["current_step"] == "genehmigung"
    order_id = out1["results"]["order"]["id"]
    assert len(out1["results"]["items"]["ids"]) == 2

    # Tabellenzeilen atomar geschrieben
    [order_row] = await q(eng, 'SELECT "values" FROM rows WHERE id = :id', id=order_id)
    ov = j(order_row["values"])
    assert ov[ex["cb"]["name"]] == "Ben Mitarbeiter"  # default {{user.name}}
    assert ov[ex["cb"]["ks"]] == "4711"
    assert ov[ex["cb"]["status"]] == "eingereicht"
    assert ov[ex["cb"]["run"]] == run_id

    # Submission und Titel prüfen
    [sub_row] = await q(eng, "SELECT run_id FROM form_submissions WHERE id = :id", id=sub1_id)
    assert sub_row["run_id"] == run_id
    [run_row] = await q(eng, "SELECT title, current_step FROM runs WHERE id = :r", r=run_id)
    assert run_row["title"] == "Bestellung KS 4711 – Ben Mitarbeiter" and run_row["current_step"] == "genehmigung"

    # Abgeschlossener Schritt erfassen ist schreibgeschützt
    async with sm() as s:
        assert await F.visible_buttons(ex["f1"], BEN, run=run_id, session=s) == []
    with pytest.raises(PipelineError) as exc_ro:
        await run_ops({"op": "draft.set", "form_block": ex["f1"], "scope": {"run": run_id},
                       "key": "kostenstelle", "value": "0000"}, actor=BEN)
    assert exc_ro.value.error.code == "FORBIDDEN"
    with pytest.raises(PipelineError) as exc_ro_sub:
        await run_ops({"op": "form.submit", "submission_id": zid("sub"), "form_block": ex["f1"],
                       "button": "submit", "run": run_id}, actor=BEN)
    assert exc_ro_sub.value.error.code == "FORBIDDEN"

    # Vier-Augen-Prinzip in genehmigung: Ben darf trotz Rolle TL nicht handeln
    async with sm() as s:
        assert await F.visible_buttons(ex["f2"], BEN, run=run_id, session=s) == []
        assert [b["id"] for b in await F.visible_buttons(ex["f2"], CHEF1, run=run_id, session=s)] == ["approve", "reject"]
    with pytest.raises(PipelineError) as exc_4eyes:
        await run_ops({"op": "form.submit", "submission_id": zid("sub"), "form_block": ex["f2"],
                       "button": "approve", "run": run_id}, actor=BEN)
    assert exc_4eyes.value.error.code == "FORBIDDEN"

    # Chef1 übernimmt -> Chef2 ist blockiert (TASK_CLAIMED)
    [t2_row] = await q(eng, "SELECT id FROM tasks WHERE run_id = :r AND step = 'genehmigung' AND status = 'open'", r=run_id)
    await run_ops({"op": "task.claim", "task": t2_row["id"]}, actor=CHEF1)
    async with sm() as s:
        assert await F.visible_buttons(ex["f2"], CHEF2, run=run_id, session=s) == []
    with pytest.raises(PipelineError) as exc_claimed_draft:
        await run_ops({"op": "draft.set", "form_block": ex["f2"], "scope": {"run": run_id},
                       "key": "kommentar", "value": "Test"}, actor=CHEF2)
    assert exc_claimed_draft.value.error.code == "TASK_CLAIMED"
    with pytest.raises(PipelineError) as exc_claimed_sub:
        await run_ops({"op": "form.submit", "submission_id": zid("sub"), "form_block": ex["f2"],
                       "button": "approve", "run": run_id}, actor=CHEF2)
    assert exc_claimed_sub.value.error.code == "TASK_CLAIMED"

    # Chef-Agent (im Auftrag von Chef1) genehmigt
    res2 = await run_ops(
        {"op": "form.submit", "submission_id": zid("sub"), "form_block": ex["f2"], "button": "approve",
         "run": run_id, "values": {"kommentar": "Passt."}},
        actor=CHEF_AGENT,
    )
    assert res2.results["0"]["run"]["current_step"] == "bestellung"
    [order_row] = await q(eng, 'SELECT "values" FROM rows WHERE id = :id', id=order_id)
    assert j(order_row["values"])[ex["cb"]["status"]] == "genehmigt"
    assert j(order_row["values"])[ex["cb"]["gen"]] == CHEF1.id

    # Anna (einkauf) schließt Bestellung ab
    sub3_id = zid("sub")
    res3 = await run_ops(
        {"op": "form.submit", "submission_id": sub3_id, "form_block": ex["f3"], "button": "ordered",
         "run": run_id, "values": {"lieferanten_nr": "L-4711", "liefertermin": "2026-12-03"}},
        actor=ANNA,
    )
    out3 = res3.results["0"]
    assert out3["run"] == {"status": "completed", "current_step": None,
                           "result": {"outcome": "ordered", "label": "Bestellt"}}
    [order_row] = await q(eng, 'SELECT "values" FROM rows WHERE id = :id', id=order_id)
    ov = j(order_row["values"])
    assert ov[ex["cb"]["status"]] == "bestellt" and ov[ex["cb"]["lnr"]] == "L-4711"

    # Doppelabsendung liefert duplicate=True und Run-Status
    dup = await run_ops(
        {"op": "form.submit", "submission_id": sub3_id, "form_block": ex["f3"], "button": "ordered", "run": run_id},
        actor=ANNA,
    )
    assert dup.results["0"]["duplicate"] is True and dup.results["0"]["run"]["status"] == "completed"


async def test_rejection_requires_comment_and_rolls_back(engine):
    eng, _ = engine
    ex = build_order_process()
    await run_ops(*ex["ops"])
    await add_member(eng, CHEF1.id, ex["tl"])

    run_id = zid("run")
    await run_ops({"op": "run.start", "id": run_id, "workflow": ex["wf_key"]}, actor=BEN)
    res1 = await run_ops(
        {"op": "form.submit", "submission_id": zid("sub"), "form_block": ex["f1"], "button": "submit", "run": run_id,
         "values": {"name": "Ben", "kostenstelle": "4711",
                    "artikel": [{"artikelname": "Monitor", "preis": 100, "anzahl": 1}]}},
        actor=BEN,
    )
    order_id = res1.results["0"]["results"]["order"]["id"]

    # Ablehnen ohne Kommentar -> VALIDATION, Run bleibt in genehmigung, Tabelle bleibt eingereicht
    with pytest.raises(PipelineError) as exc_req:
        await run_ops({"op": "form.submit", "submission_id": zid("sub"), "form_block": ex["f2"],
                       "button": "reject", "run": run_id, "values": {}}, actor=CHEF1)
    assert exc_req.value.error.code == "VALIDATION" and "kommentar" in exc_req.value.error.details["errors"]
    [r_row] = await q(eng, "SELECT status, current_step FROM runs WHERE id = :r", r=run_id)
    assert r_row["status"] == "active" and r_row["current_step"] == "genehmigung"
    [o_row] = await q(eng, 'SELECT "values" FROM rows WHERE id = :id', id=order_id)
    assert j(o_row["values"])[ex["cb"]["status"]] == "eingereicht"

    # Mit Kommentar -> abgelehnt und Run completed
    res2 = await run_ops(
        {"op": "form.submit", "submission_id": zid("sub"), "form_block": ex["f2"], "button": "reject",
         "run": run_id, "values": {"kommentar": "Budget erschöpft"}},
        actor=CHEF1,
    )
    assert res2.results["0"]["run"] == {"status": "completed", "current_step": None,
                                        "result": {"outcome": "rejected", "label": "Abgelehnt"}}
    [o_row] = await q(eng, 'SELECT "values" FROM rows WHERE id = :id', id=order_id)
    assert j(o_row["values"])[ex["cb"]["status"]] == "abgelehnt"
    assert j(o_row["values"])[ex["cb"]["komm"]] == "Budget erschöpft"


async def test_frozen_documents_and_rest_run_context(engine):
    eng, sm = engine
    ex = build_order_process()
    await run_ops(*ex["ops"])
    await add_member(eng, CHEF1.id, ex["tl"])

    run_id = zid("run")
    await run_ops({"op": "run.start", "id": run_id, "workflow": ex["wf_key"]}, actor=BEN)

    # Live-Dokument von erfassen wird nachträglich um ein Pflichtfeld erweitert
    await run_ops(
        {"op": "block.insert", "doc": ex["s1"], "parent": ex["f1"],
         "block": {"id": zid("blk"), "type": "field",
                   "props": {"key": "nachtrag", "label": "Nachtrag", "input": "text", "required": True}}},
        actor=ANNA,
    )

    # Run v1 nutzt weiterhin das eingefrorene Formular ohne "nachtrag"
    res1 = await run_ops(
        {"op": "form.submit", "submission_id": zid("sub"), "form_block": ex["f1"], "button": "submit", "run": run_id,
         "values": {"name": "Ben Mitarbeiter", "kostenstelle": "4711",
                    "artikel": [{"artikelname": "Monitor", "preis": 299, "anzahl": 2}]}},
        actor=BEN,
    )
    order_id = res1.results["0"]["results"]["order"]["id"]

    # REST GET /api/documents/{doc}?run= und /markdown?run=
    holder = {"user": CurrentUser(id=BEN.id, name=BEN.name, email="ben@zz43.local", roles=["mitarbeiter"])}

    async def session():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[current_user] = lambda: holder["user"]
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            # Schritt 1: eingefrorener Stand ohne "nachtrag"
            doc1 = await client.get(f"/api/documents/{ex['s1']}", params={"run": run_id})
            assert doc1.status_code == 200
            assert not any(b["props"].get("key") == "nachtrag" for b in doc1.json()["blocks"])

            # Schritt 2: ausgewertete Inline-Werte & table_view-Filter im JSON und Markdown
            doc2 = await client.get(f"/api/documents/{ex['s2']}", params={"run": run_id})
            assert doc2.status_code == 200
            blocks2 = doc2.json()["blocks"]
            para = next(b for b in blocks2 if b["type"] == "paragraph")
            vals = [p.get("value") for p in para["props"]["content"] if p["t"] == "value"]
            assert vals == ["Ben Mitarbeiter", "4711", 299]
            tv = next(b for b in blocks2 if b["type"] == "table_view")
            assert tv["props"]["filter"][0]["value"] == order_id

            md2 = await client.get(f"/api/documents/{ex['s2']}/markdown", params={"run": run_id})
            assert md2.status_code == 200
            assert "Bestellung von Ben Mitarbeiter für Kostenstelle 4711, Summe: 299" in md2.json()["markdown"]

            # Unbekannter Run -> 404
            assert (await client.get(f"/api/documents/{ex['s2']}", params={"run": "run_gibtsnicht"})).status_code == 404

            # Unbeteiligter Nutzer -> 403
            holder["user"] = CurrentUser(id="usr_zz43fremd", name="Fremd", email="f@zz43.local", roles=[])
            assert (await client.get(f"/api/documents/{ex['s2']}", params={"run": run_id})).status_code == 403

            # Nach Genehmigung: Schritt 3 zeigt completed_by.name
            await run_ops(
                {"op": "form.submit", "submission_id": zid("sub"), "form_block": ex["f2"], "button": "approve",
                 "run": run_id, "values": {"kommentar": "OK"}},
                actor=CHEF_AGENT,
            )
            holder["user"] = CurrentUser(id=ANNA.id, name=ANNA.name, email="a@zz43.local", roles=["einkauf"])
            md3 = await client.get(f"/api/documents/{ex['s3']}/markdown", params={"run": run_id})
            assert md3.status_code == 200
            assert "Genehmigt von Chef-Assistent." in md3.json()["markdown"]
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(current_user, None)
