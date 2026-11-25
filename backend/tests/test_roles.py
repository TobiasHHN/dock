"""Rollen-Ops (Task 1.1): role.create/update/delete, user.set_roles, agent.set_roles durch die echte Pipeline.

Läuft gegen Postgres (Standard: Host-Port 5433, überschreibbar mit TEST_DATABASE_URL). Alle Testdaten tragen
den Marker `zz11r` und werden nach jedem Test entfernt.
"""
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
from app.schemas.common import Actor
from app.schemas.ops import OpBatch

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock")
ANNA = Actor(type="user", id="usr_zz11ranna", name="Anna")  # Rolle einkauf
BEN = Actor(type="user", id="usr_zz11rben", name="Ben")  # Rolle mitarbeiter
AGENT = "agt_zz11rhelfer"


def zid(prefix: str) -> str:
    return f"{prefix}_zz11r{uuid.uuid4().hex[:8]}"


def key() -> str:
    return f"zz11r{uuid.uuid4().hex[:8]}"


async def run(*ops, actor=ANNA):
    batch = OpBatch.model_validate({"batch_id": zid("b"), "base": {}, "ops": list(ops)})
    return await pipeline.apply_batch(batch, actor)


async def expect_error(code, *ops, actor=ANNA) -> PipelineError:
    with pytest.raises(PipelineError) as exc:
        await run(*ops, actor=actor)
    assert exc.value.error.code == code, exc.value.error
    return exc.value


async def q(engine, sql, **params):
    async with engine.connect() as c:
        return (await c.execute(text(sql), params)).mappings().all()


async def role_keys(engine, member):
    rows = await q(engine, """SELECT r.key FROM member_roles mr JOIN roles r ON r.id = mr.role_id
                              WHERE mr.member_id = :m""", m=member)
    return {r["key"] for r in rows}


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
        for actor in (ANNA, BEN):
            await c.execute(text("INSERT INTO users (id, name, email) VALUES (:i, :n, :e) ON CONFLICT DO NOTHING"),
                            {"i": actor.id, "n": actor.name, "e": f"{actor.id}@zz11r.local"})
        await c.execute(text("""INSERT INTO agents (id, workspace_id, name) VALUES (:i, 'ws_demo', 'Helfer')
                                ON CONFLICT DO NOTHING"""), {"i": AGENT})
        for member, role in ((ANNA.id, "einkauf"), (BEN.id, "mitarbeiter")):
            await c.execute(text("""INSERT INTO roles (id, workspace_id, key, name) VALUES (:i, 'ws_demo', :k, :k)
                                    ON CONFLICT (workspace_id, key) DO NOTHING"""), {"i": f"rol_zz11r{role}", "k": role})
            await c.execute(text("""INSERT INTO member_roles (workspace_id, member_id, role_id)
                                    SELECT 'ws_demo', :m, id FROM roles WHERE workspace_id = 'ws_demo' AND key = :k
                                    ON CONFLICT DO NOTHING"""), {"m": member, "k": role})
    yield eng
    async with eng.begin() as c:
        for stmt in (
            "DELETE FROM oplog WHERE batch_id LIKE '%zz11r%'",
            "DELETE FROM batches WHERE batch_id LIKE '%zz11r%'",
            "DELETE FROM channels WHERE id LIKE '%zz11r%'",
            'DELETE FROM "references" WHERE source_id LIKE \'%zz11r%\' OR target_id LIKE \'%zz11r%\'',
            "DELETE FROM member_roles WHERE member_id LIKE '%zz11r%' OR role_id LIKE '%zz11r%'",
            "DELETE FROM roles WHERE id LIKE '%zz11r%' OR key LIKE 'zz11r%'",
            "DELETE FROM agents WHERE id LIKE '%zz11r%'",
            "DELETE FROM users WHERE id LIKE '%zz11r%'",
        ):
            await c.execute(text(stmt))
    await eng.dispose()


async def test_create_role_and_assign_by_key_in_one_batch(engine):
    rid, k = zid("rol"), key()
    result = await run({"op": "role.create", "id": rid, "key": k, "name": "Teamleitung"},
                       {"op": "user.set_roles", "user": BEN.id, "add": [k]})
    assert result.results["0"] == {"id": rid}
    assert rid in result.results["1"]["roles"]  # Rollen-IDs (L 5.8)
    assert await role_keys(engine, BEN.id) == {"mitarbeiter", k}
    assert "workspace" in result.seq and f"user:{BEN.id}" in result.seq

    entry = (await q(engine, "SELECT inverse FROM oplog WHERE batch_id = :b AND channel = 'workspace'",
                     b=result.batch_id))[0]
    inverse = entry["inverse"] if isinstance(entry["inverse"], list) else json.loads(entry["inverse"])
    assert inverse == [{"op": "user.set_roles", "user": BEN.id, "add": [], "remove": [rid]},
                       {"op": "role.delete", "role": rid}]


