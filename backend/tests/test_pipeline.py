"""Op-Pipeline (Task 1.2): Atomarität, Idempotenz, Konflikte, Rechte, Op-Log, Referenz-Index, NOTIFY.

Die fachlichen Handler gehören zu 1.3/1.4. Hier registrieren die Tests kleine Dummy-Handler (Fixture `handlers`).
Läuft gegen Postgres (Standard: Host-Port 5433, überschreibbar mit TEST_DATABASE_URL). Alle Testdaten tragen
den Marker `zz12` und werden nach jedem Test entfernt.
"""
import asyncio
import json
import os
import uuid

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain import references
from app.ops import pipeline
from app.ops.context import OpContext
from app.ops.errors import PipelineError
from app.ops.handlers import HANDLERS, register
from app.schemas.common import Actor
from app.schemas.ops import OpBatch

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock")
ANNA = Actor(type="user", id="usr_zz12anna", name="Anna")  # Rolle einkauf, angelegt in der Fixture `engine`
BEN = Actor(type="user", id="usr_zz12ben", name="Ben")  # Rolle mitarbeiter


def zid(prefix: str) -> str:
    return f"{prefix}_zz12{uuid.uuid4().hex[:10]}"


def batch(*ops, base=None, batch_id=None) -> OpBatch:
    return OpBatch.model_validate({"batch_id": batch_id or zid("b"), "base": base or {}, "ops": list(ops)})


def new_table(tid=None, key=None, cols=("name",)):
    tid = tid or zid("tbl")
    return {"op": "table.create", "id": tid, "key": key or tid, "name": "T",
            "columns": [{"id": zid("col"), "key": c, "name": c, "type": {"kind": "text"}} for c in cols]}


# ── Dummy-Handler (Stand-ins für 1.3/1.4) ────────────────────────────────────

calls: list[str] = []


async def h_table_create(ctx: OpContext, op):
    await ctx.session.execute(
        text("INSERT INTO tables (id, workspace_id, key, name) VALUES (:i, :ws, :k, :n)"),
        {"i": op.id, "ws": ctx.workspace_id, "k": op.key, "n": op.name})
    for pos, col in enumerate(op.columns):
        await ctx.session.execute(
            text("""INSERT INTO columns (id, table_id, key, name, type, position)
                    VALUES (:i, :t, :k, :n, CAST(:ty AS jsonb), :p)"""),
            {"i": col.id, "t": op.id, "k": col.key, "n": col.name, "ty": json.dumps(col.type.model_dump()),
             "p": f"a{pos}"})
    await ctx.touch("table", op.id, f"table:{op.id}", created=True)
    ctx.set_references("table", op.id, [("role", "rol_zz12", "step.assignee")])
    ctx.add_inverse({"op": "table.delete", "table": op.id})
    calls.append(op.op)
    return {"id": op.id}


async def h_row_insert(ctx: OpContext, op):
    for row in op.rows:
        await ctx.session.execute(
            text("""INSERT INTO rows (id, table_id, position, values)
                    VALUES (:i, :t, 'a0', CAST(:v AS jsonb))"""),
            {"i": row.id, "t": op.table, "v": json.dumps(row.values)})
        await ctx.touch("row", row.id, created=True)
    await ctx.touch("table", op.table, f"table:{op.table}")  # Tabelle als Quelle für die Suche
    ctx.add_inverse({"op": "row.delete", "table": op.table, "rows": [r.id for r in op.rows]})
    calls.append(op.op)
    return {"ids": [r.id for r in op.rows]}


async def h_row_update(ctx: OpContext, op):
    found = (await ctx.session.execute(
        text("""UPDATE rows SET values = values || CAST(:v AS jsonb) WHERE id = :i AND table_id = :t RETURNING id"""),
        {"i": op.row, "t": op.table, "v": json.dumps(op.values)})).scalar_one_or_none()
    if found is None:
        raise PipelineError("NOT_FOUND", f"Zeile '{op.row}' existiert nicht")
    await ctx.touch("row", op.row)
    calls.append(op.op)


