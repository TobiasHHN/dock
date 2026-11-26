"""Dokumente (Task 1.4): Verschachtelung, Markdown-Hin-und-Zurück, doc.*/block.*-Handler gegen Postgres,
lesende Endpunkte. Testdaten tragen den Marker `zz14` und werden nach jedem Test entfernt.
Postgres: Host-Port 5433, überschreibbar mit TEST_DATABASE_URL."""
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
from app.domain import documents as D
from app.domain import markdown as M
from app.domain import queries
from app.main import app
from app.ops import pipeline
from app.ops.errors import PipelineError
from app.realtime import presence
from app.schemas.common import Actor
from app.schemas.ops import OpBatch
from app.schemas.ws import PresenceState

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock")
ANNA = Actor(type="user", id="usr_zz14anna", name="Anna")
BEN = Actor(type="user", id="usr_zz14ben", name="Ben")
AGENT = Actor(type="agent", id="agt_zz14", on_behalf_of=ANNA.id, name="Agent")


def zid(prefix: str) -> str:
    return f"{prefix}_zz14{uuid.uuid4().hex[:10]}"


def batch(*ops, base=None) -> OpBatch:
    return OpBatch.model_validate({"batch_id": zid("b"), "base": base or {}, "ops": list(ops)})


def para(text_="Text", id_=None, **props):
    return {"id": id_ or zid("blk"), "type": "paragraph",
            "props": {"content": [{"t": "text", "text": text_}], **props}}


# ── reine Logik ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("parent,child,ok", [
    (None, "paragraph", True), (None, "form", True), (None, "field", False), (None, "line_items", False),
    (None, "list_item", False), ("form", "field", True), ("form", "form", False), ("form", "list_item", False),
    ("list", "list_item", True), ("list", "paragraph", False), ("list_item", "list", True),
    ("list_item", "paragraph", False), ("quote", "paragraph", True), ("quote", "field", False),
    ("quote", "code", False), ("paragraph", "paragraph", False), ("table_view", "paragraph", False),
])
def test_check_nesting(parent, child, ok):
    if ok:
        D.check_nesting(parent, child)
    else:
        with pytest.raises(ValueError):
            D.check_nesting(parent, child)


def test_field_error_names_form():
    with pytest.raises(ValueError, match="form"):
        D.check_nesting(None, "field")


def test_flat_to_tree_sorts_by_position():
    flat = [
        {"id": "b", "parent_id": None, "position": "a1", "type": "paragraph", "props": {}},
        {"id": "a", "parent_id": None, "position": "a0", "type": "list", "props": {}},
        {"id": "a2", "parent_id": "a", "position": "a1", "type": "list_item", "props": {}},
        {"id": "a1", "parent_id": "a", "position": "a0", "type": "list_item", "props": {}},
    ]
    tree = D.flat_to_tree(flat)
    assert [n["id"] for n in tree] == ["a", "b"]
    assert [c["id"] for c in tree[0]["children"]] == ["a1", "a2"]


def _text(t, *marks):
    return {"t": "text", "text": t, "marks": list(marks)}


