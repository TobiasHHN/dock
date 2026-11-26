"""Word-Import (Task 3.7): Parser (ohne DB), Endpunkt-Fehler und die Pipeline mit `import.include` und Speichern."""
import importlib
import io
import json
import os
import uuid

import pytest
import pytest_asyncio
from docx import Document
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.imports import store
from app.imports.docx import parse_docx
from app.imports.xlsx import ImportFileError
from app.ops import pipeline
from app.ops.context import OpContext
from app.ops.errors import PipelineError
from app.ops.handlers import HANDLERS, load_handlers
from app.schemas.common import Actor
from app.schemas.ops import OpBatch

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock_test")
ANNA = Actor(type="user", id="usr_zz37anna", name="Anna")
TAG = "zz37"
TITLE = "ZZ37 Formular"


def docx_bytes(build) -> bytes:
    d = Document()
    build(d)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def form_of(result):
    return next(b for b in result.ops[-1]["blocks"] if b["type"] == "form")


# ── Parser ───────────────────────────────────────────────────────────────────


def test_field_variants_types_and_required():
    def build(d):
        d.add_heading("F", 1)
        for line in ["Name*: ____", "Lieferdatum: ....", "Menge: [ ]", "Gesamtbetrag: ___", "Ort: …",
                     "Kein Feld: text", "Name*: ____"]:
            d.add_paragraph(line)
        d.add_paragraph("[ ] Express")
        d.add_paragraph("☑ AGB gelesen*")

    res = parse_docx(docx_bytes(build))
    fields = [c["props"] for c in form_of(res)["children"]]
    assert [(f["key"], f["input"], f["required"]) for f in fields] == [
        ("name", "text", True), ("lieferdatum", "date", False), ("menge", "integer", False),
        ("gesamtbetrag", "currency", False), ("ort", "text", False), ("name_2", "text", True),
        ("express", "boolean", False), ("agb_gelesen", "boolean", True)]
    assert any("kommt mehrfach vor" in w and "name_2" in w for w in res.warnings)
    paragraphs = [b for b in res.ops[-1]["blocks"] if b["type"] == "paragraph"]
    assert [p["props"]["content"][0]["text"] for p in paragraphs] == ["Kein Feld: text"]  # bleibt normaler Text


def test_marks_links_numbered_list_and_headings():
    def build(d):
        d.add_heading("Titel", 1)
        d.add_heading("Unter", 4)  # tiefer als 3 -> 3
        p = d.add_paragraph("a ")
        r = p.add_run("fett")
        r.bold = True
        r.italic = True
        p.add_run(" und ").bold = False
        d.add_paragraph("eins", style="List Number")
        d.add_paragraph("zwei", style="List Number")
        d.add_paragraph("punkt", style="List Bullet")
        d.add_paragraph("")

    res = parse_docx(docx_bytes(build), title="Mein Titel")
    doc = res.ops[0]
    assert doc["title"] == "Mein Titel"
    assert [b["props"].get("level") for b in doc["blocks"][:2]] == [1, 3]
    content = doc["blocks"][2]["props"]["content"]
    assert content[1] == {"t": "text", "text": "fett", "marks": ["bold", "italic"]}
    kinds = [(b["type"], b["props"].get("ordered"), len(b.get("children", []))) for b in doc["blocks"][3:]]
    assert kinds == [("list", True, 2), ("list", False, 1)]
    assert res.warnings == []  # kein Formular, keine Warnung


def test_hyperlink_and_default_title_from_filename():
    d = Document()
    p = d.add_paragraph("Siehe ")
    rid = d.part.relate_to("https://example.org", "http://schemas.openxmlformats.org/officeDocument/2006/"
                           "relationships/hyperlink", is_external=True)
    from docx.oxml import parse_xml
    link = parse_xml(
        '<w:hyperlink xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="%s">'
        '<w:r><w:t>Seite</w:t></w:r></w:hyperlink>' % rid)
    p._p.append(link)
    buf = io.BytesIO()
    d.save(buf)
    res = parse_docx(buf.getvalue(), filename="Mein Dokument.docx")
    assert res.ops[0]["title"] == "Mein Dokument"
    assert res.ops[0]["blocks"][0]["props"]["content"][1] == {"t": "link", "text": "Seite", "href": "https://example.org"}


