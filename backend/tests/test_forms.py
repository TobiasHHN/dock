"""Formulare im Backend (Task 3.3): Sichtbarkeit, Entwürfe, Absenden, Doppelabsendung, Atomarität.

Läuft gegen Postgres (Standard: Host-Port 5433, überschreibbar mit TEST_DATABASE_URL), durch die echte Op-Pipeline.
Testdaten tragen den Marker `zz33` und werden nach jedem Test entfernt.
"""
import importlib
import json
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain import forms as F
from app.ops import pipeline
from app.ops.errors import PipelineError
from app.ops.handlers import HANDLERS, load_handlers
from app.schemas.common import Actor
from app.schemas.ops import OpBatch

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock")
ANNA = Actor(type="user", id="usr_zz33anna", name="Anna")
BEN = Actor(type="user", id="usr_zz33ben", name="Ben")


def zid(prefix: str) -> str:
    return f"{prefix}_zz33{uuid.uuid4().hex[:10]}"


def batch(*ops) -> OpBatch:
    return OpBatch.model_validate({"batch_id": zid("b"), "ops": list(ops)})


@pytest_asyncio.fixture
async def engine(monkeypatch):
    eng = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with eng.connect() as c:
            await c.execute(text("SELECT 1 FROM form_drafts LIMIT 1"))
    except Exception:
        pytest.skip("Postgres nicht erreichbar")
    monkeypatch.setattr(pipeline, "SessionLocal", async_sessionmaker(eng, expire_on_commit=False))
    load_handlers()
    for name, module in (("row.insert", "tables"), ("doc.create", "documents"), ("draft.set", "forms")):
        if name not in HANDLERS:  # ein anderer Test hat die Registry geleert
            importlib.reload(importlib.import_module(f"app.ops.handlers.{module}"))

    async def fake_enqueue(kind, id_):
        pass

    monkeypatch.setattr(pipeline, "enqueue_reembed", fake_enqueue)
    async with eng.begin() as c:
        for member, role in ((ANNA.id, "einkauf"), (BEN.id, "mitarbeiter")):
            await c.execute(text("""INSERT INTO roles (id, workspace_id, key, name) VALUES (:i, 'ws_demo', :k, :k)
                                    ON CONFLICT (workspace_id, key) DO NOTHING"""), {"i": f"rol_zz33{role}", "k": role})
            await c.execute(text("""INSERT INTO member_roles (workspace_id, member_id, role_id)
                                    SELECT 'ws_demo', :m, id FROM roles WHERE workspace_id = 'ws_demo' AND key = :k
                                    ON CONFLICT DO NOTHING"""), {"m": member, "k": role})
    yield eng
    async with eng.begin() as c:
        for stmt in (
            "DELETE FROM oplog WHERE batch_id LIKE '%zz33%'",
            "DELETE FROM batches WHERE batch_id LIKE '%zz33%'",
            "DELETE FROM channels WHERE id LIKE '%zz33%'",
            "DELETE FROM form_drafts WHERE form_block LIKE '%zz33%'",
            "DELETE FROM form_submissions WHERE form_block LIKE '%zz33%'",
            'DELETE FROM "references" WHERE source_id LIKE \'%zz33%\' OR target_id LIKE \'%zz33%\'',
            "DELETE FROM documents WHERE id LIKE '%zz33%'",
            "DELETE FROM rows WHERE id LIKE '%zz33%' OR table_id LIKE '%zz33%'",
            "DELETE FROM tables WHERE id LIKE '%zz33%'",
            "DELETE FROM member_roles WHERE member_id LIKE '%zz33%'",
            "DELETE FROM roles WHERE id LIKE '%zz33%'",
        ):
            await c.execute(text(stmt))
    await eng.dispose()


async def run(*ops, actor=BEN):
    return await pipeline.apply_batch(batch(*ops), actor)


async def q(engine, sql, **params):
    async with engine.connect() as c:
        return (await c.execute(text(sql), params)).mappings().all()