async def h_role_create(ctx: OpContext, op):
    await ctx.session.execute(
        text("INSERT INTO roles (id, workspace_id, key, name) VALUES (:i, :ws, :k, :n)"),
        {"i": op.id, "ws": ctx.workspace_id, "k": op.key, "n": op.name})
    return {"id": op.id}


async def h_row_delete_refs(ctx: OpContext, op):  # nutzt `row.move` als Träger für Referenz-Tests
    ctx.set_references("block", op.row, [("table", op.table, "table_view")])


@pytest_asyncio.fixture
async def engine(monkeypatch):
    eng = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with eng.connect() as c:
            await c.execute(text("SELECT 1 FROM batches LIMIT 1"))
    except Exception:
        pytest.skip("Postgres nicht erreichbar")
    monkeypatch.setattr(pipeline, "SessionLocal", async_sessionmaker(eng, expire_on_commit=False))
    async with eng.begin() as c:
        for member, role in ((ANNA.id, "einkauf"), (BEN.id, "mitarbeiter")):
            await c.execute(text("""INSERT INTO roles (id, workspace_id, key, name) VALUES (:i, 'ws_demo', :k, :k)
                                    ON CONFLICT (workspace_id, key) DO NOTHING"""), {"i": f"rol_zz12{role}", "k": role})
            await c.execute(text("""INSERT INTO member_roles (workspace_id, member_id, role_id)
                                    SELECT 'ws_demo', :m, id FROM roles WHERE workspace_id = 'ws_demo' AND key = :k
                                    ON CONFLICT DO NOTHING"""), {"m": member, "k": role})
    yield eng
    async with eng.begin() as c:
        for stmt in (
            "DELETE FROM oplog WHERE batch_id LIKE '%zz12%'",
            "DELETE FROM batches WHERE batch_id LIKE '%zz12%'",
            "DELETE FROM channels WHERE id LIKE '%zz12%'",
            'DELETE FROM "references" WHERE source_id LIKE '"'"'%zz12%'"'"' OR target_id LIKE '"'"'%zz12%'"'"'',
            "DELETE FROM rows WHERE id LIKE '%zz12%'",
            "DELETE FROM tables WHERE id LIKE '%zz12%'",
            "DELETE FROM imports WHERE id LIKE '%zz12%'",
            "DELETE FROM member_roles WHERE member_id LIKE '%zz12%'",
            "DELETE FROM roles WHERE id LIKE '%zz12%'",
        ):
            await c.execute(text(stmt))
    await eng.dispose()


@pytest.fixture(autouse=True)
def handlers(monkeypatch):
    saved = dict(HANDLERS)
    register("table.create")(h_table_create)
    register("row.insert")(h_row_insert)
    register("row.update")(h_row_update)
    register("role.create")(h_role_create)
    register("row.move")(h_row_delete_refs)
    calls.clear()
    reembeds: list[tuple[str, str]] = []

    async def fake_enqueue(kind, id_):
        reembeds.append((kind, id_))

    monkeypatch.setattr(pipeline, "enqueue_reembed", fake_enqueue)
    monkeypatch.setattr("app.ops.handlers._loaded", True)  # keine Fach-Handler aus anderen Branches nachladen
    yield reembeds
    HANDLERS.clear()
    HANDLERS.update(saved)


async def q(engine, sql, **params):
    async with engine.connect() as c:
        return (await c.execute(text(sql), params)).mappings().all()


# ── Mehrere Ops, ganz oder gar nicht ─────────────────────────────────────────