def full_tree():
    """Ein Dokument mit allen Blocktypen und kniffligen Texten."""
    return [
        {"id": "h1", "type": "heading", "props": {"level": 2, "content": [_text("Titel *Stern* {#x}")]}},
        {"id": "p1", "type": "paragraph", "props": {"content": [
            _text("Hallo "), _text("fett", "bold"), _text(" und "), _text("kursiv fett", "bold", "italic"),
            _text(" "), _text("code `x`", "code"), _text(" "), _text("durch", "strike"),
            {"t": "link", "text": "Link [1]", "href": "https://x.de/a(b)"},
            {"t": "mention", "target": "doc_abc"},
            {"t": "value", "expr": "{{run.input.x}}"},
            _text("Zeile\\1\nZeile2  ")]}},
        {"id": "p2", "type": "paragraph", "props": {"content": [_text("- kein Listenpunkt")]}},
        {"id": "p3", "type": "paragraph", "props": {"content": []}},
        {"id": "l1", "type": "list", "props": {"ordered": False}, "children": [
            {"id": "li1", "type": "list_item", "props": {"content": [_text("eins")], "checked": True},
             "children": [{"id": "l2", "type": "list", "props": {"ordered": True}, "children": [
                 {"id": "li2", "type": "list_item", "props": {"content": [_text("a")], "checked": None}},
                 {"id": "li3", "type": "list_item", "props": {"content": [_text("b")], "checked": False}}]}]},
            {"id": "li4", "type": "list_item", "props": {"content": [_text("zwei")], "checked": None}}]},
        {"id": "l3", "type": "list", "props": {"ordered": False}, "children": [
            {"id": "li5", "type": "list_item", "props": {"content": [_text("neue Liste")], "checked": None}}]},
        {"id": "q1", "type": "quote", "props": {}, "children": [
            {"id": "qp", "type": "paragraph", "props": {"content": [_text("Zitat")]}}]},
        {"id": "c1", "type": "code", "props": {"language": "python", "text": "print('```')\n\nx = 1\n"}},
        {"id": "d1", "type": "divider", "props": {}},
        {"id": "i1", "type": "image", "props": {"asset_id": "ast_1", "alt": "Ein \"Bild\""}},
        {"id": "tv1", "type": "table_view", "props": {
            "table": "artikel", "columns": ["artikelname", "preis"],
            "filter": [{"column": "preis", "op": "gt", "value": 5}], "sort": [{"column": "preis", "dir": "desc"}],
            "editable": True, "allow_add": False, "allow_delete": False}},
        {"id": "f1", "type": "form", "props": {"actions": [], "buttons": None, "reset_after_submit": None},
         "children": [
             {"id": "fh", "type": "heading", "props": {"level": 1, "content": [_text("Formular")]}},
             {"id": "fn", "type": "field", "props": {
                 "key": "name", "label": "Name", "input": None, "required": True,
                 "column": "bestellungen.name", "default": None, "options": None, "reference_table": None}},
             {"id": "fs", "type": "field", "props": {
                 "key": "art", "label": "Art", "input": "select", "required": False, "column": None,
                 "default": "a", "options": [{"id": "a", "label": "A"}], "reference_table": None}},
             {"id": "fi", "type": "line_items", "props": {
                 "key": "artikel", "label": "Artikel", "min_rows": 1, "columns": [
                     {"key": "artikelname", "label": None, "column": "artikel.artikelname", "input": None,
                      "required": False},
                     {"key": "preis", "label": None, "column": "artikel.preis", "input": None, "required": False}]}},
             {"id": "fw", "type": "workflow", "props": {
                 "workflow": "bestellprozess", "mode": "launcher", "run": None, "input": None, "wait": False}}]},
        {"id": "li_custom", "type": "line_items" if False else "paragraph",
         "props": {"content": [_text("Ende")]}},
    ]


def test_markdown_roundtrip_all_block_types():
    tree = D.normalize_nodes(full_tree())
    D.validate_tree(tree)
    flat = []

    def flatten(nodes, parent):
        for i, n in enumerate(nodes):
            flat.append({"id": n["id"], "parent_id": parent, "position": f"a{i:02d}", "type": n["type"],
                         "props": n["props"]})
            flatten(n["children"], n["id"])

    flatten(tree, None)
    md = M.blocks_to_markdown(flat)
    back = D.normalize_nodes(M.markdown_to_blocks(md))
    assert back == tree, md


def test_markdown_example_from_spec_and_new_ids():
    md = """# Bestellung erfassen {#blk_h1}

Bitte Name angeben. {#blk_p1}

:::form{#blk_form}
::field{#blk_name key=name label="Name" column=bestellungen.name}
::line_items{#blk_items key=artikel label="Artikel" columns="artikelname,preis,anzahl" from=artikel}
:::
"""
    tree = D.normalize_nodes(M.markdown_to_blocks(md))
    assert [n["id"] for n in tree] == ["blk_h1", "blk_p1", "blk_form"]
    form = tree[2]
    field, items = form["children"]
    assert field["id"].startswith("blk_") and field["props"]["column"] == "bestellungen.name"
    assert [c["column"] for c in items["props"]["columns"]] == ["artikel.artikelname", "artikel.preis",
                                                                "artikel.anzahl"]
    assert all(c["id"].startswith("blk_") for c in form["children"])  # neue IDs für Blöcke ohne {#…}
    D.validate_tree(tree)


@pytest.mark.parametrize("md,message", [
    (":::form{#a}\n", "nicht geschlossen"), (":::\n", "schließt nichts"), ("::unbekannt{#a}\n", "unbekannte Direktive"),
    ("```\ncode", "nicht geschlossen"), ("::field{#a key='[1'}", "JSON"),
])
def test_markdown_errors_have_line_numbers(md, message):
    with pytest.raises(ValueError, match=message):
        M.markdown_to_blocks(md)


