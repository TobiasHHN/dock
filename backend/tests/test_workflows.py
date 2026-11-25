"""Workflow-Definition, Prüfung und Veröffentlichen (Task 4.1, L 5.2, L 5.3, L 5.7, L 9).

Reine Prüflogik (`check_definition`) ohne DB, dazu `workflow.*`-Handler und REST gegen Postgres.
Testdaten tragen den Marker `zz41` und werden nach jedem Test entfernt. Postgres: Host-Port 5433,
überschreibbar mit TEST_DATABASE_URL."""
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
from app.domain import workflows as W
from app.main import app
from app.ops import pipeline
from app.ops.errors import PipelineError
from app.schemas.common import Actor
from app.schemas.ops import OpBatch
from app.schemas.workflows import WorkflowDefinition

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock")
ANNA = Actor(type="user", id="usr_zz41anna", name="Anna")
BEN = Actor(type="user", id="usr_zz41ben", name="Ben")


def zid(prefix: str) -> str:
    return f"{prefix}_zz41{uuid.uuid4().hex[:10]}"


def zkey(name: str) -> str:
    return f"zz41{name}{uuid.uuid4().hex[:6]}"


# ── Beispiel aus L 10.1 als Bausteine ────────────────────────────────────────


def example(ids: dict[str, str] | None = None) -> dict[str, object]:
    """IDs, Ops und Definition des Bestellprozesses (L 10.1), mit frischen IDs/Keys."""
    i = ids or {}
    i = {k: i.get(k) or v for k, v in {
        "wf": zid("wf"), "wf_key": zkey("wf"), "tl": zid("rol"), "tl_key": zkey("tl"), "ek": "einkauf",
        "best": zid("tbl"), "art": zid("tbl"), "s1": zid("doc"), "s2": zid("doc"), "s3": zid("doc"),
    }.items()}
    c = {k: zid("col") for k in ("b_name", "b_ks", "b_status", "b_gen", "b_komm", "b_lnr", "b_lt", "b_run",
                                 "a_name", "a_preis", "a_nr", "a_anz", "a_best")}
    i["cols"] = c
    definition = {
        "start": "erfassen",
        "starters": [],
        "managers": [{"kind": "role", "role": i["ek"]}],
        "run_title": "{{concat(\"Bestellung KS \", coalesce(run.steps.erfassen.values.kostenstelle, \"…\"))}}",
        "steps": [
            {"key": "erfassen", "name": "Bestellung erfassen", "document": i["s1"], "assignees": [{"kind": "starter"}]},
            {"key": "genehmigung", "name": "Genehmigung", "document": i["s2"],
             "assignees": [{"kind": "role", "role": i["tl_key"]}], "exclude_starter": True, "due_in": "P2D"},
            {"key": "bestellung", "name": "Bestellung auslösen", "document": i["s3"],
             "assignees": [{"kind": "role", "role": i["ek"]}], "due_in": "P3D"},
        ],
        "transitions": [
            {"from": "erfassen", "on": "submitted", "to": "genehmigung"},
            {"from": "genehmigung", "on": "approved", "to": "bestellung"},
            {"from": "genehmigung", "on": "rejected", "to": "end"},
            {"from": "bestellung", "on": "ordered", "to": "end"},
        ],
    }
    order = "{{run.steps.erfassen.results.order.id}}"
    s1 = [
        {"id": zid("blk"), "type": "paragraph", "props": {"content": [{"t": "text", "text": "Bitte ausfüllen."}]}},
        {"id": zid("blk"), "type": "form", "props": {
            "actions": [
                {"key": "order", "type": "create_row", "table": i["best"], "values": {
                    c["b_name"]: "{{fields.name}}", c["b_ks"]: "{{fields.kostenstelle}}",
                    c["b_status"]: "eingereicht", c["b_run"]: "{{run.id}}"}},
                {"key": "items", "type": "create_rows", "table": i["art"], "for_each": "{{fields.artikel}}",
                 "values": {c["a_name"]: "{{item.artikelname}}", c["a_preis"]: "{{item.preis}}",
                            c["a_nr"]: "{{item.artikelnummer}}", c["a_anz"]: "{{item.anzahl}}",
                            c["a_best"]: "{{results.order.id}}"}}],
            "buttons": [{"id": "submit", "label": "Eingereicht", "style": "primary", "actions": ["order", "items"],
                         "outcome": "submitted"}]},
         "children": [
             {"id": zid("blk"), "type": "field", "props": {"key": "name", "label": "Name", "column": c["b_name"],
                                                           "default": "{{user.name}}"}},
             {"id": zid("blk"), "type": "field", "props": {"key": "kostenstelle", "label": "Kostenstelle",
                                                           "column": c["b_ks"]}},
             {"id": zid("blk"), "type": "line_items", "props": {"key": "artikel", "label": "Artikel", "min_rows": 1,
                 "columns": [{"key": "artikelname", "column": c["a_name"]}, {"key": "preis", "column": c["a_preis"]},
                             {"key": "artikelnummer", "column": c["a_nr"]}, {"key": "anzahl", "column": c["a_anz"]}]}}]},
    ]
    s2 = [
        {"id": zid("blk"), "type": "paragraph", "props": {"content": [
            {"t": "text", "text": "Bestellung von "}, {"t": "value", "expr": "{{run.steps.erfassen.values.name}}"},
            {"t": "value", "expr": "{{sum(run.steps.erfassen.values.artikel, \"preis\")}}"}]}},
        {"id": zid("blk"), "type": "table_view", "props": {
            "table": i["art"], "columns": [c["a_name"], c["a_preis"]],
            "filter": [{"column": c["a_best"], "op": "eq", "value": order}], "editable": False}},
        {"id": zid("blk"), "type": "form", "props": {
            "actions": [
                {"key": "approve", "type": "update_row", "table": i["best"], "row": order,
                 "values": {c["b_status"]: "genehmigt", c["b_gen"]: "{{user.id}}", c["b_komm"]: "{{fields.kommentar}}"}},
                {"key": "reject", "type": "update_row", "table": i["best"], "row": order,
                 "values": {c["b_status"]: "abgelehnt", c["b_komm"]: "{{fields.kommentar}}"}}],
            "buttons": [
                {"id": "approve", "label": "Genehmigt", "actions": ["approve"], "outcome": "approved"},
                {"id": "reject", "label": "Abgelehnt", "style": "danger", "actions": ["reject"], "outcome": "rejected",
                 "require": ["kommentar"]}]},
         "children": [{"id": zid("blk"), "type": "field",
                       "props": {"key": "kommentar", "label": "Kommentar", "input": "textarea"}}]},
    ]
    s3 = [
        {"id": zid("blk"), "type": "paragraph", "props": {"content": [
            {"t": "text", "text": "Genehmigt von "},
            {"t": "value", "expr": "{{run.steps.genehmigung.completed_by.name}}"}]}},
        {"id": zid("blk"), "type": "form", "props": {
            "actions": [{"key": "ordered", "type": "update_row", "table": i["best"], "row": order, "values": {
                c["b_status"]: "bestellt", c["b_lnr"]: "{{fields.lieferanten_nr}}", c["b_lt"]: "{{fields.liefertermin}}"}}],
            "buttons": [{"id": "ordered", "label": "Bestellt", "actions": ["ordered"], "outcome": "ordered"}]},
         "children": [
             {"id": zid("blk"), "type": "field", "props": {"key": "lieferanten_nr", "label": "Nr.", "column": c["b_lnr"],
                                                           "required": True}},
             {"id": zid("blk"), "type": "field", "props": {"key": "liefertermin", "label": "Termin",
                                                           "column": c["b_lt"]}}]},
    ]
    select = {"kind": "select", "options": [{"id": o, "label": o} for o in
                                            ("eingereicht", "genehmigt", "abgelehnt", "bestellt")]}
    ops = [
        {"op": "role.create", "id": i["tl"], "key": i["tl_key"], "name": "Teamleitung"},
        {"op": "table.create", "id": i["best"], "key": zkey("best"), "name": "Bestellungen", "columns": [
            {"id": c["b_name"], "key": "name", "name": "Name", "type": {"kind": "text"}, "required": True},
            {"id": c["b_ks"], "key": "kostenstelle", "name": "KS", "type": {"kind": "text"}, "required": True},
            {"id": c["b_status"], "key": "status", "name": "Status", "type": select, "default": "eingereicht"},
            {"id": c["b_gen"], "key": "genehmigt_von", "name": "Gen.", "type": {"kind": "user"}},
            {"id": c["b_komm"], "key": "kommentar", "name": "Kommentar", "type": {"kind": "long_text"}},
            {"id": c["b_lnr"], "key": "lieferanten_nr", "name": "Nr.", "type": {"kind": "text"}},
            {"id": c["b_lt"], "key": "liefertermin", "name": "Termin", "type": {"kind": "date"}},
            {"id": c["b_run"], "key": "run", "name": "Vorgang", "type": {"kind": "text"}}]},
        {"op": "table.create", "id": i["art"], "key": zkey("art"), "name": "Artikel", "columns": [
            {"id": c["a_name"], "key": "artikelname", "name": "Artikel", "type": {"kind": "text"}, "required": True},
            {"id": c["a_preis"], "key": "preis", "name": "Preis", "type": {"kind": "currency", "currency": "EUR"},
             "required": True},
            {"id": c["a_nr"], "key": "artikelnummer", "name": "Nr.", "type": {"kind": "text"}},
            {"id": c["a_anz"], "key": "anzahl", "name": "Anzahl", "type": {"kind": "integer", "min": 1},
             "required": True},
            {"id": c["a_best"], "key": "bestellung", "name": "Bestellung",
             "type": {"kind": "reference", "table": i["best"], "on_delete": "cascade"}, "required": True}]},
        {"op": "workflow.create", "id": i["wf"], "key": i["wf_key"], "name": "Bestellprozess zz41",
         "definition": definition},
        {"op": "doc.create", "id": i["s1"], "title": "Erfassen", "owner": {"workflow": i["wf"], "step": "erfassen"},
         "blocks": s1},
        {"op": "doc.create", "id": i["s2"], "title": "Genehmigung",
         "owner": {"workflow": i["wf"], "step": "genehmigung"}, "blocks": s2},
        {"op": "doc.create", "id": i["s3"], "title": "Bestellung",
         "owner": {"workflow": i["wf"], "step": "bestellung"}, "blocks": s3},
    ]
    return {"ids": i, "ops": ops, "definition": definition, "docs": {i["s1"]: s1, i["s2"]: s2, i["s3"]: s3}}