def j(value):
    return json.loads(value) if isinstance(value, str) else value


async def err(*ops, actor=BEN) -> PipelineError:
    with pytest.raises(PipelineError) as e:
        await run(*ops, actor=actor)
    return e.value


class World:
    """Tabellen `bestellung` und `artikel` (je mit Marker im Key) und ein Dokument mit Formular."""


async def make_world(engine, *, buttons=..., extra_actions=(), form_props=None, owner=None):
    w = World()
    w.best, w.art = zid("tbl"), zid("tbl")
    w.bkey, w.akey = f"best{uuid.uuid4().hex[:8]}", f"art{uuid.uuid4().hex[:8]}"
    cols_b = [{"id": zid("col"), "key": "name", "name": "Name", "type": {"kind": "text"}, "required": True},
              {"id": zid("col"), "key": "kostenstelle", "name": "Kostenstelle", "type": {"kind": "text"}},
              {"id": zid("col"), "key": "summe", "name": "Summe", "type": {"kind": "currency", "currency": "EUR"}},
              {"id": zid("col"), "key": "status", "name": "Status", "type": {"kind": "text"}, "default": "neu"}]
    cols_a = [{"id": zid("col"), "key": "bestellung", "name": "Bestellung", "type": {"kind": "text"}},
              {"id": zid("col"), "key": "artikelname", "name": "Artikel", "type": {"kind": "text"}},
              {"id": zid("col"), "key": "preis", "name": "Preis", "type": {"kind": "currency", "currency": "EUR"}},
              {"id": zid("col"), "key": "anzahl", "name": "Anzahl", "type": {"kind": "integer", "min": 1},
               "required": True}]
    w.cb = {c["key"]: c["id"] for c in cols_b}
    w.ca = {c["key"]: c["id"] for c in cols_a}
    await pipeline.apply_batch(batch(
        {"op": "table.create", "id": w.best, "key": w.bkey, "name": "Bestellungen", "columns": cols_b},
        {"op": "table.create", "id": w.art, "key": w.akey, "name": "Artikel", "columns": cols_a}), ANNA)
    w.doc, w.form, w.f_name, w.f_ks, w.items = zid("doc"), zid("blk"), zid("blk"), zid("blk"), zid("blk")
    actions = [
        {"key": "order", "type": "create_row", "table": w.bkey,
         "values": {"name": "{{fields.name}}", "kostenstelle": "{{fields.kostenstelle}}",
                    "summe": "{{sum(fields.artikel, \"preis\")}}"}},
        {"key": "items", "type": "create_rows", "table": w.akey, "for_each": "{{fields.artikel}}",
         "values": {"bestellung": "{{results.order.id}}", "artikelname": "{{item.artikelname}}",
                    "preis": "{{item.preis}}", "anzahl": "{{item.anzahl}}"}},
        *extra_actions]
    props = {"actions": actions, **(form_props or {})}
    if buttons is not ...:
        props["buttons"] = buttons
    else:
        props["buttons"] = [{"id": "submit", "label": "Absenden", "style": "primary", "actions": ["order", "items"]},
                            {"id": "draft", "label": "Entwurf", "actions": [], "validate": False}]
    form = {"id": w.form, "type": "form", "props": props, "children": [
        {"id": w.f_name, "type": "field", "props": {"key": "name", "label": "Name", "column": f"{w.bkey}.name"}},
        {"id": w.f_ks, "type": "field", "props": {"key": "kostenstelle", "label": "Kostenstelle", "input": "text"}},
        {"id": w.items, "type": "line_items", "props": {
            "key": "artikel", "label": "Artikel", "min_rows": 1, "columns": [
                {"key": "artikelname", "label": "Artikel", "input": "text", "required": True},
                {"key": "preis", "column": f"{w.akey}.preis"}, {"key": "anzahl", "input": "integer"}]}}]}
    doc_op = {"op": "doc.create", "id": w.doc, "title": "ZZ33 Bestellung", "blocks": [form]}
    if owner:
        doc_op["owner"] = owner
    await pipeline.apply_batch(batch(doc_op), ANNA)
    return w