# ── DB ───────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def engine(monkeypatch):
    eng = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with eng.connect() as c:
            await c.execute(text("SELECT 1 FROM batches LIMIT 1"))
    except Exception:
        pytest.skip("Postgres nicht erreichbar")
    monkeypatch.setattr(pipeline, "SessionLocal", async_sessionmaker(eng, expire_on_commit=False))

    async def fake_enqueue(kind, id_):
        pass

    monkeypatch.setattr(pipeline, "enqueue_reembed", fake_enqueue)
    async with eng.begin() as c:
        for member, role in ((ANNA.id, "einkauf"), (BEN.id, "mitarbeiter")):
            await c.execute(text("""INSERT INTO roles (id, workspace_id, key, name) VALUES (:i, 'ws_demo', :k, :k)
                                    ON CONFLICT (workspace_id, key) DO NOTHING"""), {"i": f"rol_zz14{role}", "k": role})
            await c.execute(text("""INSERT INTO member_roles (workspace_id, member_id, role_id)
                                    SELECT 'ws_demo', :m, id FROM roles WHERE workspace_id = 'ws_demo' AND key = :k
                                    ON CONFLICT DO NOTHING"""), {"m": member, "k": role})
    yield eng
    async with eng.begin() as c:
        for stmt in (
            "DELETE FROM oplog WHERE batch_id LIKE '%zz14%'",
            "DELETE FROM batches WHERE batch_id LIKE '%zz14%'",
            "DELETE FROM channels WHERE id LIKE '%zz14%'",
            'DELETE FROM "references" WHERE source_id LIKE \'%zz14%\' OR target_id LIKE \'%zz14%\'',
            "DELETE FROM documents WHERE id LIKE '%zz14%'",
            "DELETE FROM tables WHERE id LIKE '%zz14%'",
            "DELETE FROM member_roles WHERE member_id LIKE '%zz14%'",
            "DELETE FROM roles WHERE id LIKE '%zz14%'",
        ):
            await c.execute(text(stmt))
    await eng.dispose()


async def q(engine, sql, **params):
    async with engine.connect() as c:
        return (await c.execute(text(sql), params)).mappings().all()


async def run(*ops, actor=ANNA, base=None):
    return await pipeline.apply_batch(batch(*ops, base=base), actor)


async def make_table(engine, key=None):
    """Tabelle direkt per SQL (die Schreib-Handler gehören zu 1.3)."""
    tid, key = zid("tbl"), key or zid("k")
    cols = {k: zid("col") for k in ("name", "preis")}
    async with engine.begin() as c:
        await c.execute(text("INSERT INTO tables (id, workspace_id, key, name) VALUES (:i, 'ws_demo', :k, 'T')"),
                        {"i": tid, "k": key})
        for pos, (ckey, cid) in enumerate(cols.items()):
            kind = "currency" if ckey == "preis" else "text"
            await c.execute(text("""INSERT INTO columns (id, table_id, key, name, type, position)
                                    VALUES (:i, :t, :k, :k, CAST(:ty AS jsonb), :p)"""),
                            {"i": cid, "t": tid, "k": ckey, "ty": json.dumps({"kind": kind}), "p": f"a{pos}"})
    return {"id": tid, "key": key, "cols": cols}


async def order(engine, doc, parent=None):
    rows = await q(engine, """SELECT id FROM blocks WHERE doc_id = :d AND parent_id IS NOT DISTINCT FROM
                              CAST(:p AS text) ORDER BY position""", d=doc, p=parent)
    return [r["id"] for r in rows]


async def test_doc_create_with_tree_and_read_back(engine):
    doc = zid("doc")
    ids = {k: zid("blk") for k in ("l", "i1", "i2", "p")}
    tree = [{"id": ids["p"], "type": "paragraph", "props": {"content": [{"t": "text", "text": "Hallo"}]}},
            {"id": ids["l"], "type": "list", "props": {}, "children": [
                {"id": ids["i1"], "type": "list_item", "props": {"content": []}},
                {"id": ids["i2"], "type": "list_item", "props": {"content": []}}]}]
    result = await run({"op": "doc.create", "id": doc, "title": "Test", "blocks": tree})
    assert result.results["0"]["block_ids"] == [ids["p"], ids["l"], ids["i1"], ids["i2"]]
    assert set(result.seq) == {"workspace", f"doc:{doc}"}
    assert await order(engine, doc) == [ids["p"], ids["l"]]
    assert await order(engine, doc, ids["l"]) == [ids["i1"], ids["i2"]]
    assert (await q(engine, "SELECT version FROM documents WHERE id = :d", d=doc))[0]["version"] == 1
    log = await q(engine, "SELECT inverse FROM oplog WHERE channel = :c", c=f"doc:{doc}")
    assert log[0]["inverse"] == [{"op": "doc.delete", "doc": doc}]

    async with async_sessionmaker(engine)() as s:
        got = await queries.fetch_document(s, doc)
    assert [b["id"] for b in got["blocks"]] == [ids["p"], ids["l"], ids["i1"], ids["i2"]]
    assert got["document"]["title"] == "Test"


