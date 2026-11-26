"""Tabellen-Handler (Task 1.3) gegen Postgres, durch die echte Op-Pipeline.

Läuft gegen Postgres (Standard: Host-Port 5433, überschreibbar mit TEST_DATABASE_URL). Alle Testdaten tragen den
Marker `zz13` und werden nach jedem Test entfernt. Die reine Fachlogik und die Fixtures testen `test_tables_domain.py`
und `test_fixtures.py`.
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

from app.ops import pipeline
from app.ops.errors import PipelineError
from app.ops.handlers import HANDLERS, load_handlers
from app.schemas.common import Actor
from app.schemas.ops import OpBatch

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock_test")
SYSTEM = Actor(type="system", id="workflow")


def zid(prefix: str) -> str:
    return f"{prefix}_zz13{uuid.uuid4().hex[:10]}"


def batch(*ops) -> OpBatch:
    return OpBatch.model_validate({"batch_id": zid("b"), "ops": list(ops)})


def cdef(key, type_=None, **kw):
    return {"id": zid("col"), "key": key, "name": key.capitalize(), "type": type_ or {"kind": "text"}, **kw}


def tdef(key=None, columns=(), **kw):
    tid = zid("tbl")
    return {"op": "table.create", "id": tid, "key": key or "zz13_" + tid[-10:], "name": "Tabelle", "columns": list(columns), **kw}


def rows(*items):
    return [{"id": zid("row"), "values": v} for v in items]


@pytest_asyncio.fixture
async def engine(monkeypatch):
    eng = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with eng.connect() as c:
            await c.execute(text("SELECT 1 FROM row_links LIMIT 1"))
    except Exception:
        pytest.skip("Postgres nicht erreichbar")
    monkeypatch.setattr(pipeline, "SessionLocal", async_sessionmaker(eng, expire_on_commit=False))
    load_handlers()
    if "row.insert" not in HANDLERS:  # ein anderer Test hat die Registry zurückgesetzt
        from app.ops.handlers import tables
        importlib.reload(tables)

    async def fake_enqueue(kind, id_):
        pass

    monkeypatch.setattr(pipeline, "enqueue_reembed", fake_enqueue)
    yield eng
    async with eng.begin() as c:
        for stmt in (
            "DELETE FROM oplog WHERE batch_id LIKE '%zz13%'",
            "DELETE FROM batches WHERE batch_id LIKE '%zz13%'",
            "DELETE FROM channels WHERE id LIKE '%zz13%'",
            'DELETE FROM "references" WHERE source_id LIKE \'%zz13%\' OR target_id LIKE \'%zz13%\'',
            "DELETE FROM row_links WHERE from_row LIKE '%zz13%'",
            "DELETE FROM rows WHERE id LIKE '%zz13%'",
            "DELETE FROM tables WHERE id LIKE '%zz13%'",
        ):
            await c.execute(text(stmt))
    await eng.dispose()


async def run(*ops, actor=SYSTEM):
    return await pipeline.apply_batch(batch(*ops), actor)


async def q(engine, sql, **params):
    async with engine.connect() as c:
        return (await c.execute(text(sql), params)).mappings().all()


def j(value):
    return json.loads(value) if isinstance(value, str) else value


async def row_values(engine, row_id):
    return j((await q(engine, "SELECT values FROM rows WHERE id = :i", i=row_id))[0]["values"])


async def expect_error(code, *ops):
    with pytest.raises(PipelineError) as e:
        await run(*ops)
    assert e.value.error.code == code, e.value.error
    return e.value.error


async def make_best(engine, with_rows=True):
    name = cdef("name", required=True)
    ks = cdef("kostenstelle")
    preis = cdef("preis", {"kind": "currency", "currency": "EUR"})
    anz = cdef("anzahl", {"kind": "integer", "min": 1})
    t = tdef(columns=[name, ks, preis, anz])
    ops = [t]
    r = rows({name["id"]: "Monitor", ks["id"]: "4711", preis["id"]: "249,50", anz["id"]: "2"},
             {name["id"]: "Kabel", ks["id"]: "4712", anz["id"]: 5})
    if with_rows:
        ops.append({"op": "row.insert", "table": t["id"], "rows": r})
    await run(*ops)
    return {"t": t["id"], "name": name["id"], "ks": ks["id"], "preis": preis["id"], "anz": anz["id"],
            "rows": [x["id"] for x in r]}


# ── table.create / Zeilen ────────────────────────────────────────────────────


async def test_create_table_insert_rows_by_key_and_coerce(engine):
    t = tdef(key="zz13_best", columns=[cdef("name", required=True), cdef("preis", {"kind": "currency"}),
                                       cdef("anzahl", {"kind": "integer", "min": 1})])
    r = rows({"name": "Monitor", "preis": "249,50", "anzahl": "2"})
    result = await run(t, {"op": "row.insert", "table": "zz13_best", "rows": r})
    col = {c["key"]: c["id"] for c in t["columns"]}
    assert result.results["1"] == {"ids": [r[0]["id"]]}
    table = (await q(engine, "SELECT version, display_column FROM tables WHERE id = :i", i=t["id"]))[0]
    assert (table["version"], table["display_column"]) == (1, col["name"])  # erste Spalte ist Anzeigespalte
    assert await row_values(engine, r[0]["id"]) == {col["name"]: "Monitor", col["preis"]: 249.5, col["anzahl"]: 2}
    log = await q(engine, "SELECT inverse FROM oplog WHERE batch_id = :b LIMIT 1", b=result.batch_id)
    assert [i["op"] for i in j(log[0]["inverse"])] == ["row.delete", "table.delete"]


async def test_row_errors_are_per_field_and_atomic(engine):
    t = tdef(key="zz13_x", columns=[cdef("name", required=True), cdef("anzahl", {"kind": "integer", "min": 1})])
    err = await expect_error("VALIDATION", t, {"op": "row.insert", "table": "zz13_x", "rows": rows(
        {"name": "ok", "anzahl": 1}, {"anzahl": "0"})})
    assert set(err.details["errors"]) == {"rows[1].name", "rows[1].anzahl"}
    assert "mindestens 1" in err.details["errors"]["rows[1].anzahl"]
    assert await q(engine, "SELECT 1 FROM tables WHERE id = :i", i=t["id"]) == []  # Tabelle wurde mit zurückgerollt


async def test_unique_required_and_duplicate_row_id(engine):
    ids = await make_best(engine)
    r = rows({ids["name"]: "A", ids["ks"]: "4711"})
    t_unique = {"op": "column.update", "table": ids["t"], "column": ids["ks"], "patch": {"unique": True}}
    await run(t_unique)
    err = await expect_error("VALIDATION", {"op": "row.insert", "table": ids["t"], "rows": r})
    assert "kostenstelle" in err.details["errors"] and "schon vergeben" in err.details["errors"]["kostenstelle"]
    err = await expect_error("VALIDATION", {"op": "row.insert", "table": ids["t"],
                                            "rows": [{"id": ids["rows"][0], "values": {ids["name"]: "B"}}]})
    assert "id" in err.details["errors"]
    err = await expect_error("VALIDATION", {"op": "row.update", "table": ids["t"], "row": ids["rows"][0],
                                            "values": {ids["name"]: None}})
    assert "Pflichtfeld" in err.details["errors"]["name"]


async def test_row_update_merges_and_bumps_version_once(engine):
    ids = await make_best(engine)
    row_id = ids["rows"][0]
    await run({"op": "row.update", "table": ids["t"], "row": row_id, "values": {ids["ks"]: "4712"}},
              {"op": "row.update", "table": ids["t"], "row": row_id, "values": {ids["anz"]: "7"}})
    assert await row_values(engine, row_id) == {ids["name"]: "Monitor", ids["ks"]: "4712", ids["preis"]: 249.5, ids["anz"]: 7}
    assert (await q(engine, "SELECT version FROM rows WHERE id = :i", i=row_id))[0]["version"] == 2
    assert (await q(engine, "SELECT version FROM tables WHERE id = :i", i=ids["t"]))[0]["version"] == 1  # nur Schema zählt
    await run({"op": "row.update", "table": ids["t"], "row": row_id, "values": {ids["ks"]: None}})
    assert ids["ks"] not in await row_values(engine, row_id)


async def test_row_and_column_move(engine):
    ids = await make_best(engine)
    first, second = ids["rows"]
    third = rows({ids["name"]: "C"})
    await run({"op": "row.insert", "table": ids["t"], "rows": [{**third[0], "after": first}]})
    order = lambda: q(engine, "SELECT id FROM rows WHERE table_id = :t ORDER BY position", t=ids["t"])  # noqa: E731
    assert [r["id"] for r in await order()] == [first, third[0]["id"], second]
    await run({"op": "row.move", "table": ids["t"], "row": second, "after": None})  # an den Anfang
    assert [r["id"] for r in await order()][0] == second
    await run({"op": "column.move", "table": ids["t"], "column": ids["name"], "after": ids["anz"]})
    cols = await q(engine, "SELECT id FROM columns WHERE table_id = :t ORDER BY position", t=ids["t"])
    assert [c["id"] for c in cols][-1] == ids["name"]


# ── Spalten ──────────────────────────────────────────────────────────────────


async def test_column_add_default_backfills_and_required_is_rejected(engine):
    ids = await make_best(engine)
    new = cdef("lieferant", required=True)
    err = await expect_error("VALIDATION", {"op": "column.add", "table": ids["t"], "column": new})
    assert "column.required" in err.details["errors"]
    new["default"] = "unbekannt"
    await run({"op": "column.add", "table": ids["t"], "column": new})
    assert (await row_values(engine, ids["rows"][1]))[new["id"]] == "unbekannt"
    assert (await q(engine, "SELECT version FROM tables WHERE id = :i", i=ids["t"]))[0]["version"] == 2
    err = await expect_error("VALIDATION", {"op": "column.add", "table": ids["t"], "column": cdef("lieferant")})
    assert "column.key" in err.details["errors"]


async def test_column_type_change_converts_and_names_rows(engine):
    ids = await make_best(engine)
    await run({"op": "row.update", "table": ids["t"], "row": ids["rows"][1], "values": {ids["ks"]: "abc"}})
    result = await run({"op": "column.update", "table": ids["t"], "column": ids["ks"],
                        "patch": {"type": {"kind": "integer"}}})
    assert result.results["0"]["nulled"] == 1
    assert (await row_values(engine, ids["rows"][0]))[ids["ks"]] == 4711
    assert ids["ks"] not in await row_values(engine, ids["rows"][1])
    err = await expect_error("VALIDATION", {"op": "column.update", "table": ids["t"], "column": ids["name"],
                                            "patch": {"type": {"kind": "integer"}}})
    assert ids["rows"][0] in err.message and ids["rows"][0] in err.details["rows"]
    assert (await q(engine, "SELECT type FROM columns WHERE id = :i", i=ids["name"]))[0]["type"] in (
        {"kind": "text"}, '{"kind": "text"}')


async def test_column_set_required_and_unique_check_existing_rows(engine):
    ids = await make_best(engine)
    err = await expect_error("VALIDATION", {"op": "column.update", "table": ids["t"], "column": ids["preis"],
                                            "patch": {"required": True}})
    assert ids["rows"][1] in err.details["rows"]  # Zeile ohne Preis wird genannt
    await run({"op": "row.update", "table": ids["t"], "row": ids["rows"][1], "values": {ids["ks"]: "4711"}})
    err = await expect_error("VALIDATION", {"op": "column.update", "table": ids["t"], "column": ids["ks"],
                                            "patch": {"unique": True}})
    assert "4711" in err.message


async def test_column_delete_blocked_by_reference_index_then_ok(engine):
    ids = await make_best(engine)
    block = zid("blk")
    async with engine.begin() as c:
        await c.execute(text('''INSERT INTO "references" (source_kind, source_id, target_kind, target_id, via)
                                VALUES ('block', :b, 'column', :c, 'table_view')'''), {"b": block, "c": ids["preis"]})
    err = await expect_error("IN_USE", {"op": "column.delete", "table": ids["t"], "column": ids["preis"]})
    assert block in err.message
    assert err.details["usages"] == [{"source_kind": "block", "source_id": block, "via": "table_view"}]
    await run({"op": "column.delete", "table": ids["t"], "column": ids["name"]})
    assert ids["name"] not in await row_values(engine, ids["rows"][0])
    assert (await q(engine, "SELECT display_column FROM tables WHERE id = :i", i=ids["t"]))[0]["display_column"] == ids["ks"]


# ── Referenzen, on_delete ────────────────────────────────────────────────────


async def make_refs(engine, on_delete):
    parent = tdef(key=None, columns=[cdef("name")])
    child = tdef(key=None, columns=[cdef("name"), cdef("eltern", {"kind": "reference", "table": parent["id"], "on_delete": on_delete})])
    p_rows = rows({parent["columns"][0]["id"]: "P1"}, {parent["columns"][0]["id"]: "P2"})
    ref_col = child["columns"][1]["id"]
    c_rows = rows({child["columns"][0]["id"]: "C1", ref_col: p_rows[0]["id"]})
    await run(parent, child, {"op": "row.insert", "table": parent["id"], "rows": p_rows},
              {"op": "row.insert", "table": child["id"], "rows": c_rows})
    return parent["id"], child["id"], [r["id"] for r in p_rows], c_rows[0]["id"], ref_col


async def test_reference_is_indexed_and_checked(engine):
    parent, child, p_rows, c_row, ref_col = await make_refs(engine, "restrict")
    edges = await q(engine, 'SELECT target_kind, target_id, via FROM "references" WHERE source_id = :c', c=ref_col)
    assert [dict(e) for e in edges] == [{"target_kind": "table", "target_id": parent, "via": "reference_column"}]
    assert (await q(engine, "SELECT to_row FROM row_links WHERE from_row = :r", r=c_row))[0]["to_row"] == p_rows[0]
    err = await expect_error("VALIDATION", {"op": "row.update", "table": child, "row": c_row,
                                            "values": {ref_col: "row_zz13nope"}})
    assert "row_zz13nope" in err.details["errors"]["eltern"]
    await run({"op": "row.update", "table": child, "row": c_row, "values": {ref_col: p_rows[1]}})
    assert (await q(engine, "SELECT to_row FROM row_links WHERE from_row = :r", r=c_row))[0]["to_row"] == p_rows[1]


async def test_row_delete_restrict_blocks_and_lists_usages(engine):
    parent, child, p_rows, c_row, ref_col = await make_refs(engine, "restrict")
    err = await expect_error("IN_USE", {"op": "row.delete", "table": parent, "rows": [p_rows[0]]})
    assert c_row in err.message and err.details["usages"][0]["source_id"] == c_row
    await run({"op": "row.delete", "table": parent, "rows": [p_rows[1]]})  # unverwendete Zeile geht
    assert len(await q(engine, "SELECT 1 FROM rows WHERE table_id = :t", t=parent)) == 1


async def test_row_delete_cascade_and_set_null(engine):
    parent, child, p_rows, c_row, ref_col = await make_refs(engine, "cascade")
    result = await run({"op": "row.delete", "table": parent, "rows": [p_rows[0]]})
    assert set(result.results["0"]["deleted"]) == {p_rows[0], c_row}
    assert await q(engine, "SELECT 1 FROM rows WHERE id = :r", r=c_row) == []
    assert any(c.startswith("table:" + child) for c in result.seq)  # Kanal der abhängigen Tabelle gesperrt

    parent, child, p_rows, c_row, ref_col = await make_refs(engine, "set_null")
    await run({"op": "row.delete", "table": parent, "rows": [p_rows[0]]})
    assert ref_col not in await row_values(engine, c_row)
    assert (await q(engine, "SELECT version FROM rows WHERE id = :r", r=c_row))[0]["version"] == 2
    assert await q(engine, "SELECT 1 FROM row_links WHERE from_row = :r", r=c_row) == []


async def test_table_delete_in_use_and_cleanup(engine):
    parent, child, p_rows, c_row, ref_col = await make_refs(engine, "restrict")
    err = await expect_error("IN_USE", {"op": "table.delete", "table": parent})
    assert ref_col in err.message
    await run({"op": "table.delete", "table": child})  # Kinder zuerst
    assert await q(engine, 'SELECT 1 FROM "references" WHERE source_id = :c', c=ref_col) == []
    await run({"op": "table.delete", "table": parent})
    assert await q(engine, "SELECT 1 FROM tables WHERE id IN (:a, :b)", a=parent, b=child) == []


async def test_table_update_and_column_rename_keep_ids(engine):
    ids = await make_best(engine)
    await run({"op": "table.update", "table": ids["t"], "key": "zz13_neu", "name": "Neu"},
              {"op": "column.update", "table": ids["t"], "column": ids["ks"], "patch": {"key": "ks", "name": "KS"}})
    await run({"op": "row.update", "table": "zz13_neu", "row": ids["rows"][0], "values": {"ks": "1"}})
    assert (await row_values(engine, ids["rows"][0]))[ids["ks"]] == "1"
    other = tdef(key="zz13_neu")
    err = await expect_error("VALIDATION", other)
    assert "key" in err.details["errors"]