def test_filled_table_name_keys_and_collision_with_existing_table():
    def build(d):
        d.add_heading("Preise", 1)
        t = d.add_table(rows=3, cols=3)
        for c, h in enumerate(["Artikel", "", "Preis"]):
            t.cell(0, c).text = h
        t.cell(1, 0).text, t.cell(1, 2).text = "Monitor", "249,00"
        t.cell(2, 0).text = ""  # leere Zeile wird übersprungen
        d.add_paragraph("Ende")

    res = parse_docx(docx_bytes(build), tables=[{"id": "tbl_x", "key": "preise", "name": "Preise", "columns": []}])
    create, insert, doc = res.ops
    assert create["key"] == "preise_2" and create["name"] == "Preise 2"
    assert [c["key"] for c in create["columns"]] == ["artikel", "preis"]
    assert insert["rows"][0]["values"] == {"artikel": "Monitor", "preis": "249,00"} and len(insert["rows"]) == 1
    assert [b["type"] for b in doc["blocks"]] == ["heading", "table_view", "paragraph"]
    joined = " | ".join(res.warnings)
    assert "Spalte(n) ohne Spaltenkopf" in joined and "schon vergeben" in joined
    assert res.created["tables"][0]["rows"] == 1 and res.created["documents"][0]["form"] is None


def test_bind_table_to_table_from_same_import_and_missing_table():
    def build(d):
        d.add_heading("Kunden", 1)
        t = d.add_table(rows=2, cols=2)
        t.cell(0, 0).text, t.cell(0, 1).text = "Name", "Ort"
        t.cell(1, 0).text, t.cell(1, 1).text = "A", "B"
        d.add_paragraph("Name: ____")

    res = parse_docx(docx_bytes(build), bind_table="kunden")
    action = form_of(res)["props"]["actions"][0]
    create = res.ops[0]
    assert action["table"] == create["id"] and list(action["values"]) == [create["columns"][0]["id"]]
    assert not any("nirgends" in w for w in res.warnings)
    missing = parse_docx(docx_bytes(build), bind_table="gibtsnicht")
    assert any("gibtsnicht" in w and "nicht gefunden" in w for w in missing.warnings)
    assert any("nirgends hin" in w for w in missing.warnings)
    assert form_of(missing)["props"]["actions"] == []


def test_owner_forms_images_and_header_warnings():
    def build(d):
        d.add_paragraph("Hallo")
        d.sections[0].header.paragraphs[0].text = "Kopf"
        d.add_picture(io.BytesIO(_PNG))

    res = parse_docx(docx_bytes(build), owner="bestellfreigabe:erfassen")
    assert res.ops[0]["owner"] == {"workflow": "bestellfreigabe", "step": "erfassen"}
    assert any("Bild" in w for w in res.warnings) and any("Kopf-/Fußzeilen" in w for w in res.warnings)
    res = parse_docx(docx_bytes(build), owner={"workflow": "w", "step": "s"})
    assert res.ops[0]["owner"] == {"workflow": "w", "step": "s"}
    assert parse_docx(docx_bytes(build), owner='{"workflow": "w", "step": "s"}').ops[0]["owner"]["step"] == "s"
    with pytest.raises(ImportFileError, match="owner"):
        parse_docx(docx_bytes(build), owner="nur-workflow")


def test_broken_files_give_readable_errors():
    for data, needle in [
        (b"", "leer"),
        (b"das ist kein Word", "keine gültige .docx"),
        (bytes.fromhex("D0CF11E0A1B11AE1") + b"0" * 100, "passwortgeschützt"),
        (b"PK\x03\x04kaputt", "beschädigt"),
        (b"x" * (10 * 1024 * 1024 + 1), "zu groß"),
        (docx_bytes(lambda d: None), "keine importierbaren Inhalte"),
    ]:
        with pytest.raises(ImportFileError, match=needle):
            parse_docx(data)