async def test_doc_create_free_for_all_roles_step_docs_need_einkauf_and_unique_ids(engine):
    doc = zid("doc")
    with pytest.raises(PipelineError) as exc:  # Schritt-Dokument eines Workflows: nur `einkauf`
        await run({"op": "doc.create", "id": doc, "title": "x", "owner": {"workflow": "wf_x", "step": "s"}}, actor=BEN)
    assert exc.value.error.code == "FORBIDDEN"
    free = zid("doc")
    await run({"op": "doc.create", "id": free, "title": "Notiz von Ben, Straße 1"}, actor=BEN)  # freies Dokument: alle Rollen
    assert (await q(engine, "SELECT title FROM documents WHERE id = :d", d=free))[0]["title"] == "Notiz von Ben, Straße 1"
    dup = zid("blk")
    with pytest.raises(PipelineError) as exc:
        await run({"op": "doc.create", "id": doc, "title": "x", "blocks": [para(id_=dup), para(id_=dup)]})
    assert exc.value.error.code == "VALIDATION" and dup in exc.value.error.message
    assert not await q(engine, "SELECT 1 FROM documents WHERE id = :d", d=doc)  # atomar


async def test_markdown_import_and_get_markdown_roundtrip(engine):
    tbl = await make_table(engine, key=zid("art"))
    other = await make_table(engine, key=zid("best"))
    doc, form, tv = zid("doc"), zid("blk"), zid("blk")
    md = f"""# Bestellung {{#{zid('blk')}}}

Hinweis mit **fett**. {{#{zid('blk')}}}

::table_view{{#{tv} table={tbl['key']} columns="name,preis" editable=true}}

:::form{{#{form}}}
::field{{#{zid('blk')} key=name label="Name" column={other['key']}.name}}
::line_items{{#{zid('blk')} key=artikel label="Artikel" columns="name,preis" from={tbl['key']}}}
:::
"""
    result = await run({"op": "doc.create", "id": doc, "title": "Import", "markdown": md})
    assert len(result.results["0"]["block_ids"]) == 6

    stored = (await q(engine, "SELECT props FROM blocks WHERE id = :i", i=tv))[0]["props"]
    assert stored["table"] == tbl["id"] and stored["columns"] == [tbl["cols"]["name"], tbl["cols"]["preis"]]
    refs = await q(engine, 'SELECT target_kind, target_id, via FROM "references" WHERE source_id = :i', i=tv)
    assert {(r["target_kind"], r["target_id"], r["via"]) for r in refs} >= {
        ("table", tbl["id"], "table_view"), ("column", tbl["cols"]["name"], "table_view")}

    async with async_sessionmaker(engine)() as s:
        first = await queries.fetch_document_markdown(s, doc)
        json_before = await queries.fetch_document(s, doc)
    assert tbl["key"] in first["markdown"] and "columns=" in first["markdown"]  # Keys statt IDs
    assert f"{other['key']}.name" in first["markdown"]

    # Hin und zurück: löschen, aus dem Markdown neu anlegen, gleiche Blöcke
    await run({"op": "doc.delete", "doc": doc})
    await run({"op": "doc.create", "id": doc, "title": "Import", "markdown": first["markdown"]})
    async with async_sessionmaker(engine)() as s:
        json_after = await queries.fetch_document(s, doc)
    strip = lambda d: [{k: b[k] for k in ("id", "parent_id", "type", "props")} for b in d["blocks"]]  # noqa: E731
    assert strip(json_after) == strip(json_before)


async def test_markdown_errors_and_unknown_table(engine):
    with pytest.raises(PipelineError) as exc:
        await run({"op": "doc.create", "id": zid("doc"), "title": "x", "markdown": ":::form{#a}\n"})
    assert exc.value.error.code == "VALIDATION" and "nicht geschlossen" in exc.value.error.message
    with pytest.raises(PipelineError) as exc:
        await run({"op": "doc.create", "id": zid("doc"), "title": "x",
                   "markdown": "::table_view{#zz14a table=gibtsnicht}"})
    assert exc.value.error.code == "NOT_FOUND"
    with pytest.raises(PipelineError) as exc:
        await run({"op": "doc.create", "id": zid("doc"), "title": "x", "markdown": "::field{#zz14b key=a label=A}"})
    assert exc.value.error.code == "VALIDATION" and "form" in exc.value.error.message