def scope(actor=BEN):
    return {"user": actor.id}


async def fill(w, *, name="Ben", ks="4711", rows=(("Monitor", "249,50", 2), ("Maus", 19, 1)), actor=BEN):
    ops = [{"op": "draft.set", "form_block": w.form, "scope": scope(actor), "key": "name", "value": name},
           {"op": "draft.set", "form_block": w.form, "scope": scope(actor), "key": "kostenstelle", "value": ks}]
    for i, (artikel, preis, anzahl) in enumerate(rows):
        ops.append({"op": "draft.item_insert", "form_block": w.form, "scope": scope(actor), "key": "artikel",
                    "item": {"id": f"li_zz33_{i}", "values": {"artikelname": artikel, "preis": preis, "anzahl": anzahl}}})
    await run(*ops, actor=actor)


def submit(w, button="submit", sid=None, **kw):
    return {"op": "form.submit", "submission_id": sid or zid("sub"), "form_block": w.form, "button": button, **kw}


async def count(engine, table_id):
    return len(await q(engine, "SELECT 1 FROM rows WHERE table_id = :t", t=table_id))


# ── reine Logik ──────────────────────────────────────────────────────────────


def test_effective_buttons_rule():
    assert F.effective_buttons({"actions": [{"key": "a"}]}, 2) == [
        {"id": "save", "label": "Speichern", "style": "primary", "actions": ["a"]}]
    assert F.effective_buttons({"actions": []}, 0) == []  # kein Feld, kein Button
    assert F.effective_buttons({"buttons": [{"id": "ok", "label": "OK"}]}, 0) == [{"id": "ok", "label": "OK"}]
    assert F.effective_buttons({"buttons": []}, 3) == []  # explizit leer bleibt leer


# ── Sichtbarkeit ─────────────────────────────────────────────────────────────


async def test_visible_buttons_explicit_auto_none_and_step_documents(engine):
    w = await make_world(engine)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        shown = await F.visible_buttons(w.form, BEN, session=s)
        assert [b["id"] for b in shown] == ["submit", "draft"]
        assert await F.visible_buttons(w.form, BEN, run="run_x", session=s) == []  # Run-Regeln: Task 4.3
    auto = await make_world(engine, buttons=...)
    await run({"op": "block.update", "block": auto.form, "props": {"buttons": None}}, actor=ANNA)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        assert [(b["id"], b["actions"]) for b in await F.visible_buttons(auto.form, BEN, session=s)] == [
            ("save", ["order", "items"])]
    # Formular ohne Felder und ohne Buttons: kein Speichern-Button
    empty = zid("blk")
    await run({"op": "block.insert", "doc": auto.doc, "block": {"id": empty, "type": "form", "props": {}}}, actor=ANNA)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        assert await F.visible_buttons(empty, BEN, session=s) == []


# ── Entwürfe ─────────────────────────────────────────────────────────────────


async def draft_values(engine, w, actor=BEN):
    rows = await q(engine, 'SELECT "values", version FROM form_drafts WHERE form_block = :b AND scope = :s',
                   b=w.form, s=f"user:{actor.id}")
    return (j(rows[0]["values"]), rows[0]["version"]) if rows else (None, 0)