# ── reine Prüfung (ohne DB) ──────────────────────────────────────────────────


def _flat(doc_id: str, nodes: list[dict], parent: str | None = None) -> list[dict]:
    out = []
    for n, node in enumerate(nodes):
        out.append({"id": node["id"], "doc_id": doc_id, "parent_id": parent, "position": f"a{n}",
                    "type": node["type"], "props": node["props"]})
        out += _flat(doc_id, node.get("children") or [], node["id"])
    return out


def env_for(ex: dict, members: int = 2) -> W.WorkflowEnv:
    i = ex["ids"]
    env = W.WorkflowEnv(workflow_id=i["wf"], workflows={i["wf"]})
    steps = {s["document"]: s["key"] for s in ex["definition"]["steps"]}
    env.documents = {d: {"title": d, "owner_workflow": i["wf"], "owner_step": steps[d], "blocks": _flat(d, nodes)}
                     for d, nodes in ex["docs"].items()}
    env.roles = {i["tl"]: {"key": i["tl_key"], "members": members}, "rol_ek": {"key": "einkauf", "members": members}}
    table_ops = [o for o in ex["ops"] if o["op"] == "table.create"]
    env.tables = {t["id"]: {"key": t["key"], "columns": {
        c["id"]: {"key": c["key"], "required": c.get("required", False), "default": c.get("default")}
        for c in t["columns"]}} for t in table_ops}
    return env