async def test_multi_op_batch_with_keys_results_oplog_and_inverse(engine):
    tbl = new_table(key="zz12_best", cols=("name", "menge"))
    rid = zid("row")
    b = batch(tbl, {"op": "row.insert", "table": "zz12_best", "rows": [
        {"id": rid, "values": {"name": "Schraube", "menge": 5}}]})
    result = await pipeline.apply_batch(b, ANNA)

    assert set(result.seq) == {"workspace", f"table:{tbl['id']}"}
    assert result.results["0"] == {"id": tbl["id"]}
    assert result.results["1"] == {"ids": [rid]}
    col_ids = {c["key"]: c["id"] for c in tbl["columns"]}
    row = (await q(engine, "SELECT values, version FROM rows WHERE id = :i", i=rid))[0]
    assert row["values"] == {col_ids["name"]: "Schraube", col_ids["menge"]: 5}  # Spalten-Keys wurden zu IDs
    assert row["version"] == 1  # neu angelegt: keine Erhöhung

    log = await q(engine, "SELECT channel, seq, ops, inverse, actor FROM oplog WHERE batch_id = :b", b=b.batch_id)
    assert {r["channel"] for r in log} == set(result.seq)
    entry = log[0]
    assert entry["ops"][1]["table"] == tbl["id"]  # aufgelöste IDs im Log
    assert [i["op"] for i in entry["inverse"]] == ["row.delete", "table.delete"]  # umgekehrte Reihenfolge
    assert entry["actor"]["id"] == ANNA.id
    assert calls == ["table.create", "row.insert"]


async def test_batch_is_all_or_nothing(engine):
    tbl = new_table()
    before = await q(engine, "SELECT id, seq FROM channels WHERE id LIKE '%zz12%'")
    b = batch(tbl, {"op": "row.update", "table": tbl["id"], "row": zid("row"), "values": {}})
    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(b, ANNA)
    assert e.value.error.code == "NOT_FOUND"
    assert await q(engine, "SELECT 1 FROM tables WHERE id = :i", i=tbl["id"]) == []
    assert await q(engine, "SELECT 1 FROM batches WHERE batch_id = :b", b=b.batch_id) == []
    assert await q(engine, "SELECT 1 FROM oplog WHERE batch_id = :b", b=b.batch_id) == []
    assert await q(engine, "SELECT id, seq FROM channels WHERE id LIKE '%zz12%'") == before  # seq nicht verbraucht


async def test_database_integrity_error_becomes_validation_and_rolls_back(engine):
    tid = zid("tbl")
    first = batch(new_table(tid=tid))
    await pipeline.apply_batch(first, ANNA)
    role_id = zid("rol")
    again = batch(new_table(tid=tid), {"op": "role.create", "id": role_id, "key": zid("r"), "name": "R"})
    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(again, ANNA)
    assert e.value.error.code == "VALIDATION"
    assert await q(engine, "SELECT 1 FROM roles WHERE id = :i", i=role_id) == []


async def test_unknown_handler_is_rejected(engine):
    del HANDLERS["row.insert"]
    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(batch({"op": "row.insert", "table": "tbl_x", "rows": []}), ANNA)
    assert e.value.error.code in {"VALIDATION", "NOT_FOUND"}


# ── Idempotenz ───────────────────────────────────────────────────────────────


async def test_repeat_with_same_batch_id_returns_first_result(engine, handlers):
    b = batch(new_table())
    first = await pipeline.apply_batch(b, ANNA)
    second = await pipeline.apply_batch(b, ANNA)
    assert second == first
    assert calls == ["table.create"]  # Handler lief nur einmal
    assert len(await q(engine, "SELECT 1 FROM oplog WHERE batch_id = :b", b=b.batch_id)) == len(first.seq)
    assert handlers == [("table", b.ops[0].id)]  # auch die Neu-Einbettung nur einmal


async def test_parallel_attempts_with_same_batch_id_apply_once(engine):
    tbl = new_table()
    b = batch(tbl, {"op": "row.insert", "table": tbl["id"], "rows": [{"id": zid("row"), "values": {"name": "x"}}]})
    results = await asyncio.gather(*(pipeline.apply_batch(b, ANNA) for _ in range(5)))
    assert all(r == results[0] for r in results)
    assert calls.count("table.create") == 1
    assert (await q(engine, "SELECT seq FROM channels WHERE id = :c", c=f"table:{tbl['id']}"))[0]["seq"] == 1