async def test_draft_ops_set_and_line_items(engine):
    w = await make_world(engine)
    await fill(w, rows=(("A", 1, 1), ("B", 2, 2)))
    values, version = await draft_values(engine, w)
    assert values["name"] == "Ben" and version == 4
    items = values["artikel"]
    assert [i["id"] for i in items] == ["li_zz33_0", "li_zz33_1"] and items[0]["position"] < items[1]["position"]

    await run({"op": "draft.item_insert", "form_block": w.form, "scope": scope(), "key": "artikel",
               "item": {"id": "li_zz33_mid", "values": {"artikelname": "M"}}, "after": "li_zz33_0"},
              {"op": "draft.item_update", "form_block": w.form, "scope": scope(), "key": "artikel",
               "item_id": "li_zz33_1", "values": {"preis": 5, "anzahl": None}},
              {"op": "draft.item_delete", "form_block": w.form, "scope": scope(), "key": "artikel",
               "item_id": "li_zz33_0"},
              {"op": "draft.set", "form_block": w.form, "scope": scope(), "key": "kostenstelle", "value": None})
    values, _ = await draft_values(engine, w)
    assert [i["id"] for i in values["artikel"]] == ["li_zz33_mid", "li_zz33_1"]
    assert values["artikel"][1]["values"] == {"artikelname": "B", "preis": 5} and "kostenstelle" not in values
    assert (await q(engine, "SELECT 1 FROM oplog WHERE channel = :c", c=f"user:{BEN.id}"))  # live im Kanal des Scopes


async def test_draft_rights_and_unknown_targets(engine):
    w = await make_world(engine)
    base = {"form_block": w.form, "key": "name", "value": "x"}
    assert (await err({"op": "draft.set", **base, "scope": {"user": ANNA.id}})).error.code == "FORBIDDEN"
    assert (await err({"op": "draft.set", **base, "scope": {"run": "run_gibtsnicht"}})).error.code == "NOT_FOUND"
    assert (await err({"op": "draft.set", **base, "scope": {"user": BEN.id, "run": "x"}})).error.code == "VALIDATION"
    assert (await err({"op": "draft.set", **{**base, "key": "nix"}, "scope": scope()})).error.code == "VALIDATION"
    assert (await err({"op": "draft.set", **{**base, "key": "artikel"}, "scope": scope()})).error.code == "VALIDATION"
    assert (await err({"op": "draft.set", **{**base, "form_block": w.f_name}, "scope": scope()})).error.code == "VALIDATION"
    e = await err({"op": "draft.item_insert", "form_block": w.form, "scope": scope(), "key": "artikel",
                   "item": {"id": "i", "values": {"nix": 1}}})
    assert e.error.code == "VALIDATION"
    assert (await err({"op": "draft.item_update", "form_block": w.form, "scope": scope(), "key": "artikel",
                       "item_id": "gibtsnicht", "values": {}})).error.code == "NOT_FOUND"
    # Agent im Auftrag von Ben darf Bens Entwurf bearbeiten
    agent = Actor(type="agent", id="agt_zz33", on_behalf_of=BEN.id)
    await run({"op": "draft.set", **base, "scope": scope()}, actor=agent)


# ── Absenden ─────────────────────────────────────────────────────────────────


async def test_submit_writes_order_and_items_together_and_clears_draft(engine):
    w = await make_world(engine)
    await fill(w)
    res = await run(submit(w, sid="sub_zz33_a"))
    out = res.results["0"]
    order_id = out["results"]["order"]["id"]
    assert len(out["results"]["items"]["ids"]) == 2
    [order] = await q(engine, 'SELECT "values" FROM rows WHERE id = :i', i=order_id)
    values = j(order["values"])
    assert values[w.cb["name"]] == "Ben" and values[w.cb["summe"]] == 268.5  # sum() aus den Zeilen, Typ bleibt
    assert values[w.cb["status"]] == "neu"  # Standardwert der Spalte
    items = await q(engine, 'SELECT "values" FROM rows WHERE table_id = :t ORDER BY position', t=w.art)
    assert [j(i["values"])[w.ca["artikelname"]] for i in items] == ["Monitor", "Maus"]
    assert all(j(i["values"])[w.ca["bestellung"]] == order_id for i in items)  # results.order.id im Folgeschritt
    assert j(items[0]["values"])[w.ca["preis"]] == 249.5 and j(items[0]["values"])[w.ca["anzahl"]] == 2
    sub = (await q(engine, "SELECT * FROM form_submissions WHERE id = 'sub_zz33_a'"))[0]
    assert sub["button"] == "submit" and sub["run_id"] is None and j(sub["actor"])["id"] == BEN.id
    assert j(sub["results"]) == out["results"] and j(sub["values"])["name"] == "Ben"
    assert (await draft_values(engine, w))[0] is None  # reset_after_submit: Standard außerhalb von Workflows
    # Kanäle der betroffenen Tabellen sind im Batch dabei
    assert set(res.seq) >= {f"table:{w.best}", f"table:{w.art}", f"user:{BEN.id}"}