def check(ex: dict, env: W.WorkflowEnv | None = None, **patch) -> W.ValidationResult:
    definition = {**ex["definition"], **patch}
    return W.check_definition(WorkflowDefinition.model_validate(definition), env or env_for(ex))


def codes(result, severity="error") -> list[str]:
    return [i.code for i in result.issues if i.severity == severity]


def test_example_from_spec_is_valid():
    result = check(example())
    assert result.ok, result.issues
    assert codes(result, "warning") == []


def test_expression_paths_skip_functions_and_strings():
    assert W.expression_paths('{{concat("a.b", run.steps.x.values.y, coalesce(fields.z, "…"))}}') == [
        "run.steps.x.values.y", "fields.z"]
    assert W.expression_paths("Text ohne Ausdruck") == []
    assert W.expression_paths("{{sum(run.steps.erfassen.values.artikel, \"preis\")}} und {{true}}") == [
        "run.steps.erfassen.values.artikel"]


def test_structure_errors():
    ex = example()
    steps = ex["definition"]["steps"]
    r = check(ex, start="anfang")
    assert "START_UNKNOWN" in codes(r) and not r.ok
    # bestellung ist nicht mehr erreichbar, und von genehmigung führt "approved" ins Leere
    r = check(ex, transitions=[t for t in ex["definition"]["transitions"] if t["to"] != "bestellung"])
    assert "STEP_UNREACHABLE" in codes(r)
    assert any(i.code == "BUTTON_NO_TRANSITION" and i.step == "genehmigung" and "approved" in i.message
               for i in r.issues)
    # Schleife ohne Ausgang
    r = check(ex, transitions=[{"from": "erfassen", "on": "submitted", "to": "genehmigung"},
                               {"from": "genehmigung", "on": "*", "to": "erfassen"}], steps=steps[:2])
    assert "NO_PATH_TO_END" in codes(r)
    r = check(ex, transitions=[*ex["definition"]["transitions"], {"from": "erfassn", "on": "x", "to": "ende"}])
    assert codes(r).count("TRANSITION_UNKNOWN_STEP") == 2
    assert "Meinten Sie 'erfassen'" in r.issues[0].message