def test_table_limits(monkeypatch):
    from app.imports import docx as mod

    monkeypatch.setattr(mod, "MAX_ROWS", 2)
    monkeypatch.setattr(mod, "MAX_COLUMNS", 2)

    def rows(d):
        t = d.add_table(rows=4, cols=1)
        t.cell(0, 0).text = "a"

    def cols(d):
        d.add_table(rows=1, cols=3).cell(0, 0).text = "a"

    with pytest.raises(ImportFileError, match="mehr als 2 Zeilen"):
        parse_docx(docx_bytes(rows))
    with pytest.raises(ImportFileError, match="mehr als 2 Spalten"):
        parse_docx(docx_bytes(cols))


def test_endpoint_rejects_broken_files_with_readable_message():
    from fastapi.testclient import TestClient

    from app.api import routers
    from app.auth import CurrentUser, current_user
    from app.db.session import get_session
    from app.main import app

    class FakeSession:
        async def commit(self):
            pass

    async def fake_tables(session):
        return []

    app.dependency_overrides[current_user] = lambda: CurrentUser(id="usr_a", name="A", email="a@x.de",
                                                                 roles=["einkauf"])
    app.dependency_overrides[get_session] = lambda: FakeSession()
    orig = routers.queries.list_tables
    routers.queries.list_tables = fake_tables
    try:
        client = TestClient(app)
        r = client.post("/api/imports/docx", files={"file": ("x.docx", b"kein word")})
        assert r.status_code == 422 and "keine gültige .docx" in r.json()["detail"]
        r = client.post("/api/imports/docx", files={"file": ("x.docx", b"x" * (10 * 1024 * 1024 + 1))})
        assert r.status_code == 413
    finally:
        routers.queries.list_tables = orig
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)


_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f0005"
    "0001ff8dc7b4e80000000049454e44ae426082")


# ── Pipeline: Import ausführen und Formular absenden ─────────────────────────


@pytest_asyncio.fixture
async def engine(monkeypatch):
    eng = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with eng.connect() as c:
            await c.execute(text("SELECT 1 FROM imports LIMIT 1"))
            await c.execute(text("SELECT 1 FROM form_drafts LIMIT 1"))
    except Exception:
        pytest.skip("Postgres nicht erreichbar")

    async def no_reembed(*_):
        return None

    monkeypatch.setattr(pipeline, "enqueue_reembed", no_reembed)
    monkeypatch.setattr(pipeline, "SessionLocal", async_sessionmaker(eng, expire_on_commit=False))
    load_handlers()
    for name, module in (("row.insert", "tables"), ("doc.create", "documents"), ("form.submit", "forms")):
        if name not in HANDLERS:  # ein anderer Test hat die Registry geleert
            importlib.reload(importlib.import_module(f"app.ops.handlers.{module}"))
    async with eng.begin() as c:
        await c.execute(text("""INSERT INTO roles (id, workspace_id, key, name) VALUES ('rol_zz37einkauf', 'ws_demo',
                                'einkauf', 'einkauf') ON CONFLICT (workspace_id, key) DO NOTHING"""))
        await c.execute(text("""INSERT INTO member_roles (workspace_id, member_id, role_id)
                                SELECT 'ws_demo', :m, id FROM roles WHERE workspace_id = 'ws_demo' AND key = 'einkauf'
                                ON CONFLICT DO NOTHING"""), {"m": ANNA.id})
    yield eng
    async with eng.begin() as c:
        docs = [r[0] for r in (await c.execute(text("SELECT id FROM documents WHERE title = :t"),
                                               {"t": TITLE})).all()]
        for stmt in (
            f"DELETE FROM oplog WHERE batch_id LIKE '%{TAG}%'",
            f"DELETE FROM batches WHERE batch_id LIKE '%{TAG}%'",
            f"DELETE FROM form_submissions WHERE id LIKE '%{TAG}%'",
            f"DELETE FROM channels WHERE id IN (SELECT 'table:' || id FROM tables WHERE key LIKE '{TAG}%')",
            f"DELETE FROM rows WHERE table_id IN (SELECT id FROM tables WHERE key LIKE '{TAG}%')",
            f"DELETE FROM tables WHERE key LIKE '{TAG}%'",
            f"DELETE FROM imports WHERE actor ->> 'id' = '{ANNA.id}'",
            f"DELETE FROM member_roles WHERE member_id = '{ANNA.id}'",
        ):
            await c.execute(text(stmt))
        for d in docs:
            await c.execute(text('DELETE FROM "references" WHERE source_id = :d OR source_id IN '
                                 "(SELECT id FROM blocks WHERE doc_id = :d)"), {"d": d})
            await c.execute(text("DELETE FROM form_drafts WHERE form_block IN (SELECT id FROM blocks WHERE doc_id = :d)"),
                            {"d": d})
            await c.execute(text("DELETE FROM documents WHERE id = :d"), {"d": d})
    await eng.dispose()