async def test_reset_after_submit_false_keeps_draft(engine):
    w = await make_world(engine, form_props={"reset_after_submit": False})
    await fill(w)
    await run(submit(w))
    assert (await draft_values(engine, w))[0]["name"] == "Ben"


async def test_duplicate_submission_returns_first_result_and_runs_nothing_again(engine):
    w = await make_world(engine)
    await fill(w)
    first = (await run(submit(w, sid="sub_zz33_dup"))).results["0"]
    await fill(w, name="Zweiter")  # neuer Entwurf, dieselbe submission_id
    second = (await run(submit(w, sid="sub_zz33_dup"))).results["0"]  # anderer Batch, gleiche submission_id
    assert second["results"] == first["results"] and second["duplicate"] is True
    assert await count(engine, w.best) == 1 and await count(engine, w.art) == 2
    # Dieselbe ID von anderer Person oder für ein anderes Formular wird nicht herausgegeben
    assert (await err(submit(w, sid="sub_zz33_dup"), actor=ANNA)).error.code == "VALIDATION"
    # zweimal im selben Batch (der Entwurf von oben ist noch da, das Duplikat hat ihn nicht geleert)
    res = await run(submit(w, sid="sub_zz33_twice"), submit(w, sid="sub_zz33_twice"))
    assert res.results["1"]["duplicate"] is True and await count(engine, w.best) == 2


async def test_failing_action_rolls_back_everything(engine):
    """Bestellung + Artikel gemeinsam oder gar nicht: Artikel ohne Anzahl scheitert an der Tabellenregel."""
    w = await make_world(engine)
    await fill(w, rows=(("Monitor", 10, 1), ("Maus", 5, None)))
    e = await err(submit(w, sid="sub_zz33_fail"))
    assert e.error.code == "VALIDATION" and "items" in e.error.message
    assert any(k.startswith("actions.items") for k in e.error.details["errors"])
    assert await count(engine, w.best) == 0 and await count(engine, w.art) == 0
    assert not await q(engine, "SELECT 1 FROM form_submissions WHERE id = 'sub_zz33_fail'")
    assert (await draft_values(engine, w))[0]["name"] == "Ben"  # Entwurf bleibt erhalten
    # nach Korrektur klappt dieselbe submission_id
    await run({"op": "draft.item_update", "form_block": w.form, "scope": scope(), "key": "artikel",
               "item_id": "li_zz33_1", "values": {"anzahl": 3}})
    await run(submit(w, sid="sub_zz33_fail"))
    assert await count(engine, w.best) == 1 and await count(engine, w.art) == 2