def test_step_without_buttons_and_unknown_document():
    ex = example()
    env = env_for(ex)
    s3 = ex["ids"]["s3"]
    env.documents[s3]["blocks"] = [b for b in env.documents[s3]["blocks"] if b["type"] == "paragraph"]
    r = check(ex, env)
    assert any(i.code == "STEP_NO_BUTTONS" and i.step == "bestellung" for i in r.issues)
    del env.documents[s3]
    assert "DOCUMENT_UNKNOWN" in codes(check(ex, env))


def test_assignee_errors_and_warnings():
    ex = example()
    steps = json.loads(json.dumps(ex["definition"]["steps"]))
    steps[1]["assignees"] = []
    steps[2]["assignees"] = [{"kind": "role", "role": "teamleitung"}, {"kind": "user", "user": "usr_weg"}]
    steps[0]["exclude_starter"] = True
    r = check(ex, steps=steps, managers=[])
    assert {"STEP_NO_ASSIGNEES", "ROLE_UNKNOWN", "USER_UNKNOWN", "EXCLUDE_STARTER_ONLY_STARTER"} <= set(codes(r))
    assert "MANAGERS_EMPTY" in codes(r, "warning")
    r = check(ex, env_for(ex, members=0))
    assert r.ok and "ROLE_EMPTY" in codes(r, "warning")
    steps = json.loads(json.dumps(ex["definition"]["steps"]))
    steps[1]["due_in"] = "2 Tage"
    assert "DUE_INVALID" in codes(check(ex, steps=steps))