async def test_seq_is_gapless_for_concurrent_batches_on_one_channel(engine):
    tbl = new_table()
    await pipeline.apply_batch(batch(tbl), ANNA)
    rid = zid("row")
    await pipeline.apply_batch(batch({"op": "row.insert", "table": tbl["id"], "rows": [
        {"id": rid, "values": {"name": "a"}}]}), ANNA)
    col = tbl["columns"][0]["id"]
    results = await asyncio.gather(*(pipeline.apply_batch(batch(
        {"op": "row.update", "table": tbl["id"], "row": rid, "values": {col: str(n)}}), ANNA) for n in range(8)))
    seqs = sorted(r.seq[f"table:{tbl['id']}"] for r in results)
    assert seqs == list(range(3, 11))
    rows = await q(engine, "SELECT seq FROM oplog WHERE channel = :c ORDER BY seq", c=f"table:{tbl['id']}")
    assert [r["seq"] for r in rows] == list(range(1, 11))


# ── Versionen ────────────────────────────────────────────────────────────────


async def test_stale_base_version_conflicts_and_changes_nothing(engine):
    tbl = new_table()
    rid = zid("row")
    col = tbl["columns"][0]["id"]
    await pipeline.apply_batch(batch(tbl, {"op": "row.insert", "table": tbl["id"], "rows": [
        {"id": rid, "values": {"name": "a"}}]}), ANNA)
    update = {"op": "row.update", "table": tbl["id"], "row": rid, "values": {col: "b"}}
    await pipeline.apply_batch(batch(update, base={rid: 1}), ANNA)  # aktuell: passt, danach Version 2
    assert (await q(engine, "SELECT version FROM rows WHERE id = :i", i=rid))[0]["version"] == 2

    stale = batch(update, base={rid: 1})
    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(stale, ANNA)
    err = e.value.error
    assert err.code == "CONFLICT" and err.details["versions"][rid] == {"expected": 1, "current": 2}
    assert e.value.status_code == 409
    assert (await q(engine, "SELECT version FROM rows WHERE id = :i", i=rid))[0]["version"] == 2


async def test_version_is_bumped_once_per_batch(engine):
    tbl = new_table()
    rid = zid("row")
    col = tbl["columns"][0]["id"]
    await pipeline.apply_batch(batch(tbl, {"op": "row.insert", "table": tbl["id"], "rows": [
        {"id": rid, "values": {"name": "a"}}]}), ANNA)
    two = [{"op": "row.update", "table": tbl["id"], "row": rid, "values": {col: v}} for v in ("x", "y")]
    await pipeline.apply_batch(batch(*two), ANNA)
    assert (await q(engine, "SELECT version FROM rows WHERE id = :i", i=rid))[0]["version"] == 2
    assert (await q(engine, "SELECT version FROM tables WHERE id = :i", i=tbl["id"]))[0]["version"] == 1


async def test_unknown_base_object_is_not_found(engine):
    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(batch(new_table(), base={"row_zz12nope": 1}), ANNA)
    assert e.value.error.code == "NOT_FOUND"


# ── Rechte ───────────────────────────────────────────────────────────────────


async def test_missing_role_is_forbidden_and_writes_nothing(engine):
    tbl = new_table()
    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(batch(tbl), BEN)
    assert e.value.error.code == "FORBIDDEN" and e.value.status_code == 403
    assert await q(engine, "SELECT 1 FROM tables WHERE id = :i", i=tbl["id"]) == []


async def test_permission_is_checked_for_every_op_before_anything_runs(engine):
    # Ben darf Zeilen ändern, aber kein Schema: der zweite Op lehnt den ganzen Batch ab, bevor der erste läuft.
    tbl = new_table()
    b = batch({"op": "row.update", "table": "tbl_zz12x", "row": "row_zz12x", "values": {}}, tbl)
    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(b, BEN)
    assert e.value.error.code == "FORBIDDEN" and calls == []