def batch(*ops):
    return OpBatch.model_validate({"batch_id": f"b_{TAG}{uuid.uuid4().hex[:8]}", "ops": list(ops)})


async def rows(engine, table_id):
    async with engine.connect() as c:
        res = await c.execute(text('SELECT "values" FROM rows WHERE table_id = :t'), {"t": table_id})
        return [json.loads(r[0]) if isinstance(r[0], str) else r[0] for r in res.all()]


async def save_and_run(engine, result, *more):
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session, session.begin():
        plan = await store.save_plan(OpContext(session=session, actor=ANNA), "docx", result.ops, result.created,
                                     result.warnings)
    return await pipeline.apply_batch(batch({"op": "import.include", "import_id": plan.import_id}, *more), ANNA)


def sample() -> bytes:
    def build(d):
        d.add_heading("Bestellformular", 1)
        d.add_paragraph("Bitte ausfüllen.")
        d.add_paragraph("Name*: ____")
        d.add_paragraph("Kostenstelle: ____")
        d.add_paragraph("☐ Lieferung eilig")
        d.add_paragraph("Danke.")

    return docx_bytes(build)


async def test_bind_table_import_runs_in_pipeline_and_save_writes_row(engine):
    key = f"{TAG}best{uuid.uuid4().hex[:6]}"
    tid, c_name, c_ks = (f"{p}_{TAG}{uuid.uuid4().hex[:10]}" for p in ("tbl", "col", "col"))
    await pipeline.apply_batch(batch({"op": "table.create", "id": tid, "key": key, "name": "Bestellungen", "columns": [
        {"id": c_name, "key": "name", "name": "Name", "type": {"kind": "text"}, "required": True},
        {"id": c_ks, "key": "kostenstelle", "name": "Kostenstelle", "type": {"kind": "text"}}]}), ANNA)
    existing = [{"id": tid, "key": key, "name": "Bestellungen", "columns": [
        {"id": c_name, "key": "name", "name": "Name", "required": True},
        {"id": c_ks, "key": "kostenstelle", "name": "Kostenstelle"}]}]
    result = parse_docx(sample(), title=TITLE, bind_table=key, tables=existing)
    assert any("Lieferung eilig" in w for w in result.warnings)
    form_id = result.created["documents"][0]["form"]["block"]

    res = await save_and_run(engine, result)
    assert res.results["0"] == {"included": 1}
    sub = {"op": "form.submit", "submission_id": f"sub_{TAG}{uuid.uuid4().hex[:8]}", "form_block": form_id,
           "button": "save", "values": {"name": "Anna", "kostenstelle": "4711", "lieferung_eilig": True}}
    out = await pipeline.apply_batch(batch(sub), ANNA)
    assert out.results["0"]["results"]["save"]["id"].startswith("row_")
    assert await rows(engine, tid) == [{c_name: "Anna", c_ks: "4711"}]

    bad = {**sub, "submission_id": f"sub_{TAG}{uuid.uuid4().hex[:8]}", "values": {"kostenstelle": "x"}}
    with pytest.raises(PipelineError) as e:  # Pflichtfeld Name fehlt: nichts wird geschrieben
        await pipeline.apply_batch(batch(bad), ANNA)
    assert e.value.error.code == "VALIDATION"
    assert len(await rows(engine, tid)) == 1