def test_data_errors():
    ex = example()
    i, c = ex["ids"], ex["ids"]["cols"]
    form = ex["docs"][i["s1"]][1]
    actions = form["props"]["actions"]
    actions[0]["values"][c["b_ks"]] = "{{fields.kostenstele}}"
    actions[0]["values"]["col_gibtsnicht"] = "x"
    del actions[1]["values"][c["a_name"]]
    r = check(ex)
    fields = [x for x in r.issues if x.code == "EXPR_UNKNOWN_FIELD"]
    assert fields and "kostenstele" in fields[0].message and "Meinten Sie 'kostenstelle'" in fields[0].message
    assert fields[0].block == form["id"] and fields[0].step == "erfassen"
    assert any(x.code == "COLUMN_UNKNOWN" and "col_gibtsnicht" in x.message for x in r.issues)
    assert any(x.code == "REQUIRED_COLUMN_MISSING" and ".artikelname" in x.message for x in r.issues)


def test_run_steps_must_lie_on_every_path_before():
    ex = example()
    # bestellung ist auch direkt aus erfassen erreichbar: genehmigung liegt nicht auf jedem Weg davor
    r = check(ex, transitions=[*ex["definition"]["transitions"],
                               {"from": "erfassen", "on": "eilig", "to": "bestellung"}])
    assert any(x.code == "RUN_STEP_NOT_BEFORE" and x.step == "bestellung" and "genehmigung" in x.message
               for x in r.issues)
    assert "TRANSITION_UNUSED" in codes(r, "warning")


def test_revisit_with_create_row_warns():
    ex = example()
    r = check(ex, transitions=[*ex["definition"]["transitions"],
                               {"from": "genehmigung", "on": "rueckfrage", "to": "erfassen"}])
    assert any(x.code == "REVISIT_CREATE_ROW" and x.step == "erfassen" for x in r.issues)


def test_subflow_cycle_is_rejected():
    ex = example()
    env = env_for(ex)
    other = "wf_other"
    env.workflows.add(other)
    env.subflows = {other: {ex["ids"]["wf"]}}
    s3 = ex["ids"]["s3"]
    env.documents[s3]["blocks"].append({"id": "blk_sub", "doc_id": s3, "parent_id": None, "position": "z",
                                        "type": "workflow", "props": {"workflow": other, "mode": "subflow"}})
    r = check(ex, env)
    assert any(x.code == "CYCLE" and other in x.message for x in r.issues)


# ── gegen Postgres ───────────────────────────────────────────────────────────


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
        for member, role in ((ANNA.id, "einkauf"), (BEN.id, "mitarbeiter")):
            await c.execute(text("""INSERT INTO roles (id, workspace_id, key, name) VALUES (:i, 'ws_demo', :k, :k)
                                    ON CONFLICT (workspace_id, key) DO NOTHING"""), {"i": f"rol_zz41{role}", "k": role})
            await c.execute(text("""INSERT INTO member_roles (workspace_id, member_id, role_id)
                                    SELECT 'ws_demo', :m, id FROM roles WHERE workspace_id = 'ws_demo' AND key = :k
                                    ON CONFLICT DO NOTHING"""), {"m": member, "k": role})
    yield eng
    async with eng.begin() as c:
        for stmt in (
            "DELETE FROM oplog WHERE batch_id LIKE '%zz41%'",
            "DELETE FROM batches WHERE batch_id LIKE '%zz41%'",
            "DELETE FROM channels WHERE id LIKE '%zz41%'",
            'DELETE FROM "references" WHERE source_id LIKE \'%zz41%\' OR target_id LIKE \'%zz41%\'',
            "DELETE FROM run_events WHERE run_id LIKE '%zz41%'",
            "DELETE FROM tasks WHERE run_id LIKE '%zz41%'",
            "DELETE FROM runs WHERE id LIKE '%zz41%'",
            "DELETE FROM workflows WHERE id LIKE '%zz41%'",
            "DELETE FROM documents WHERE id LIKE '%zz41%'",
            "DELETE FROM tables WHERE id LIKE '%zz41%'",
            "DELETE FROM member_roles WHERE member_id LIKE '%zz41%' OR role_id LIKE '%zz41%'",
            "DELETE FROM roles WHERE id LIKE '%zz41%'",
        ):
            await c.execute(text(stmt))
    await eng.dispose()