async def test_block_insert_after_first_last_and_children(engine):
    doc = zid("doc")
    a, b = zid("blk"), zid("blk")
    await run({"op": "doc.create", "id": doc, "title": "T", "blocks": [para(id_=a), para(id_=b)]})
    mid, last, first = zid("blk"), zid("blk"), zid("blk")
    r = await run({"op": "block.insert", "doc": doc, "after": a, "block": para(id_=mid)},
                  {"op": "block.insert", "doc": doc, "block": para(id_=last)},
                  {"op": "block.insert", "doc": doc, "after": "^", "block": para(id_=first)})
    assert await order(engine, doc) == [first, a, mid, b, last]
    assert (await q(engine, "SELECT version FROM documents WHERE id = :d", d=doc))[0]["version"] == 2  # einmal je Batch
    assert r.results["0"]["id"] == mid
    log = await q(engine, "SELECT inverse FROM oplog WHERE channel = :c AND seq = :s", c=f"doc:{doc}", s=r.seq[f"doc:{doc}"])
    assert [i["op"] for i in log[0]["inverse"]] == ["block.delete"] * 3

    lst, item = zid("blk"), zid("blk")
    await run({"op": "block.insert", "doc": doc, "block": {
        "id": lst, "type": "list", "props": {}, "children": [
            {"id": item, "type": "list_item", "props": {"content": []}}]}})
    assert await order(engine, doc, lst) == [item]

    with pytest.raises(PipelineError) as exc:
        await run({"op": "block.insert", "doc": doc, "after": "blk_gibtsnicht", "block": para()})
    assert exc.value.error.code == "VALIDATION"
    with pytest.raises(PipelineError) as exc:
        await run({"op": "block.insert", "doc": doc, "parent": a, "block": para()})  # Absatz hat keine Kinder
    assert exc.value.error.code == "VALIDATION"
    with pytest.raises(PipelineError) as exc:
        await run({"op": "block.insert", "doc": doc, "block": {
            "id": zid("blk"), "type": "field", "props": {"key": "x", "label": "X"}}})
    assert exc.value.error.code == "VALIDATION" and "form" in exc.value.error.message


async def test_block_update_merges_props_and_validates(engine):
    doc, h = zid("doc"), zid("blk")
    await run({"op": "doc.create", "id": doc, "title": "T", "blocks": [
        {"id": h, "type": "heading", "props": {"level": 1, "content": [{"t": "text", "text": "Titel"}]}}]})
    r = await run({"op": "block.update", "block": h, "props": {"level": 2}})
    assert r.results["0"]["changed"] == ["level"]
    row = (await q(engine, "SELECT props, version FROM blocks WHERE id = :i", i=h))[0]
    assert row["props"]["level"] == 2 and row["props"]["content"][0]["text"] == "Titel" and row["version"] == 2
    log = await q(engine, "SELECT inverse FROM oplog WHERE channel = :c AND seq = :s", c=f"doc:{doc}", s=r.seq[f"doc:{doc}"])
    assert log[0]["inverse"] == [{"op": "block.update", "block": h, "props": {"level": 1}}]

    for bad in ({"level": 7}, {"unbekannt": 1}):
        with pytest.raises(PipelineError) as exc:
            await run({"op": "block.update", "block": h, "props": bad})
        assert exc.value.error.code == "VALIDATION" and "props" in exc.value.error.message
    await run({"op": "block.update", "block": h, "props": {"level": 2}})  # unverändert: keine Versionserhöhung
    assert (await q(engine, "SELECT version FROM blocks WHERE id = :i", i=h))[0]["version"] == 2

    with pytest.raises(PipelineError) as exc:  # base-Version veraltet
        await run({"op": "block.update", "block": h, "props": {"level": 3}}, base={h: 1})
    assert exc.value.error.code == "CONFLICT"


async def test_block_update_resolves_keys_and_tracks_references(engine):
    tbl = await make_table(engine)
    doc, tv = zid("doc"), zid("blk")
    await run({"op": "doc.create", "id": doc, "title": "T", "blocks": [
        {"id": tv, "type": "table_view", "props": {"table": tbl["id"]}}]})
    await run({"op": "block.update", "block": tv, "props": {
        "columns": ["name"], "filter": [{"column": "preis", "op": "gt", "value": 3}]}})
    props = (await q(engine, "SELECT props FROM blocks WHERE id = :i", i=tv))[0]["props"]
    assert props["columns"] == [tbl["cols"]["name"]] and props["filter"][0]["column"] == tbl["cols"]["preis"]
    refs = {(r["target_id"], r["via"]) for r in await q(engine, 'SELECT * FROM "references" WHERE source_id = :i', i=tv)}
    assert refs == {(tbl["id"], "table_view"), (tbl["cols"]["name"], "table_view"), (tbl["cols"]["preis"], "filter")}
    await run({"op": "block.update", "block": tv, "props": {"columns": None, "filter": []}})  # Kanten werden ersetzt
    refs = {r["target_id"] for r in await q(engine, 'SELECT * FROM "references" WHERE source_id = :i', i=tv)}
    assert refs == {tbl["id"]}
    with pytest.raises(PipelineError) as exc:
        await run({"op": "block.update", "block": tv, "props": {"columns": ["gibtsnicht"]}})
    assert exc.value.error.code == "NOT_FOUND"