async def test_role_change_takes_effect_on_next_batch(engine):
    """L 5.8: Rollen werden beim Handeln geprüft. Ben bekommt `einkauf` und darf danach Rollen anlegen."""
    await expect_error("FORBIDDEN", {"op": "role.create", "id": zid("rol"), "key": key(), "name": "X"}, actor=BEN)
    await run({"op": "user.set_roles", "user": BEN.id, "add": ["einkauf"]})
    await run({"op": "role.create", "id": zid("rol"), "key": key(), "name": "X"}, actor=BEN)
    await run({"op": "user.set_roles", "user": BEN.id, "remove": ["einkauf"]})
    assert await role_keys(engine, BEN.id) == {"mitarbeiter"}
    await expect_error("FORBIDDEN", {"op": "role.create", "id": zid("rol"), "key": key(), "name": "X"}, actor=BEN)


async def test_role_validation_errors(engine):
    k = key()
    await run({"op": "role.create", "id": zid("rol"), "key": k, "name": "A"})
    err = await expect_error("VALIDATION", {"op": "role.create", "id": zid("rol"), "key": k, "name": "B"})
    assert err.error.details["errors"]["key"] == "bereits vergeben"
    for bad in ("rol_x", "Gross", "1abc", ""):
        await expect_error("VALIDATION", {"op": "role.create", "id": zid("rol"), "key": bad, "name": "B"})
    await expect_error("VALIDATION", {"op": "role.create", "id": zid("rol"), "key": key(), "name": "  "})
    await expect_error("VALIDATION", {"op": "role.create", "id": "x_zz11r", "key": key(), "name": "B"})
    # Fehler im zweiten Op: nichts vom Batch bleibt
    rid = zid("rol")
    await expect_error("VALIDATION", {"op": "role.create", "id": rid, "key": key(), "name": "C"},
                       {"op": "role.create", "id": zid("rol"), "key": k, "name": "D"})
    assert not await q(engine, "SELECT 1 FROM roles WHERE id = :i", i=rid)


async def test_role_update_renames_key_and_name(engine):
    rid, k, k2 = zid("rol"), key(), key()
    await run({"op": "role.create", "id": rid, "key": k, "name": "Alt"})
    await run({"op": "role.update", "role": k, "key": k2, "name": "Neu"})
    assert (await q(engine, "SELECT key, name FROM roles WHERE id = :i", i=rid))[0] == {"key": k2, "name": "Neu"}
    await run({"op": "user.set_roles", "user": BEN.id, "add": [k2]})  # neuer Key löst auf
    await expect_error("NOT_FOUND", {"op": "user.set_roles", "user": BEN.id, "add": [k]})
    other = key()
    await run({"op": "role.create", "id": zid("rol"), "key": other, "name": "O"})
    await expect_error("VALIDATION", {"op": "role.update", "role": rid, "key": other})


async def test_role_delete_protected_by_members_and_references(engine):
    rid, k = zid("rol"), key()
    await run({"op": "role.create", "id": rid, "key": k, "name": "Teamleitung"},
              {"op": "user.set_roles", "user": BEN.id, "add": [rid]})
    err = await expect_error("IN_USE", {"op": "role.delete", "role": rid})
    assert err.error.details["members"] == [BEN.id]

    await run({"op": "user.set_roles", "user": BEN.id, "remove": [rid]})
    async with engine.begin() as c:
        await c.execute(text("""INSERT INTO "references" (source_kind, source_id, target_kind, target_id, via)
                                VALUES ('workflow', 'wf_zz11r', 'role', :r, 'step.assignee')"""), {"r": rid})
    err = await expect_error("IN_USE", {"op": "role.delete", "role": rid})
    assert "wf_zz11r" in err.error.message and err.error.details["members"] == []

    async with engine.begin() as c:
        await c.execute(text("""DELETE FROM "references" WHERE source_id = 'wf_zz11r'"""))
    await run({"op": "role.delete", "role": k})
    assert not await q(engine, "SELECT 1 FROM roles WHERE id = :i", i=rid)


async def test_set_roles_for_agents_and_unknown_members(engine):
    k = key()
    await run({"op": "role.create", "id": zid("rol"), "key": k, "name": "Assistent"})
    result = await run({"op": "agent.set_roles", "agent": AGENT, "add": [k]})
    assert result.results["0"]["roles"] and await role_keys(engine, AGENT) == {k}
    # Idempotent: nochmal hinzufügen ändert nichts und erzeugt keine inverse Op
    again = await run({"op": "agent.set_roles", "agent": AGENT, "add": [k]})
    entry = (await q(engine, "SELECT inverse FROM oplog WHERE batch_id = :b", b=again.batch_id))[0]
    assert (entry["inverse"] if isinstance(entry["inverse"], list) else json.loads(entry["inverse"])) == []

    await expect_error("NOT_FOUND", {"op": "agent.set_roles", "agent": "agt_zz11rnope", "add": [k]})
    await expect_error("NOT_FOUND", {"op": "user.set_roles", "user": "usr_zz11rnope", "add": [k]})
    await expect_error("NOT_FOUND", {"op": "user.set_roles", "user": BEN.id, "add": ["gibtsnicht"]})
    await expect_error("VALIDATION", {"op": "user.set_roles", "user": BEN.id, "add": [k], "remove": [k]})