async def test_forbidden_beats_conflict_and_text_edit_is_privileged(engine):
    b = batch({"op": "text.edit", "block": "blk_zz12x", "from": 0, "to": 0, "insert": "x", "version": 1}, base={"row_zz12y": 9})
    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(b, BEN)
    assert e.value.error.code == "FORBIDDEN"


async def test_rows_are_open_to_every_user(engine):
    tbl = new_table()
    await pipeline.apply_batch(batch(tbl), ANNA)
    rid = zid("row")
    await pipeline.apply_batch(batch({"op": "row.insert", "table": tbl["id"], "rows": [
        {"id": rid, "values": {"name": "von Ben"}}]}), BEN)
    assert await q(engine, "SELECT 1 FROM rows WHERE id = :i", i=rid)


async def test_roles_come_from_db_and_agents_act_on_behalf(engine):
    role, user = zid("rol"), zid("usr")
    async with engine.begin() as c:
        await c.execute(text("INSERT INTO roles (id, workspace_id, key, name) VALUES (:i, 'ws_demo', 'einkauf_zz12', 'x')"),
                        {"i": role})
    # Rolle mit anderem Key als `einkauf` reicht nicht
    async with engine.begin() as c:
        await c.execute(text("INSERT INTO member_roles (workspace_id, member_id, role_id) VALUES ('ws_demo', :m, :r)"),
                        {"m": user, "r": role})
    with pytest.raises(PipelineError):
        await pipeline.apply_batch(batch(new_table()), Actor(type="user", id=user))
    # Agent im Auftrag von Anna: Rechte der Person; Agent mit eigener Identität ohne Rollen: nein
    on_behalf = Actor(type="agent", id="agt_zz12", on_behalf_of=ANNA.id)
    await pipeline.apply_batch(batch(new_table()), on_behalf)
    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(batch(new_table()), Actor(type="agent", id="agt_zz12"))
    assert e.value.error.code == "FORBIDDEN"
    await pipeline.apply_batch(batch(new_table()), Actor(type="system", id="workflow"))  # System darf


# ── Referenz-Index ───────────────────────────────────────────────────────────


async def test_reference_index_is_replaced_per_source_and_usages_overlay(engine):
    tbl = new_table()
    await pipeline.apply_batch(batch(tbl), ANNA)
    assert await q(engine, 'SELECT via FROM "references" WHERE source_id = :s', s=tbl["id"]) == [
        {"via": "step.assignee"}]
    blk = zid("blk")
    for target in (zid("tbl"), zid("tbl")):
        await pipeline.apply_batch(batch({"op": "row.move", "table": target, "row": blk}), ANNA)
    rows = await q(engine, 'SELECT target_id FROM "references" WHERE source_id = :s', s=blk)
    assert len(rows) == 1 and rows[0]["target_id"] == target  # alte Kante ersetzt, nicht ergänzt

    async with pipeline.SessionLocal() as s:
        ctx = OpContext(s, ANNA)
        assert [u["source_id"] for u in await references.usages(ctx, "table", target)] == [blk]
        ctx.set_references("block", blk, [])  # im selben Batch entfernt
        assert await references.usages(ctx, "table", target) == []


# ── NOTIFY und Neu-Einbettung erst nach Commit ───────────────────────────────