async def test_block_move_and_cycle_and_inverse(engine):
    doc = zid("doc")
    a, b, lst, item = zid("blk"), zid("blk"), zid("blk"), zid("blk")
    await run({"op": "doc.create", "id": doc, "title": "T", "blocks": [
        para(id_=a), para(id_=b),
        {"id": lst, "type": "list", "props": {}, "children": [{"id": item, "type": "list_item", "props": {}}]}]})
    r = await run({"op": "block.move", "block": b, "after": "^"})
    assert await order(engine, doc) == [b, a, lst]
    log = await q(engine, "SELECT inverse FROM oplog WHERE channel = :c AND seq = :s", c=f"doc:{doc}", s=r.seq[f"doc:{doc}"])
    assert log[0]["inverse"] == [{"op": "block.move", "block": b, "parent": None, "after": a}]
    await run({"op": "block.move", "block": b, "after": lst})
    assert await order(engine, doc) == [a, lst, b]

    with pytest.raises(PipelineError) as exc:
        await run({"op": "block.move", "block": lst, "parent": item})
    assert exc.value.error.code == "VALIDATION"
    with pytest.raises(PipelineError) as exc:  # Absatz in Liste: nicht erlaubt
        await run({"op": "block.move", "block": a, "parent": lst})
    assert exc.value.error.code == "VALIDATION"
    other = zid("doc")
    ob = zid("blk")
    await run({"op": "doc.create", "id": other, "title": "O", "blocks": [para(id_=ob)]})
    with pytest.raises(PipelineError) as exc:
        await run({"op": "block.move", "block": a, "parent": ob})
    assert exc.value.error.code == "VALIDATION"


async def test_block_delete_cascades_with_inverse_and_references(engine):
    tbl = await make_table(engine)
    doc, lst, i1, i2, tv, keep = (zid("doc"), zid("blk"), zid("blk"), zid("blk"), zid("blk"), zid("blk"))
    await run({"op": "doc.create", "id": doc, "title": "T", "blocks": [
        para(id_=keep),
        {"id": lst, "type": "list", "props": {}, "children": [
            {"id": i1, "type": "list_item", "props": {}}, {"id": i2, "type": "list_item", "props": {}}]},
        {"id": tv, "type": "table_view", "props": {"table": tbl["key"]}}]})
    r = await run({"op": "block.delete", "block": lst}, {"op": "block.delete", "block": tv})
    assert await order(engine, doc) == [keep]
    assert not await q(engine, "SELECT 1 FROM blocks WHERE id = ANY(:ids)", ids=[lst, i1, i2])
    assert not await q(engine, 'SELECT 1 FROM "references" WHERE source_id = :i', i=tv)
    inverse = (await q(engine, "SELECT inverse FROM oplog WHERE channel = :c AND seq = :s",
                       c=f"doc:{doc}", s=r.seq[f"doc:{doc}"]))[0]["inverse"]
    # Undo: die inversen Ops stellen Liste samt Kindern an der alten Stelle wieder her
    await run(*inverse)
    assert await order(engine, doc) == [keep, lst, tv]
    assert await order(engine, doc, lst) == [i1, i2]
    assert await q(engine, 'SELECT 1 FROM "references" WHERE source_id = :i', i=tv)


async def test_doc_update_and_delete_with_undo_and_in_use(engine):
    doc, p = zid("doc"), zid("blk")
    await run({"op": "doc.create", "id": doc, "title": "Alt", "blocks": [para(id_=p)]})
    await run({"op": "doc.update", "doc": doc, "title": "Neu"})
    assert (await q(engine, "SELECT title, version FROM documents WHERE id = :d", d=doc))[0] == {"title": "Neu", "version": 2}
    with pytest.raises(PipelineError) as exc:
        await run({"op": "doc.update", "doc": "doc_gibtsnicht", "title": "x"})
    assert exc.value.error.code == "NOT_FOUND"

    r = await run({"op": "doc.delete", "doc": doc})
    assert not await q(engine, "SELECT 1 FROM documents WHERE id = :d", d=doc)
    assert not await q(engine, "SELECT 1 FROM blocks WHERE id = :i", i=p)
    inverse = (await q(engine, "SELECT inverse FROM oplog WHERE channel = :c AND seq = :s",
                       c=f"doc:{doc}", s=r.seq[f"doc:{doc}"]))[0]["inverse"]
    await run(*inverse)
    assert await order(engine, doc) == [p]

    wf = zid("wf")
    async with engine.begin() as c:  # Workflow als Verwender (Kante step.document)
        await c.execute(text("""INSERT INTO "references" (source_kind, source_id, target_kind, target_id, via)
                                VALUES ('workflow', :w, 'document', :d, 'step.document')"""), {"w": wf, "d": doc})
    with pytest.raises(PipelineError) as exc:
        await run({"op": "doc.delete", "doc": doc})
    assert exc.value.error.code == "IN_USE" and wf in exc.value.error.message
    assert await q(engine, "SELECT 1 FROM documents WHERE id = :d", d=doc)


