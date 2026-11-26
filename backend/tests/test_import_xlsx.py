"""Excel-Import (Task 3.6): Parser (ohne DB) und `import.include` mit den echten Handlern (Postgres)."""
import datetime as dt
import io
import os
import uuid

import pytest
import pytest_asyncio
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.imports import store
from app.imports.xlsx import ImportFileError, parse_xlsx
from app.ops import pipeline
from app.ops.context import OpContext
from app.ops.errors import PipelineError
from app.schemas.common import Actor
from app.schemas.ops import OpBatch

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock_test")
ANNA = Actor(type="user", id="usr_zz36anna", name="Anna")
TAG = "zz36"


def xlsx_bytes(build) -> bytes:
    wb = Workbook()
    build(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Parser ───────────────────────────────────────────────────────────────────


def test_type_inference_and_keys():
    def build(wb):
        ws = wb.active
        ws.title = "Größe & Co"
        ws.append(["Straße", "Ja?", "Zahl", "Dezimal", "Zeit", "Notiz", "Preis", "Straße"])
        ws.append(["x", True, 1, 1.5, dt.datetime(2026, 1, 2, 10, 30), "a" * 300, 9.5, "y"])
        ws.append(["z", False, 2, 2.0, dt.datetime(2026, 1, 3, 8, 0), "b", 10, "w"])
        for r in (2, 3):
            ws.cell(row=r, column=7).number_format = '#,##0.00 [$USD]'

    res = parse_xlsx(xlsx_bytes(build))
    table = res.ops[0]
    assert table["key"] == "groesse_co"
    types = {c["key"]: c["type"] for c in table["columns"]}
    assert list(types) == ["strasse", "ja", "zahl", "dezimal", "zeit", "notiz", "preis", "strasse_2"]
    assert types["ja"] == {"kind": "boolean"}
    assert types["zahl"] == {"kind": "integer"}
    assert types["dezimal"] == {"kind": "number", "decimals": 2}
    assert types["zeit"] == {"kind": "datetime"}
    assert types["notiz"] == {"kind": "long_text"}
    assert types["preis"] == {"kind": "currency", "currency": "USD"}
    assert res.created["tables"][0]["rows"] == 2


def test_formula_empty_header_and_error_cells_warn():
    def build(wb):
        ws = wb.active
        ws.title = "F"
        ws.append(["A", None, "C"])
        ws.append([1, 2, "=A2*2"])
        ws.append([2, 3, "#DIV/0!"])

    res = parse_xlsx(xlsx_bytes(build))
    joined = " | ".join(res.warnings)
    assert "Formel verloren" in joined and "keinen Spaltenkopf" in joined
    assert [c["key"] for c in res.ops[0]["columns"]] == ["a", "c"]


def test_sheet_selection_and_unknown_sheet():
    def build(wb):
        wb.active.title = "Eins"
        wb.active.append(["a"])
        wb.active.append([1])
        wb.create_sheet("Zwei").append(["b"])
        wb["Zwei"].append([2])

    data = xlsx_bytes(build)
    assert [t["key"] for t in parse_xlsx(data).created["tables"]] == ["eins", "zwei"]
    assert [t["key"] for t in parse_xlsx(data, "Zwei").created["tables"]] == ["zwei"]
    with pytest.raises(ImportFileError, match="Eins, Zwei"):
        parse_xlsx(data, "Drei")


def test_broken_files_give_readable_errors():
    for data, needle in [
        (b"", "leer"),
        (b"das ist keine Excel-Datei", "keine gültige .xlsx"),
        (bytes.fromhex("D0CF11E0A1B11AE1") + b"0" * 100, "passwortgeschützt"),
        (b"PK\x03\x04kaputt", "beschädigt"),
        (b"x" * (10 * 1024 * 1024 + 1), "zu groß"),
    ]:
        with pytest.raises(ImportFileError, match=needle):
            parse_xlsx(data)

    def only_empty(wb):
        wb.active.title = "Leer"

    with pytest.raises(ImportFileError, match="keine importierbaren Daten"):
        parse_xlsx(xlsx_bytes(only_empty))


def test_row_and_column_limits(monkeypatch):
    from app.imports import xlsx

    monkeypatch.setattr(xlsx, "MAX_ROWS", 5)
    monkeypatch.setattr(xlsx, "MAX_COLUMNS", 3)

    def rows(wb):
        wb.active.append(["a"])
        for i in range(6):
            wb.active.append([i])

    def cols(wb):
        wb.active.append(["a", "b", "c", "d"])
        wb.active.append([1, 2, 3, 4])

    with pytest.raises(ImportFileError, match="mehr als 5 Zeilen"):
        parse_xlsx(xlsx_bytes(rows))
    with pytest.raises(ImportFileError, match="mehr als 3 Spalten"):
        parse_xlsx(xlsx_bytes(cols))


def test_large_sheet_is_chunked():
    def build(wb):
        wb.active.append(["n"])
        for i in range(1200):
            wb.active.append([i])

    res = parse_xlsx(xlsx_bytes(build))
    assert [len(o["rows"]) for o in res.ops[1:]] == [500, 500, 200]


# ── import.include mit echten Handlern ───────────────────────────────────────


@pytest_asyncio.fixture
async def engine(monkeypatch):
    eng = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with eng.connect() as c:
            await c.execute(text("SELECT 1 FROM imports LIMIT 1"))
    except Exception:
        pytest.skip("Postgres nicht erreichbar")
    async def no_reembed(*_):  # kein Job-Queue-Zugriff im Test
        return None

    monkeypatch.setattr(pipeline, "enqueue_reembed", no_reembed)
    monkeypatch.setattr(pipeline, "SessionLocal", async_sessionmaker(eng, expire_on_commit=False))
    async with eng.begin() as c:
        await c.execute(text("""INSERT INTO roles (id, workspace_id, key, name) VALUES ('rol_zz36einkauf', 'ws_demo',
                                'einkauf', 'einkauf') ON CONFLICT (workspace_id, key) DO NOTHING"""))
        await c.execute(text("""INSERT INTO member_roles (workspace_id, member_id, role_id)
                                SELECT 'ws_demo', :m, id FROM roles WHERE workspace_id = 'ws_demo' AND key = 'einkauf'
                                ON CONFLICT DO NOTHING"""), {"m": ANNA.id})
    yield eng
    async with eng.begin() as c:
        for stmt in (
            f"DELETE FROM oplog WHERE batch_id LIKE '%{TAG}%'",
            f"DELETE FROM batches WHERE batch_id LIKE '%{TAG}%'",
            f"DELETE FROM channels WHERE id IN (SELECT 'table:' || id FROM tables WHERE key LIKE '{TAG}%')",
            f"DELETE FROM tables WHERE key LIKE '{TAG}%'",
            f"DELETE FROM imports WHERE actor ->> 'id' = '{ANNA.id}'",
            f"DELETE FROM member_roles WHERE member_id = '{ANNA.id}'",
        ):
            await c.execute(text(stmt))
    await eng.dispose()


def sample() -> bytes:
    def build(wb):
        ws = wb.active
        ws.title = f"{TAG}_{uuid.uuid4().hex[:6]}"
        ws.append(["Name", "Menge"])
        ws.append(["a", 1])
        ws.append(["b", 2])

    return xlsx_bytes(build)


async def prepare(engine, data=None):
    result = parse_xlsx(data or sample())
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session, session.begin():
        plan = await store.save_plan(OpContext(session=session, actor=ANNA), "xlsx", result.ops, result.created,
                                     result.warnings)
    return result, plan


def batch(*ops):
    return OpBatch.model_validate({"batch_id": f"b_{TAG}{uuid.uuid4().hex[:8]}", "ops": list(ops)})


async def count(engine, sql, **p):
    async with engine.connect() as c:
        return len((await c.execute(text(sql), p)).all())


async def test_include_with_further_ops_in_one_batch(engine):
    result, plan = await prepare(engine)
    key = result.created["tables"][0]["key"]
    tid = result.created["tables"][0]["id"]
    assert plan.import_id.startswith("imp_") and plan.created == result.created
    extra = {"op": "column.add", "table": key,
             "column": {"id": f"col_{TAG}status", "key": "status", "name": "Status", "type": {"kind": "text"}}}
    res = await pipeline.apply_batch(batch({"op": "import.include", "import_id": plan.import_id}, extra), ANNA)
    assert res.results["0"] == {"included": 2}
    assert await count(engine, "SELECT 1 FROM rows WHERE table_id = :t", t=tid) == 2
    assert await count(engine, "SELECT 1 FROM columns WHERE table_id = :t AND key = 'status'", t=tid) == 1
    with pytest.raises(PipelineError) as e:  # einmalig
        await pipeline.apply_batch(batch({"op": "import.include", "import_id": plan.import_id}), ANNA)
    assert e.value.error.code == "IMPORT_USED"


async def test_failing_batch_leaves_no_half_table(engine):
    result, plan = await prepare(engine)
    key = result.created["tables"][0]["key"]
    tid = result.created["tables"][0]["id"]
    bad = {"op": "column.add", "table": key,
           "column": {"id": f"col_{TAG}dup", "key": "name", "name": "Name", "type": {"kind": "text"}}}  # Key existiert
    with pytest.raises(PipelineError):
        await pipeline.apply_batch(batch({"op": "import.include", "import_id": plan.import_id}, bad), ANNA)
    assert await count(engine, "SELECT 1 FROM tables WHERE key = :k", k=key) == 0
    assert await count(engine, "SELECT 1 FROM rows WHERE table_id = :t", t=tid) == 0
    async with engine.connect() as c:  # Import bleibt unverbraucht und kann korrigiert erneut verwendet werden
        used = (await c.execute(text("SELECT used_at FROM imports WHERE id = :i"), {"i": plan.import_id})).scalar_one()
    assert used is None
    await pipeline.apply_batch(batch({"op": "import.include", "import_id": plan.import_id}), ANNA)
    assert await count(engine, "SELECT 1 FROM tables WHERE key = :k", k=key) == 1


# ── REST: verständliche Fehler (vor jedem DB-Zugriff) ────────────────────────


def test_endpoint_rejects_broken_files_with_readable_message():
    from fastapi.testclient import TestClient

    from app.auth import CurrentUser, current_user
    from app.main import app

    app.dependency_overrides[current_user] = lambda: CurrentUser(id="usr_a", name="A", email="a@x.de",
                                                                 roles=["einkauf"])
    try:
        client = TestClient(app)
        r = client.post("/api/imports/xlsx", files={"file": ("x.xlsx", b"kein excel")})
        assert r.status_code == 422 and "keine gültige .xlsx" in r.json()["detail"]
        r = client.post("/api/imports/xlsx", files={"file": ("x.xlsx", b"x" * (10 * 1024 * 1024 + 1))})
        assert r.status_code == 413
    finally:
        app.dependency_overrides.pop(current_user, None)