async def test_notify_only_for_committed_batches(engine):
    conn = await asyncpg.connect(DB_URL.replace("+asyncpg", ""))
    received: list[dict] = []
    await conn.add_listener("ops", lambda *a: received.append(json.loads(a[3])))
    try:
        tbl = new_table()
        with pytest.raises(PipelineError):
            await pipeline.apply_batch(batch(tbl, {"op": "row.update", "table": tbl["id"], "row": "row_zz12x",
                                                   "values": {}}), ANNA)
        await asyncio.sleep(0.2)
        assert [m for m in received if "zz12" in m["channel"]] == []
        ok = await pipeline.apply_batch(batch(tbl), ANNA)
        await asyncio.sleep(0.2)
    finally:
        await conn.close()
    assert {(m["channel"], m["seq"]) for m in received if "zz12" in m["channel"]} == {
        (f"table:{tbl['id']}", ok.seq[f"table:{tbl['id']}"])}


async def test_reembed_enqueued_after_commit_only(engine, handlers):
    tbl = new_table()
    with pytest.raises(PipelineError):
        await pipeline.apply_batch(batch(tbl, {"op": "row.update", "table": tbl["id"], "row": "row_zz12x",
                                               "values": {}}), ANNA)
    assert handlers == []
    await pipeline.apply_batch(batch(tbl), ANNA)
    assert handlers == [("table", tbl["id"])]


async def test_reembed_failure_does_not_fail_committed_batch(engine, monkeypatch):
    async def broken(kind, id_):
        raise RuntimeError("queue down")

    monkeypatch.setattr(pipeline, "enqueue_reembed", broken)
    tbl = new_table()
    result = await pipeline.apply_batch(batch(tbl), ANNA)
    assert result.results["0"]["id"] == tbl["id"]
    assert await q(engine, "SELECT 1 FROM tables WHERE id = :i", i=tbl["id"])


# ── import.include ───────────────────────────────────────────────────────────


async def _prepare_import(engine, ops, actor=ANNA, hours_ago=0):
    imp = zid("imp")
    async with engine.begin() as c:
        await c.execute(text("""INSERT INTO imports (id, workspace_id, actor, source, ops, created, created_at)
                                VALUES (:i, 'ws_demo', CAST(:a AS jsonb), 'xlsx', CAST(:o AS jsonb), '{}',
                                        now() - make_interval(hours => :h))"""),
                        {"i": imp, "a": json.dumps(actor.model_dump(exclude_none=True)),
                         "o": json.dumps(ops), "h": hours_ago})
    return imp


async def test_import_include_expands_and_is_used_once(engine):
    imported = new_table(key="zz12_imp")
    imp = await _prepare_import(engine, [imported])
    extra = {"op": "row.insert", "table": "zz12_imp", "rows": [{"id": zid("row"), "values": {"name": "n"}}]}
    result = await pipeline.apply_batch(batch({"op": "import.include", "import_id": imp}, extra), ANNA)
    assert result.results["0"] == {"included": 1}
    assert result.results["1"]["ids"]  # Ergebnis-Index bezieht sich auf den gesendeten Batch
    assert await q(engine, "SELECT 1 FROM tables WHERE id = :i", i=imported["id"])
    ops_logged = (await q(engine, "SELECT ops FROM oplog WHERE batch_id = :b LIMIT 1", b=result.batch_id))[0]["ops"]
    assert [o["op"] for o in ops_logged] == ["table.create", "row.insert"]  # expandiert im Log

    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(batch({"op": "import.include", "import_id": imp}), ANNA)
    assert e.value.error.code == "IMPORT_USED"


async def test_import_include_errors_roll_back_and_keep_import_unused(engine):
    imp = await _prepare_import(engine, [new_table(), {"op": "row.update", "table": "tbl_zz12x", "row": "row_zz12x",
                                                       "values": {}}])
    with pytest.raises(PipelineError):
        await pipeline.apply_batch(batch({"op": "import.include", "import_id": imp}), ANNA)  # zweite Op scheitert
    assert (await q(engine, "SELECT used_at FROM imports WHERE id = :i", i=imp))[0]["used_at"] is None
    assert await q(engine, "SELECT 1 FROM tables WHERE id LIKE '%zz12%'") == []