async def test_agent_blocked_while_human_edits(engine):
    doc, p = zid("doc"), zid("blk")
    await run({"op": "doc.create", "id": doc, "title": "T", "blocks": [para(id_=p)]})
    await presence.update(f"doc:{doc}", BEN, PresenceState(editing=p), conn_id="zz14")
    try:
        for op in ({"op": "block.update", "block": p, "props": {"content": []}},
                   {"op": "block.move", "block": p, "after": "^"}, {"op": "block.delete", "block": p}):
            with pytest.raises(PipelineError) as exc:
                await run(op, actor=AGENT)
            assert exc.value.error.code == "BLOCK_IN_USE"
        await run({"op": "block.update", "block": p, "props": {"content": []}}, actor=ANNA)  # Menschen nicht
    finally:
        await presence.remove(f"doc:{doc}", BEN, conn_id="zz14")
    await run({"op": "block.update", "block": p, "props": {"content": []}}, actor=AGENT)  # danach frei


# ── lesende Endpunkte ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[current_user] = lambda: CurrentUser(
        id=ANNA.id, name="Anna", email="a@example.local", roles=["einkauf"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(current_user, None)


async def test_document_endpoints(engine, api):
    doc, h = zid("doc"), zid("blk")
    await run({"op": "doc.create", "id": doc, "title": "ZZ14 Titel", "markdown": f"# Hallo {{#{h}}}\n"})
    listing = (await api.get("/api/documents")).json()
    assert any(d["id"] == doc and d["title"] == "ZZ14 Titel" for d in listing)
    body = (await api.get(f"/api/documents/{doc}")).json()
    assert body["document"]["id"] == doc and body["blocks"][0]["id"] == h and body["blocks"][0]["position"]
    md = (await api.get(f"/api/documents/{doc}/markdown")).json()
    assert md["markdown"] == f"# Hallo {{#{h}}}\n"
    assert (await api.get("/api/documents/doc_gibtsnicht")).status_code == 404


async def insert_rows(engine, tbl, rows):
    async with engine.begin() as c:
        for i, (name, preis) in enumerate(rows):
            vals = {tbl["cols"]["name"]: name}
            if preis is not None:
                vals[tbl["cols"]["preis"]] = preis
            await c.execute(text("""INSERT INTO rows (id, table_id, position, "values")
                                    VALUES (:i, :t, :p, CAST(:v AS jsonb))"""),
                            {"i": zid("row"), "t": tbl["id"], "p": f"a{i}", "v": json.dumps(vals)})


async def test_table_and_row_endpoints_filters(engine, api):
    tbl = await make_table(engine)
    await insert_rows(engine, tbl, [("Schraube", 2.5), ("Mutter", 10), ("Dübel", 7.25), ("Hammer", None), ("schrank", 99)])
    got = (await api.get(f"/api/tables/{tbl['key']}")).json()
    assert got["id"] == tbl["id"] and [c["key"] for c in got["columns"]] == ["name", "preis"]
    assert any(t["id"] == tbl["id"] for t in (await api.get("/api/tables")).json())
    assert (await api.get("/api/tables/gibtsnicht")).status_code == 404

    async def query(**body):
        res = await api.post(f"/api/tables/{tbl['key']}/rows/query", json=body)
        assert res.status_code == 200, res.text
        data = res.json()
        return [r["values"].get(tbl["cols"]["name"]) for r in data["rows"]], data["total"]

    assert await query() == (["Schraube", "Mutter", "Dübel", "Hammer", "schrank"], 5)
    assert (await query(filter=[{"column": "preis", "op": "gt", "value": 5}]))[0] == ["Mutter", "Dübel", "schrank"]
    assert (await query(filter=[{"column": tbl["cols"]["preis"], "op": "lte", "value": "7,25"}]))[0] == [
        "Schraube", "Dübel"]  # Spalten-ID, Zahl als Text mit Komma
    assert (await query(filter=[{"column": "name", "op": "contains", "value": "sch"}]))[0] == ["Schraube", "schrank"]
    assert (await query(filter=[{"column": "name", "op": "eq", "value": "Mutter"}]))[0] == ["Mutter"]
    assert (await query(filter=[{"column": "name", "op": "in", "value": ["Mutter", "Hammer"]}]))[0] == ["Mutter", "Hammer"]
    assert (await query(filter=[{"column": "preis", "op": "is_null"}]))[0] == ["Hammer"]
    assert (await query(filter=[{"column": "preis", "op": "ne", "value": 10}]))[1] == 4
    assert (await query(sort=[{"column": "preis", "dir": "desc"}]))[0] == ["schrank", "Mutter", "Dübel", "Schraube", "Hammer"]
    assert await query(sort=[{"column": "name"}], limit=2, offset=1) == (["Hammer", "Mutter"], 5)

    bad = await api.post(f"/api/tables/{tbl['key']}/rows/query", json={"filter": [{"column": "nix", "op": "eq"}]})
    assert bad.status_code == 422
    expr = await api.post(f"/api/tables/{tbl['key']}/rows/query",
                          json={"filter": [{"column": "name", "op": "eq", "value": "{{run.id}}"}]})
    assert expr.status_code == 422  # `run` gibt es in einer Abfrage nicht
    assert (await query(filter=[{"column": "name", "op": "eq", "value": '{{concat("Mu", "tter")}}'}]))[0] == ["Mutter"]


async def test_table_view_block_protects_table_and_column_from_delete(engine):
    """Zusammenspiel 1.3/1.4: Kanten der Block-Handler lösen den Löschschutz der Tabellen-Handler aus (L 9)."""
    tbl = await make_table(engine, key=zid("art"))
    doc, tv = zid("doc"), zid("blk")
    await run({"op": "doc.create", "id": doc, "title": "Ansicht", "blocks": [
        {"id": tv, "type": "table_view", "props": {"table": tbl["key"], "columns": ["name"]}}]})

    for op in ({"op": "table.delete", "table": tbl["id"]},
               {"op": "column.delete", "table": tbl["id"], "column": tbl["cols"]["name"]}):
        with pytest.raises(PipelineError) as exc:
            await run(op)
        assert exc.value.error.code == "IN_USE"
        assert tv in json.dumps(exc.value.error.details)

    # Block weg, dann ist die Tabelle wieder löschbar
    await run({"op": "block.delete", "block": tv})
    await run({"op": "table.delete", "table": tbl["id"]})
    assert not await q(engine, "SELECT 1 FROM tables WHERE id = :i", i=tbl["id"])


async def test_text_edit_transforms_concurrent_edits(engine):
    """F15 (L 7.5, T 2.6): zwei Edits auf derselben Basis-Version; der zweite wird hinter den ersten verschoben.
    Ins Op-Log geht der transformierte Edit (Schreibweise `from`) mit der Version vor der Änderung."""
    doc, p, d = zid("doc"), zid("blk"), zid("blk")
    await run({"op": "doc.create", "id": doc, "title": "T", "blocks": [
        para("Hallo", id_=p), {"id": d, "type": "divider", "props": {}}]})
    await run({"op": "text.edit", "block": p, "version": 1, "from": 5, "to": 5, "insert": " Anna"})
    r = await run({"op": "text.edit", "block": p, "version": 1, "from": 5, "to": 5, "insert": " Ben",
                   "marks": [{"from": 1, "to": 4, "mark": "bold"}]})
    assert r.results["0"] == {"id": p, "from": 10, "to": 10, "version": 2}
    row = (await q(engine, "SELECT props, version FROM blocks WHERE id = :i", i=p))[0]
    assert row["version"] == 3
    assert [(c["text"], c.get("marks", [])) for c in row["props"]["content"]] == [("Hallo Anna ", []), ("Ben", ["bold"])]
    log = await q(engine, "SELECT ops, inverse FROM oplog WHERE channel = :c AND seq = :s", c=f"doc:{doc}", s=r.seq[f"doc:{doc}"])
    assert log[0]["ops"][0]["from"] == 10 and log[0]["ops"][0]["version"] == 2 and "from_" not in log[0]["ops"][0]
    assert log[0]["inverse"][0]["props"]["content"][0]["text"] == "Hallo Anna"

    # Löschen davor, Basis veraltet: Einfügen rückt nach links
    await run({"op": "text.edit", "block": p, "version": 3, "from": 0, "to": 6, "insert": ""})
    await run({"op": "text.edit", "block": p, "version": 3, "from": 14, "to": 14, "insert": "!"})
    row = (await q(engine, "SELECT props FROM blocks WHERE id = :i", i=p))[0]
    assert "".join(c["text"] for c in row["props"]["content"]) == "Anna Ben!"

    with pytest.raises(PipelineError) as exc:
        await run({"op": "text.edit", "block": d, "version": 1, "from": 0, "to": 0, "insert": "x"})
    assert exc.value.error.code == "VALIDATION"

    await presence.update(f"doc:{doc}", BEN, PresenceState(editing=p), conn_id="zz14")
    try:
        with pytest.raises(PipelineError) as exc:
            await run({"op": "text.edit", "block": p, "version": 5, "from": 0, "to": 0, "insert": "x"}, actor=AGENT)
        assert exc.value.error.code == "BLOCK_IN_USE"
        await run({"op": "text.edit", "block": p, "version": 5, "from": 0, "to": 0, "insert": "x"}, actor=ANNA)
    finally:
        await presence.remove(f"doc:{doc}", BEN, conn_id="zz14")