async def test_import_with_table_and_form_in_one_batch_and_extra_actions(engine):
    """Gefüllte Tabelle + Formular im selben Import: bind_table zeigt auf die neue Tabelle, Speichern funktioniert."""
    name = f"{TAG}kunden{uuid.uuid4().hex[:6]}"

    def build(d):
        d.add_heading(name, 1)
        t = d.add_table(rows=2, cols=2)
        t.cell(0, 0).text, t.cell(0, 1).text = "Name", "Ort"
        t.cell(1, 0).text, t.cell(1, 1).text = "Anna", "Köln"
        d.add_paragraph("Name: ____")
        d.add_paragraph("Ort: ____")

    result = parse_docx(docx_bytes(build), title=TITLE, bind_table=name)
    table = result.created["tables"][0]
    form_id = result.created["documents"][0]["form"]["block"]
    assert result.created["bound_table"]["id"] == table["id"]
    await save_and_run(engine, result)
    assert len(await rows(engine, table["id"])) == 1
    sub = {"op": "form.submit", "submission_id": f"sub_{TAG}{uuid.uuid4().hex[:8]}", "form_block": form_id,
           "button": "save", "values": {"name": "Ben", "ort": "Bonn"}}
    await pipeline.apply_batch(batch(sub), ANNA)
    assert sorted(r[table["column_ids"]["name"]] for r in await rows(engine, table["id"])) == ["Anna", "Ben"]


async def test_form_without_actions_imports_but_cannot_submit(engine):
    result = parse_docx(sample(), title=TITLE)
    assert any("Formular schreibt nirgends hin" in w for w in result.warnings)
    form_id = result.created["documents"][0]["form"]["block"]
    await save_and_run(engine, result)
    sub = {"op": "form.submit", "submission_id": f"sub_{TAG}{uuid.uuid4().hex[:8]}", "form_block": form_id,
           "button": "save", "values": {"name": "Anna"}}
    with pytest.raises(PipelineError):
        await pipeline.apply_batch(batch(sub), ANNA)


async def test_owner_is_resolved_by_pipeline(engine):
    """Ein unbekannter Workflow im `owner` lässt den ganzen Import scheitern, nichts bleibt zurück."""
    result = parse_docx(sample(), title=TITLE, owner="gibtsnicht:erfassen")
    with pytest.raises(PipelineError):
        await save_and_run(engine, result)
    async with engine.connect() as c:
        n = (await c.execute(text("SELECT count(*) FROM documents WHERE title = :t"), {"t": TITLE})).scalar_one()
    assert n == 0


async def test_endpoint_apply_true_end_to_end(engine):
    """POST /api/imports/docx mit bind_table und apply=true gegen die echte Datenbank."""
    import httpx

    from app.auth import CurrentUser, current_user
    from app.db.session import get_session
    from app.main import app

    sm = async_sessionmaker(engine, expire_on_commit=False)

    async def real_session():
        async with sm() as s:
            yield s

    key = f"{TAG}rest{uuid.uuid4().hex[:6]}"
    tid, c_name = f"tbl_{TAG}{uuid.uuid4().hex[:10]}", f"col_{TAG}{uuid.uuid4().hex[:10]}"
    await pipeline.apply_batch(batch({"op": "table.create", "id": tid, "key": key, "name": "Rest", "columns": [
        {"id": c_name, "key": "name", "name": "Name", "type": {"kind": "text"}}]}), ANNA)
    app.dependency_overrides[current_user] = lambda: CurrentUser(id=ANNA.id, name="Anna", email="a@x.de",
                                                                 roles=["einkauf"])
    app.dependency_overrides[get_session] = real_session
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            r = await client.post("/api/imports/docx", files={"file": ("f.docx", sample())},
                                  data={"title": TITLE, "bind_table": key, "apply": "true"})
            assert r.status_code == 200, r.text
            plan = r.json()
            assert plan["result"]["results"]["0"] == {"included": 1}
            form_id = plan["created"]["documents"][0]["form"]["block"]
            assert any("Kostenstelle" in w for w in plan["warnings"])  # Feld ohne Spalte
            r = await client.post("/api/imports/docx", files={"file": ("f.docx", b"kaputt")})
            assert r.status_code == 422 and "keine gültige .docx" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)
    sub = {"op": "form.submit", "submission_id": f"sub_{TAG}{uuid.uuid4().hex[:8]}", "form_block": form_id,
           "button": "save", "values": {"name": "Via REST"}}
    await pipeline.apply_batch(batch(sub), ANNA)
    assert await rows(engine, tid) == [{c_name: "Via REST"}]