async def q(engine, sql, **params):
    async with engine.connect() as c:
        return (await c.execute(text(sql), params)).mappings().all()


async def run(*ops, actor=ANNA):
    return await pipeline.apply_batch(OpBatch.model_validate({"batch_id": zid("b"), "ops": list(ops)}), actor)


async def add_member(engine, member: str, role_id: str):
    async with engine.begin() as c:
        await c.execute(text("INSERT INTO member_roles (workspace_id, member_id, role_id) VALUES ('ws_demo', :m, :r)"),
                        {"m": member, "r": role_id})


async def test_full_example_in_one_batch_publishes_v1(engine):
    ex = example()
    i = ex["ids"]
    result = await run(*ex["ops"], {"op": "workflow.publish", "workflow": i["wf_key"]})
    published = result.results[str(len(ex["ops"]))]
    assert published["version"] == 1 and published["workflow"] == i["wf"]
    # die frisch angelegte Rolle hat noch keine Mitglieder: Warnung, aber kein Fehler
    assert any(w["code"] == "ROLE_EMPTY" for w in published["warnings"])

    wf = (await q(engine, "SELECT key, draft, latest_version FROM workflows WHERE id = :i", i=i["wf"]))[0]
    assert wf["latest_version"] == 1
    # Rollen-Key wurde zur ID aufgelöst (L 1)
    assert wf["draft"]["steps"][1]["assignees"] == [{"kind": "role", "role": i["tl"]}]
    version = (await q(engine, "SELECT definition, documents, published_by FROM workflow_versions "
                               "WHERE workflow_id = :i AND version = 1", i=i["wf"]))[0]
    assert set(version["documents"]) == {i["s1"], i["s2"], i["s3"]}
    assert len(version["documents"][i["s1"]]) == 5  # Absatz, Formular, 3 Felder
    assert version["published_by"]["id"] == ANNA.id
    assert version["definition"]["transitions"][0]["from"] == "erfassen"

    refs = await q(engine, """SELECT target_kind, target_id, via FROM "references"
                              WHERE source_kind = 'workflow' AND source_id = :i""", i=i["wf"])
    edges = {(r["target_kind"], r["target_id"], r["via"]) for r in refs}
    assert ("document", i["s2"], "step.document") in edges
    assert ("role", i["tl"], "step.assignee") in edges
    assert any(e[2] == "workflow.managers" for e in edges)


async def test_publish_freezes_documents_and_counts_up(engine):
    ex = example()
    i = ex["ids"]
    await run(*ex["ops"], {"op": "workflow.publish", "workflow": i["wf"]})
    first_block = ex["docs"][i["s1"]][0]["id"]
    await run({"op": "block.update", "block": first_block,
               "props": {"content": [{"t": "text", "text": "Neuer Text"}]}})
    second = await run({"op": "workflow.publish", "workflow": i["wf"]})
    assert second.results["0"]["version"] == 2
    rows = await q(engine, "SELECT version, documents FROM workflow_versions WHERE workflow_id = :i ORDER BY version",
                   i=i["wf"])

    def text_of(docs):
        block = next(b for b in docs[i["s1"]] if b["id"] == first_block)
        return block["props"]["content"][0]["text"]

    assert [text_of(r["documents"]) for r in rows] == ["Bitte ausfüllen.", "Neuer Text"]


