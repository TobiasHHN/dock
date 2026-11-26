"""Demo-Fallback (Task 5.6): `demo/fallback.py` legt aus den Demo-Dateien und `demo/fallback_batch.json` den
kompletten Bestellprozess an, `validate_workflow` ist ohne Fehler.

Läuft im Modus `--direct` gegen Postgres (Host-Port 5433). Alle IDs und Keys bekommen den Marker `zz56`, damit der
Test neben echten Demo-Daten läuft; danach wird alles entfernt."""
import importlib.util
import json
import os
import re
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.ops import pipeline
from app.schemas.common import Actor

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock")
PATH = Path(__file__).resolve().parents[2] / "demo" / "fallback.py"
ANNA = Actor(type="user", id="usr_zz56anna", name="Anna zz56")


def _load():
    spec = importlib.util.spec_from_file_location("demo_fallback", PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["demo_fallback"] = mod
    spec.loader.exec_module(mod)
    return mod


fallback = _load()


def tagged(tag: str) -> tuple[dict, callable]:
    """Template und Import-Ops mit eindeutigen IDs (`<präfix>_zz56<tag>…`) und Keys."""
    ids = re.compile(r'"(wf|tbl|doc|col|blk|row)_(?!zz56)')

    def retag_json(obj):
        return json.loads(ids.sub(rf'"\1_zz56{tag}', json.dumps(obj)))

    template = retag_json(json.loads(fallback.TEMPLATE.read_text()))
    template["batch_id"] = f"b_zz56{tag}"
    for op in template["ops"]:
        if op["op"] in ("workflow.create", "table.create"):
            op["key"] = f"zz56{op['key']}{tag}"

    def retag(ops: list, created: dict) -> None:
        new_ops, new_created = retag_json(ops), retag_json(created)
        for op in new_ops:
            if op["op"] == "table.create":
                op["key"] = f"zz56{op['key']}{tag}"
        for t in new_created.get("tables", []):
            t["key"] = f"zz56{t['key']}{tag}"
        ops[:] = new_ops
        created.clear()
        created.update(new_created)

    return template, retag


@pytest_asyncio.fixture
async def engine(monkeypatch):
    eng = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with eng.connect() as c:
            await c.execute(text("SELECT 1 FROM imports LIMIT 1"))
    except Exception:
        pytest.skip("Postgres nicht erreichbar")

    async def no_reembed(*_):
        return None

    monkeypatch.setattr(pipeline, "enqueue_reembed", no_reembed)
    async with eng.begin() as c:
        await c.execute(text("INSERT INTO workspaces (id, name) VALUES ('ws_demo', 'Demo') ON CONFLICT DO NOTHING"))
        for key in ("einkauf", "chef"):
            await c.execute(text("""INSERT INTO roles (id, workspace_id, key, name) VALUES (:i, 'ws_demo', :k, :k)
                                    ON CONFLICT (workspace_id, key) DO NOTHING"""), {"i": f"rol_zz56{key}", "k": key})
        await c.execute(text("""INSERT INTO member_roles (workspace_id, member_id, role_id)
                                SELECT 'ws_demo', :m, id FROM roles WHERE workspace_id = 'ws_demo' AND key = 'einkauf'
                                ON CONFLICT DO NOTHING"""), {"m": ANNA.id})
    yield eng
    async with eng.begin() as c:
        for stmt in (
            "DELETE FROM oplog WHERE batch_id LIKE '%zz56%'",
            "DELETE FROM batches WHERE batch_id LIKE '%zz56%'",
            "DELETE FROM channels WHERE id LIKE '%zz56%'",
            'DELETE FROM "references" WHERE source_id LIKE \'%zz56%\' OR target_id LIKE \'%zz56%\'',
            "DELETE FROM workflow_versions WHERE workflow_id LIKE '%zz56%'",
            "DELETE FROM workflows WHERE id LIKE '%zz56%'",
            "DELETE FROM blocks WHERE doc_id LIKE '%zz56%'",
            "DELETE FROM documents WHERE id LIKE '%zz56%'",
            "DELETE FROM rows WHERE table_id LIKE '%zz56%'",
            "DELETE FROM tables WHERE id LIKE '%zz56%'",
            f"DELETE FROM imports WHERE actor ->> 'id' = '{ANNA.id}'",
            "DELETE FROM member_roles WHERE member_id LIKE '%zz56%' OR role_id LIKE '%zz56%'",
            "DELETE FROM roles WHERE id LIKE '%zz56%'",
        ):
            await c.execute(text(stmt))
    await eng.dispose()


async def q(engine, sql, **params):
    async with engine.connect() as c:
        return (await c.execute(text(sql), params)).mappings().all()


def test_template_placeholders_are_all_filled():
    """Jeder Platzhalter im Batch wird von den echten Import-Plänen belegt (ohne DB)."""
    from app.imports.docx import parse_docx
    from app.imports.xlsx import parse_xlsx

    x, d = parse_xlsx(fallback.XLSX.read_bytes()), parse_docx(fallback.DOCX.read_bytes(), owner=fallback.DOCX_OWNER)
    batch = fallback.build_batch({"import_id": "imp_x", "created": x.created}, {"import_id": "imp_d", "created": d.created})
    assert not re.search(r'"\$[a-z]', json.dumps(batch))
    assert [o["op"] for o in batch["ops"]].count("import.include") == 2
    assert batch["ops"][-1] == {"op": "workflow.publish", "workflow": "wf_best"}
    with pytest.raises(fallback.FallbackError):
        fallback.fill({"x": "$col.gibtsnicht"}, {})


async def test_fallback_creates_tables_workflow_and_documents(engine):
    tag = uuid.uuid4().hex[:6]
    template, retag = tagged(tag)
    out = await fallback.run_direct(False, DB_URL, ANNA, template, retag)

    assert fallback.errors_of(out["validation"]) == [], out["validation"]
    ops = out["batch"]["ops"]
    published = out["result"]["results"][str(len(ops) - 1)]
    assert published["version"] == 1
    wf_id = published["workflow"]

    best_key, art_key = f"zz56bestellungen{tag}", f"zz56artikel{tag}"
    tables = {r["key"]: r for r in await q(engine, "SELECT id, key FROM tables WHERE key IN (:a, :b)",
                                           a=best_key, b=art_key)}
    assert set(tables) == {best_key, art_key}
    best = tables[best_key]["id"]
    cols = {r["key"] for r in await q(engine, "SELECT key FROM columns WHERE table_id = :t", t=best)}
    assert {"name", "kostenstelle", "bestelldatum", "gesamtbetrag", "status", "besteller", "genehmigt_von",
            "kommentar", "lieferanten_nr", "liefertermin", "run", "bemerkung"} <= cols
    assert len(await q(engine, "SELECT id FROM rows WHERE table_id = :t", t=best)) == 3  # Beispielanträge aus Excel

    docs = await q(engine, "SELECT id, title, owner_step FROM documents WHERE id LIKE :p OR owner_workflow = :w",
                   p=f"%zz56{tag}%", w=wf_id)
    steps = {d["owner_step"]: d for d in docs}
    assert {"erfassen", "genehmigung", "bestellung", None} <= set(steps)
    assert steps["erfassen"]["title"] == "Bestellformular"  # aus dem Word-Import

    blocks = await q(engine, "SELECT type, props FROM blocks WHERE doc_id = :d", d=steps["erfassen"]["id"])
    form = next(b["props"] for b in blocks if b["type"] == "form")
    assert [a["key"] for a in form["actions"]] == ["order", "items"]
    assert form["buttons"][0]["outcome"] == "submitted"
    items = next(b["props"] for b in blocks if b["type"] == "line_items")
    assert items["key"] == "artikel" and all(c.get("column") for c in items["columns"])

    version = (await q(engine, "SELECT documents FROM workflow_versions WHERE workflow_id = :w AND version = 1",
                       w=wf_id))[0]
    assert len(version["documents"]) == 3

    # Regression: Spalten mit String-Default ("eingereicht", "{{user.id}}") ließen list_tables mit 500 scheitern
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.domain import queries
    async with AsyncSession(engine) as s:
        table = await queries.fetch_table(s, best)
    defaults = {c["key"]: c["default"] for c in table["columns"]}
    assert defaults["status"] == "eingereicht" and defaults["besteller"] == "{{user.id}}"