async def test_field_validation_errors_and_button_options(engine):
    w = await make_world(engine, buttons=[
        {"id": "submit", "label": "Absenden", "actions": ["order", "items"]},
        {"id": "ablehnen", "label": "Ablehnen", "actions": [], "require": ["kostenstelle"]},
        {"id": "ohne", "label": "Ohne Prüfung", "actions": [], "validate": False},
        {"id": "kaputt", "label": "Kaputt", "actions": ["gibtsnicht"]}])
    await fill(w, name="", ks="", rows=(("", "abc", 1),))
    e = await err(submit(w))
    errors = e.error.details["errors"]
    assert errors["name"].endswith("Pflichtfeld und darf nicht leer sein")
    assert "artikel[0].artikelname" in errors and "artikel[0].preis" in errors  # Pflicht und Typ pro Zeile
    assert await count(engine, w.best) == 0
    # Zeilen fehlen komplett: min_rows
    await run({"op": "draft.item_delete", "form_block": w.form, "scope": scope(), "key": "artikel",
               "item_id": "li_zz33_0"})
    assert "mindestens 1" in (await err(submit(w))).error.details["errors"]["artikel"]
    # button.require prüft zusätzlich, validate=false überspringt Pflichtfelder
    assert "kostenstelle" in (await err(submit(w, "ablehnen"))).error.details["errors"]
    await run(submit(w, "ohne"))
    assert (await err(submit(w, "kaputt"))).error.code == "VALIDATION"
    assert (await err(submit(w, "gibtsnicht"))).error.code == "VALIDATION"


async def test_values_override_the_draft_and_unknown_fields_are_rejected(engine):
    w = await make_world(engine)
    await fill(w, name="Entwurf")
    values = {"name": "Agent-Bestellung", "kostenstelle": "4712",
              "artikel": [{"artikelname": "Kabel", "preis": "1,5", "anzahl": "2"}]}  # reine Zeilen, Texte werden Typen
    res = await run(submit(w, values=values))
    [row] = await q(engine, 'SELECT "values" FROM rows WHERE id = :i', i=res.results["0"]["results"]["order"]["id"])
    assert j(row["values"])[w.cb["name"]] == "Agent-Bestellung" and j(row["values"])[w.cb["summe"]] == 1.5
    assert (await draft_values(engine, w))[0] is None  # der Entwurf wird trotzdem geleert
    e = await err(submit(w, values={"name": "x", "nix": 1, "artikel": [{"artikelname": "a", "anzahl": 1}]}))
    assert "nix" in e.error.details["errors"]


async def test_rights_and_context(engine):
    w = await make_world(engine)
    await fill(w)
    assert (await err(submit(w, run="run_x"))).error.code == "VALIDATION"  # Run-Kontext: Task 4.3
    assert (await err({**submit(w), "form_block": w.f_name})).error.code == "VALIDATION"
    assert (await err({**submit(w), "form_block": "blk_gibtsnicht"})).error.code == "NOT_FOUND"
    # Formular ohne Buttons: nichts zu senden
    await run({"op": "block.update", "block": w.form, "props": {"buttons": []}}, actor=ANNA)
    assert (await err(submit(w))).error.code == "FORBIDDEN"
    # Ein Schritt-Dokument eines Workflows ist außerhalb eines Runs nicht absendbar
    await run({"op": "block.update", "block": w.form, "props": {"buttons": None}}, actor=ANNA)
    await engine_exec(engine, "UPDATE documents SET owner_workflow = 'wf_zz33', owner_step = 'erfassen' WHERE id = :d",
                      d=w.doc)
    assert (await err(submit(w))).error.code == "FORBIDDEN"


async def engine_exec(engine, sql, **params):
    async with engine.begin() as c:
        await c.execute(text(sql), params)