async def test_faulty_publish_rejects_whole_batch_with_readable_issues(engine):
    ex = example()
    i = ex["ids"]
    ex["definition"]["steps"][1]["assignees"] = [{"kind": "role", "role": "gibtsnicht"}]
    ex["definition"]["transitions"] = ex["definition"]["transitions"][:-1]  # bestellung ohne Weg zum Ende
    with pytest.raises(PipelineError) as exc:
        await run(*ex["ops"], {"op": "workflow.publish", "workflow": i["wf"]})
    err = exc.value.error
    assert err.code == "VALIDATION"
    issue_codes = {x["code"] for x in err.details["issues"]}
    assert {"ROLE_UNKNOWN", "NO_PATH_TO_END", "BUTTON_NO_TRANSITION"} <= issue_codes
    assert "gibtsnicht" in err.message
    assert any(k.startswith("steps.genehmigung") for k in err.details["errors"])
    # atomar: weder Workflow noch Tabellen noch Dokumente
    assert await q(engine, "SELECT 1 FROM workflows WHERE id = :i", i=i["wf"]) == []
    assert await q(engine, "SELECT 1 FROM tables WHERE id = :i", i=i["best"]) == []
    assert await q(engine, "SELECT 1 FROM documents WHERE id = :i", i=i["s1"]) == []


async def test_draft_may_be_incomplete_until_publish(engine):
    wf, key = zid("wf"), zkey("wf")
    definition = {"start": "a", "steps": [{"key": "a", "name": "A", "document": zid("doc"),
                                           "assignees": [{"kind": "role", "role": "nochnicht"}]}],
                  "transitions": []}
    await run({"op": "workflow.create", "id": wf, "key": key, "name": "Entwurf", "definition": definition})
    row = (await q(engine, "SELECT draft, latest_version FROM workflows WHERE id = :i", i=wf))[0]
    assert row["latest_version"] is None
    assert row["draft"]["steps"][0]["assignees"][0]["role"] == "nochnicht"
    definition["steps"][0]["name"] = "A2"
    await run({"op": "workflow.update", "workflow": key, "definition": definition})
    row = (await q(engine, "SELECT draft FROM workflows WHERE id = :i", i=wf))[0]
    assert row["draft"]["steps"][0]["name"] == "A2"
    with pytest.raises(PipelineError) as exc:
        await run({"op": "workflow.publish", "workflow": wf})
    assert {"ROLE_UNKNOWN", "DOCUMENT_UNKNOWN"} <= {x["code"] for x in exc.value.error.details["issues"]}


async def test_create_rejects_bad_and_duplicate_keys(engine):
    definition = {"start": "a", "steps": [], "transitions": []}
    key = zkey("wf")
    await run({"op": "workflow.create", "id": zid("wf"), "key": key, "name": "X", "definition": definition})
    for op, field in (({"id": zid("wf"), "key": key}, "key"), ({"id": zid("wf"), "key": "wf_x"}, "key"),
                      ({"id": zid("wf"), "key": "Groß"}, "key"), ({"id": "bad", "key": zkey("wf")}, "id")):
        with pytest.raises(PipelineError) as exc:
            await run({"op": "workflow.create", "name": "X", "definition": definition, **op})
        assert exc.value.error.code == "VALIDATION" and field in exc.value.error.details["errors"]


async def test_ben_may_not_create_or_publish(engine):
    ex = example()
    with pytest.raises(PipelineError) as exc:
        await run(*ex["ops"], actor=BEN)
    assert exc.value.error.code == "FORBIDDEN"


async def test_step_document_and_role_are_protected(engine):
    ex = example()
    i = ex["ids"]
    await run(*ex["ops"])
    with pytest.raises(PipelineError) as exc:
        await run({"op": "doc.delete", "doc": i["s2"]})
    assert exc.value.error.code == "IN_USE"
    with pytest.raises(PipelineError) as exc:
        await run({"op": "role.delete", "role": i["tl"]})
    assert exc.value.error.code == "IN_USE"