async def test_import_include_checks_permission_owner_and_expiry(engine):
    imp = await _prepare_import(engine, [new_table()], actor=BEN)
    with pytest.raises(PipelineError) as e:  # Rechte der enthaltenen Ops gelten (L 8.3)
        await pipeline.apply_batch(batch({"op": "import.include", "import_id": imp}), BEN)
    assert e.value.error.code == "FORBIDDEN"
    with pytest.raises(PipelineError) as e:  # fremder Import
        await pipeline.apply_batch(batch({"op": "import.include", "import_id": imp}), ANNA)
    assert e.value.error.code == "FORBIDDEN"
    old = await _prepare_import(engine, [new_table()], hours_ago=2)
    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(batch({"op": "import.include", "import_id": old}), ANNA)
    assert e.value.error.code == "IMPORT_INVALID"
    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(batch({"op": "import.include", "import_id": "imp_zz12missing"}), ANNA)
    assert e.value.error.code == "IMPORT_INVALID"


# ── Keys ─────────────────────────────────────────────────────────────────────


async def test_keys_resolve_roles_and_unknown_keys_are_not_found(engine):
    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(batch({"op": "row.insert", "table": "zz12_gibtsnicht", "rows": []}), ANNA)
    assert e.value.error.code == "NOT_FOUND"
    tbl = new_table(cols=("a",))
    with pytest.raises(PipelineError) as e:
        await pipeline.apply_batch(batch(tbl, {"op": "row.insert", "table": tbl["key"], "rows": [
            {"id": zid("row"), "values": {"unbekannt": 1}}]}), ANNA)
    assert e.value.error.code == "NOT_FOUND"


async def test_column_add_resolves_table_key_before_remembering_column(engine):
    from app.ops.handlers import register as reg

    seen = []

    async def column_add(ctx, op):
        seen.append(op)

    reg("column.add")(column_add)
    tbl = new_table(key="zz12_ca")
    col = {"id": zid("col"), "key": "neu", "name": "Neu", "type": {"kind": "text"}}
    row = {"id": zid("row"), "values": {"neu": "x"}}
    await pipeline.apply_batch(batch(tbl, {"op": "column.add", "table": "zz12_ca", "column": col},
                                     {"op": "row.insert", "table": "zz12_ca", "rows": [row]}), ANNA)
    assert seen[0].table == tbl["id"]
    assert list((await q(engine, "SELECT values FROM rows WHERE id = :i", i=row["id"]))[0]["values"]) == [col["id"]]


# ── REST ─────────────────────────────────────────────────────────────────────


async def test_rest_endpoint_maps_pipeline_errors(engine):
    import httpx

    from app.auth import CurrentUser, current_user
    from app.main import app

    users = {"anna": CurrentUser(id=ANNA.id, name="Anna", email="anna@zz12.local", roles=["einkauf"]),
             "ben": CurrentUser(id=BEN.id, name="Ben", email="ben@zz12.local", roles=["mitarbeiter"])}
    active = ["anna"]
    app.dependency_overrides[current_user] = lambda: users[active[0]]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        tbl = new_table()
        ok = await client.post("/api/ops", json=batch(tbl).model_dump(mode="json"))
        assert ok.status_code == 200 and ok.json()["results"]["0"]["id"] == tbl["id"]

        active[0] = "ben"
        forbidden = await client.post("/api/ops",
                                      json=batch(new_table(), batch_id="zz12_rest_forbidden").model_dump(mode="json"))
        assert forbidden.status_code == 403
        body = forbidden.json()
        assert body["batch_id"] == "zz12_rest_forbidden" and body["error"]["code"] == "FORBIDDEN"

        active[0] = "anna"
        conflict = await client.post("/api/ops", json=batch(
            {"op": "row.update", "table": tbl["id"], "row": "row_zz12x", "values": {}},
            base={tbl["id"]: 99}).model_dump(mode="json"))
        assert conflict.status_code == 409 and conflict.json()["error"]["details"]["versions"]
    app.dependency_overrides.pop(current_user, None)