async def test_update_and_delete_actions(engine):
    w = await make_world(engine)
    old = zid("row")
    await run({"op": "row.insert", "table": w.best, "rows": [{"id": old, "values": {"name": "Alt", "status": "offen"}}]},
              actor=ANNA)
    await run({"op": "block.update", "block": w.form, "props": {"actions": [
        {"key": "order", "type": "create_row", "table": w.bkey, "values": {"name": "{{fields.name}}"}},
        {"key": "items", "type": "create_rows", "table": w.akey, "for_each": "{{fields.artikel}}",
         "values": {"artikelname": "{{item.artikelname}}", "anzahl": "{{item.anzahl}}"}},
        {"key": "upd", "type": "update_row", "table": w.bkey, "row": old,
         "values": {"status": "{{concat(\"geprüft von \", user.name)}}", "kostenstelle": "{{fields.kostenstelle}}"}},
        {"key": "del", "type": "delete_row", "table": w.bkey, "row": "{{results.order.id}}"}],
        "buttons": [{"id": "go", "label": "Los", "actions": ["order", "items", "upd"]},
                    {"id": "weg", "label": "Weg", "actions": ["order", "items", "del"]}]}}, actor=ANNA)
    await fill(w)
    await run(submit(w, "go"))
    [row] = await q(engine, 'SELECT "values" FROM rows WHERE id = :i', i=old)
    assert j(row["values"])[w.cb["kostenstelle"]] == "4711" and j(row["values"])[w.cb["status"]] == "geprüft von Ben"
    assert await count(engine, w.best) == 2
    await fill(w)
    res = await run(submit(w, "weg"))  # legt an und löscht die eben angelegte Bestellung wieder
    assert await count(engine, w.best) == 2 and res.results["0"]["results"]["del"]["id"] == res.results["0"]["results"]["order"]["id"]


async def test_lookup_expression_reads_tables(engine):
    w = await make_world(engine)
    ks_table = f"ks{uuid.uuid4().hex[:8]}"
    t_id = zid("tbl")
    cn, cv = zid("col"), zid("col")
    await run({"op": "table.create", "id": t_id, "key": ks_table, "name": "KS", "columns": [
        {"id": cn, "key": "nummer", "name": "Nr", "type": {"kind": "text"}},
        {"id": cv, "key": "verantwortlich", "name": "V", "type": {"kind": "text"}}]}, actor=ANNA)
    await run({"op": "row.insert", "table": t_id, "rows": [{"id": zid("row"), "values": {"nummer": "4711", "verantwortlich": "usr_chef"}}]},
              actor=ANNA)
    await run({"op": "block.update", "block": w.form, "props": {"actions": [
        {"key": "order", "type": "create_row", "table": w.bkey, "values": {
            "name": f"{{{{lookup(\"{ks_table}\", \"nummer\", fields.kostenstelle, \"verantwortlich\")}}}}"}}],
        "buttons": [{"id": "go", "label": "Go", "actions": ["order"]}]}}, actor=ANNA)
    await fill(w)
    res = await run(submit(w, "go"))
    [row] = await q(engine, 'SELECT "values" FROM rows WHERE id = :i', i=res.results["0"]["results"]["order"]["id"])
    assert j(row["values"])[w.cb["name"]] == "usr_chef"
    await engine_exec(engine, "DELETE FROM tables WHERE id = :t", t=t_id)


async def test_expression_errors_become_validation_errors(engine):
    w = await make_world(engine)
    await run({"op": "block.update", "block": w.form, "props": {"actions": [
        {"key": "order", "type": "create_row", "table": w.bkey, "values": {"name": "{{fields.tippfehler}}"}}],
        "buttons": [{"id": "go", "label": "Go", "actions": ["order"]}]}}, actor=ANNA)
    await fill(w)
    e = await err(submit(w, "go"))
    assert e.error.code == "VALIDATION" and "tippfehler" in e.error.message
    assert await count(engine, w.best) == 0


async def test_user_snapshot_carries_own_drafts(engine):
    """Der Snapshot von `user:<id>` enthält die Entwürfe mit `scope = "user:<id>"` (Frontend 3.4 liest sie dort)."""
    from app.realtime import snapshots

    w = await make_world(engine)
    await fill(w, rows=(("A", 1, 1),))
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        mine = (await snapshots._user(s, BEN.id, None))["drafts"]
        other = (await snapshots._user(s, ANNA.id, None))["drafts"]
    assert [(d["form_block"], d["scope"]) for d in mine] == [(w.form, f"user:{BEN.id}")]
    assert mine[0]["values"]["name"] == "Ben" and mine[0]["values"]["artikel"][0]["id"] == "li_zz33_0"
    assert other == []