async def test_delete_rules(engine):
    ex = example()
    i = ex["ids"]
    await run(*ex["ops"], {"op": "workflow.publish", "workflow": i["wf"]})
    launcher_doc, launcher_block = zid("doc"), zid("blk")
    await run({"op": "doc.create", "id": launcher_doc, "title": "Einkauf", "blocks": [
        {"id": launcher_block, "type": "workflow", "props": {"workflow": i["wf_key"], "mode": "launcher"}}]})
    with pytest.raises(PipelineError) as exc:
        await run({"op": "workflow.delete", "workflow": i["wf"]})
    assert exc.value.error.code == "IN_USE" and launcher_block in exc.value.error.message
    await run({"op": "block.delete", "block": launcher_block})

    run_id = zid("run")
    async with engine.begin() as c:
        await c.execute(text("""INSERT INTO runs (id, workflow_id, version, title, status, current_step, started_by,
                                                  started_by_id) VALUES (:r, :w, 1, 'T', 'active', 'erfassen',
                                                  CAST(:a AS jsonb), :u)"""),
                        {"r": run_id, "w": i["wf"], "a": json.dumps({"type": "user", "id": ANNA.id}), "u": ANNA.id})
    with pytest.raises(PipelineError) as exc:
        await run({"op": "workflow.delete", "workflow": i["wf"]})
    assert exc.value.error.code == "IN_USE" and run_id in exc.value.error.details["runs"]
    async with engine.begin() as c:
        await c.execute(text("UPDATE runs SET status = 'completed' WHERE id = :r"), {"r": run_id})

    # in einem Batch: Workflow löschen, danach sind die Schritt-Dokumente frei
    await run({"op": "workflow.delete", "workflow": i["wf"]}, {"op": "doc.delete", "doc": i["s2"]})
    assert await q(engine, "SELECT 1 FROM workflows WHERE id = :i", i=i["wf"]) == []
    assert await q(engine, "SELECT 1 FROM workflow_versions WHERE workflow_id = :i", i=i["wf"]) == []
    assert await q(engine, "SELECT 1 FROM runs WHERE id = :r", r=run_id) == []
    assert await q(engine, """SELECT 1 FROM "references" WHERE source_kind = 'workflow' AND source_id = :i""",
                   i=i["wf"]) == []


# ── REST ─────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api(engine):
    sm = async_sessionmaker(engine, expire_on_commit=False)

    async def session():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[current_user] = lambda: CurrentUser(
        id=ANNA.id, name="Anna", email="anna@zz41.local", roles=["einkauf"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(current_user, None)


async def test_rest_list_get_and_validate(engine, api):
    ex = example()
    i = ex["ids"]
    await run(*ex["ops"])
    listed = (await api.get("/api/workflows")).json()
    assert any(w["id"] == i["wf"] and w["latest_version"] is None for w in listed)
    got = await api.get(f"/api/workflows/{i['wf_key']}")
    assert got.status_code == 200 and got.json()["draft"]["start"] == "erfassen"
    assert (await api.get("/api/workflows/gibtsnicht_zz41")).status_code == 404

    ok = (await api.post("/api/workflows/validate", json={"workflow": i["wf"]})).json()
    assert ok["ok"] is True
    assert any(x["code"] == "ROLE_EMPTY" for x in ok["issues"])
    await add_member(engine, BEN.id, i["tl"])
    ok = (await api.post("/api/workflows/validate", json={"workflow": i["wf"]})).json()
    assert ok == {"ok": True, "issues": []}

    bad = {**ex["definition"], "start": "erfasen"}
    res = (await api.post("/api/workflows/validate", json={"definition": bad})).json()
    assert res["ok"] is False and res["issues"][0]["code"] == "START_UNKNOWN"
    res = (await api.post("/api/workflows/validate", json={"definition": {"start": "a"}})).json()
    assert res["ok"] is False and {x["code"] for x in res["issues"]} == {"SCHEMA"}
    assert (await api.post("/api/workflows/validate", json={})).status_code == 422
