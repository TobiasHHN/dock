"""MCP-Server (Task 5.3): alle Tools aus L 8.1 gegen die REST-Stubs."""
import base64
import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException, Request
from mcp.shared.memory import create_connected_server_and_client_session

from app.auth import CurrentUser, current_user
from app.db.session import get_session
from app.main import app
from app.mcp.server import mcp

FILES = Path(__file__).resolve().parents[2] / "spec" / "fixtures" / "files"

EXPECTED_TOOLS = {
    "search", "list_tables", "get_table", "query_rows", "create_table", "update_table", "add_column",
    "update_column", "delete_column", "insert_rows", "update_row", "delete_rows", "get_document",
    "create_document", "edit_document", "import_xlsx", "import_docx", "validate_form", "list_workflows",
    "get_workflow", "create_workflow", "update_workflow", "validate_workflow", "publish_workflow", "delete_workflow", "start_run",
    "list_runs", "get_run", "cancel_run", "comment_run", "list_tasks", "get_task", "claim_task", "release_task",
    "reassign_task", "complete_task", "list_roles", "list_users", "create_role", "set_user_roles",
    "set_agent_roles", "apply_ops", "describe_schema", "generate_ids", "get_workflow_playbook",
}

COL = {"key": "name", "name": "Name", "type": {"kind": "text"}}
DEFINITION = {
    "start": "s1",
    "steps": [{"key": "s1", "name": "Erfassen", "document": "doc_s1", "assignees": [{"kind": "starter"}]}],
    "transitions": [],
}

CALLS = [
    ("search", {"query": "Bestellung", "kinds": ["workflow"]}),
    ("list_tables", {}),
    ("get_table", {"table": "bestellungen"}),
    ("query_rows", {"table": "bestellungen", "filter": [{"column": "status", "op": "eq", "value": "offen"}],
                    "sort": [{"column": "name"}], "limit": 5}),
    ("create_table", {"key": "t", "name": "T", "columns": [COL]}),
    ("update_table", {"table": "t", "name": "T2"}),
    ("add_column", {"table": "t", "column": {"key": "x", "name": "X", "type": {"kind": "integer"}}}),
    ("update_column", {"table": "t", "column": "x", "patch": {"name": "XX"}}),
    ("delete_column", {"table": "t", "column": "x"}),
    ("insert_rows", {"table": "t", "rows": [{"name": "a"}, {"name": "b"}]}),
    ("update_row", {"table": "t", "row": "row_1", "values": {"name": "c"}}),
    ("delete_rows", {"table": "t", "rows": ["row_1"]}),
    ("get_document", {"doc": "doc_s1"}),
    ("get_document", {"doc": "doc_s1", "format": "json", "run": "run_42"}),
    ("create_document", {"title": "Neu", "markdown": "# Neu {#blk_h1}"}),
    ("edit_document", {"doc": "doc_s1", "base_version": {"blk_a": 1},
                       "ops": [{"op": "block.update", "block": "blk_a", "props": {"level": 2}}]}),
    ("validate_form", {"doc": "doc_s1", "block": "blk_form"}),
    ("list_workflows", {}),
    ("get_workflow", {"workflow": "bestellprozess"}),
    ("create_workflow", {"key": "w", "name": "W", "definition": DEFINITION}),
    ("update_workflow", {"workflow": "w", "definition": DEFINITION}),
    ("validate_workflow", {"workflow": "bestellprozess"}),
    ("validate_workflow", {"definition": DEFINITION}),
    ("publish_workflow", {"workflow": "w"}),
    ("delete_workflow", {"workflow": "bestellprozess"}),
    ("start_run", {"workflow": "bestellprozess", "input": {"x": 1}}),
    ("list_runs", {"status": "active"}),
    ("get_run", {"run": "run_42"}),
    ("cancel_run", {"run": "run_42", "reason": "Test"}),
    ("comment_run", {"run": "run_42", "text": "Hallo"}),
    ("list_tasks", {}),
    ("get_task", {"task": "tsk_2"}),
    ("claim_task", {"task": "tsk_2"}),
    ("release_task", {"task": "tsk_2"}),
    ("reassign_task", {"task": "tsk_2", "assignees": [{"kind": "role", "role": "chef"}]}),
    ("complete_task", {"task": "tsk_2", "button": "approve", "values": {"kommentar": "Passt."}}),
    ("describe_schema", {"topic": "ops"}),
    ("generate_ids", {"requests": [{"name": "workflow", "kind": "workflow"}]}),
    ("get_workflow_playbook", {}),
    ("list_roles", {}),
    ("list_users", {"role": "chef"}),
    ("create_role", {"key": "r", "name": "R"}),
    ("set_user_roles", {"user": "usr_ben", "add": ["chef"]}),
    ("set_agent_roles", {"agent": "agt_1", "add": ["einkauf"]}),
    ("apply_ops", {"batch": {"batch_id": "b1", "ops": [
        {"op": "row.update", "table": "bestellungen", "row": "row_b1", "values": {"status": "genehmigt"}}]}}),
]


def _text(res) -> str:
    return "".join(c.text for c in res.content if getattr(c, "type", "") == "text")


async def _call(name, args):
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        return await client.call_tool(name, args)


_TEST_USERS = {
    "anna": CurrentUser(id="usr_anna", name="Anna", email="anna@example.local", roles=["einkauf"]),
    "chef": CurrentUser(id="usr_chef", name="Chef", email="chef@example.local", roles=["chef"]),
}


async def _user_from_test_token(request: Request) -> CurrentUser:
    """Ersetzt die DB-Anmeldung: der Bearer-Wert ist der Testnutzer (der MCP-Server reicht ihn aus DOCK_TOKEN weiter)."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or token not in _TEST_USERS:
        raise HTTPException(status_code=401, detail="Nicht angemeldet")
    return _TEST_USERS[token]


class _EmptyResult:
    def mappings(self):
        return self

    def all(self):
        return []


class _EmptySession:
    async def execute(self, *args, **kwargs):
        return _EmptyResult()

    async def commit(self):
        pass


async def _empty_session():
    yield _EmptySession()


@pytest.fixture(autouse=True)
def _demo_user(monkeypatch):
    monkeypatch.setenv("DOCK_TOKEN", "chef")
    app.dependency_overrides[current_user] = _user_from_test_token
    app.dependency_overrides[get_session] = _empty_session  # list_roles/list_users lesen jetzt aus der DB
    yield
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture(autouse=True)
def _stub_search(monkeypatch):
    """Die Suche (5.2) braucht Modell und DB; dieser Test prüft nur das MCP-Werkzeug `search` und den Pfad."""
    from app.schemas.api import SearchHit, SearchResponse
    from app.search import search as search_mod

    async def fake(query, actor, kinds=None, limit=10):
        return SearchResponse(query=query, hits=[SearchHit(
            kind="workflow", id="wf_best", title="Bestellprozess", snippet="Bestellung erfassen …", score=0.9)])

    monkeypatch.setattr(search_mod, "hybrid_search", fake)


@pytest.fixture(autouse=True)
def _stub_reads(monkeypatch):
    """Dokument-, Tabellen- und Workflow-Lesezugriffe sind seit 1.4/4.1 echt (DB); dieser Test prüft nur die MCP-Werkzeuge,
    deshalb liefern die Abfragen hier die Beispieldaten aus `stub_data`."""
    from app.api import stub_data as D
    from app.domain import queries
    from app.ops.errors import PipelineError

    def table(ref):
        found = next((t for t in D.TABLES if ref in (t.id, t.key)), None)
        if found is None:
            raise PipelineError("NOT_FOUND", f"Tabelle '{ref}' wurde nicht gefunden")
        return found

    def doc(ref):
        if ref not in D.DOCS:
            raise PipelineError("NOT_FOUND", f"Dokument '{ref}' wurde nicht gefunden")
        return D.DOCS[ref]

    async def list_tables(s):
        return [t.model_dump() for t in D.TABLES]

    async def fetch_table(s, ref):
        return table(ref).model_dump()

    async def query_rows(s, ref, filters, sorts, limit=100, offset=0, context=None):
        t = table(ref)
        rows = D.ROWS.get(t.id, [])
        return {"table": t.id, "rows": [r.model_dump() for r in rows], "total": len(rows)}

    async def fetch_document(s, ref, run=None, user=None):
        d, blocks = doc(ref)
        return {"document": d.model_dump(), "blocks": [b.model_dump() for b in blocks]}

    async def fetch_document_markdown(s, ref, run=None, user=None):
        d, _ = doc(ref)
        return {"document": d.model_dump(), "markdown": f"# {d.title} {{#blk_h1}}\n"}

    async def list_documents(s):
        return [d.model_dump() for d, _ in D.DOCS.values()]

    async def list_workflows(s):
        w = D.WORKFLOW
        return [{"id": w.id, "key": w.key, "name": w.name, "latest_version": w.latest_version}]

    async def fetch_workflow(s, ref):
        if ref not in (D.WORKFLOW.id, D.WORKFLOW.key):
            raise PipelineError("NOT_FOUND", f"Workflow '{ref}' wurde nicht gefunden")
        return D.WORKFLOW.model_dump(by_alias=True)

    async def validate_workflow(s, actor, workflow, definition):
        return {"ok": True, "issues": []}

    for name, fn in [("list_workflows", list_workflows), ("fetch_workflow", fetch_workflow),
                     ("validate_workflow", validate_workflow), ("list_tables", list_tables), ("fetch_table", fetch_table), ("query_rows", query_rows),
                     ("fetch_document", fetch_document), ("fetch_document_markdown", fetch_document_markdown),
                     ("list_documents", list_documents)]:
        monkeypatch.setattr(queries, name, fn)

    async def validate_form_in_db(s, doc_id, block):
        return {"ok": True, "warnings": []}

    from app.domain import forms, run_status
    from app.schemas.workflows import ButtonInfo, Notification, TaskDetail, TaskListItem
    monkeypatch.setattr(forms, "validate_form_in_db", validate_form_in_db)

    async def list_runs(s, viewer, workflow=None, started_by="me", status=None):
        return D.RUN_LIST

    async def build_status_view(ctx, run_id, viewer):
        return D.RUN_STATUS

    async def list_tasks(s, viewer, assigned_to="me", status="open", workflow=None):
        can = viewer.id != D.ANNA.id
        return [TaskListItem(task=D.TASK_OPEN, run_title=D.RUN_STATUS.title, step_name="Genehmigung",
                             workflow_name="Bestellprozess", can_act=can)] if can else []

    async def get_task_detail(s, task_id, user):
        return TaskDetail(
            task=D.TASK_OPEN, run_title=D.RUN_STATUS.title, document_id="doc_s2",
            document_markdown="# Genehmigung {#blk_s2_h}\n\nBestellung von Ben Mitarbeiter für Kostenstelle 4711.",
            form_block="blk_s2_form",
            buttons=[ButtonInfo(id="approve", label="Genehmigt", style="primary", outcome="approved"),
                     ButtonInfo(id="reject", label="Abgelehnt", style="danger", outcome="rejected",
                                require=["kommentar"])],
            fields=[{"key": "kommentar", "label": "Kommentar", "input": "textarea", "required": False}],
            can_act="chef" in user.roles,
        )

    async def list_notifications(s, viewer, unread=False):
        return []

    async def mark_notification_read(s, nid, viewer):
        return Notification(id=nid, recipient_id=viewer.id, type="step_entered", created_at=D.T1, read_at=D.T1)

    for name, fn in [("list_runs", list_runs), ("build_status_view", build_status_view),
                     ("list_tasks", list_tasks), ("get_task_detail", get_task_detail),
                     ("list_notifications", list_notifications), ("mark_notification_read", mark_notification_read)]:
        monkeypatch.setattr(run_status, name, fn)


@pytest.fixture(autouse=True)
def _stub_pipeline(monkeypatch):
    """POST /api/ops läuft seit 1.2 durch die echte Pipeline (Handler kommen mit 1.3/1.4). Diese Tests prüfen
    nur den Vertrag der Stubs und die Werkzeuge, nicht die Persistenz."""
    from app.api import routers
    from app.schemas.ops import BatchResult

    async def fake(batch, actor, session=None):
        return BatchResult(batch_id=batch.batch_id, seq={"workspace": 1}, results={})

    monkeypatch.setattr(routers, "apply_batch", fake)


async def test_exact_tool_set():
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == EXPECTED_TOOLS
    apply = next(t for t in tools if t.name == "apply_ops")
    assert "describe_schema" in json.dumps(apply.inputSchema)  # schlankes Schema verweist auf die Doku (B12)


async def test_big_tool_schemas_stay_small():
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in ("apply_ops", "edit_document", "create_document"):
        assert len(json.dumps(tools[name].inputSchema)) < 5000, name


async def test_describe_schema():
    res = await _call("describe_schema", {"topic": "ops"})
    assert not res.isError and "row.update" in _text(res) and "block.insert" in _text(res)
    res = await _call("describe_schema", {"topic": "blocks"})
    assert not res.isError and "form" in _text(res) and "paragraph" in _text(res)
    res = await _call("describe_schema", {"topic": "row.update"})
    assert not res.isError and "values" in _text(res)
    res = await _call("describe_schema", {"topic": "form"})
    assert not res.isError and "props" in _text(res)
    res = await _call("describe_schema", {"topic": "gibtsnicht"})
    assert res.isError and "NOT_FOUND" in _text(res)


async def test_invalid_op_is_readable_error():
    res = await _call("apply_ops", {"batch": {"batch_id": "b", "ops": [{"op": "row.explode"}]}})
    assert res.isError and "VALIDATION at ops" in _text(res)


async def test_all_tools_against_stubs():
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        for name, args in CALLS:
            res = await client.call_tool(name, args)
            assert not res.isError, f"{name}: {_text(res)}"
    assert {n for n, _ in CALLS} | {"import_xlsx", "import_docx"} == EXPECTED_TOOLS


async def test_create_document_with_blocks():
    res = await _call("create_document", {"title": "Neu", "blocks": [
        {"id": "blk_a", "type": "paragraph", "props": {"content": [{"t": "text", "text": "Hallo"}]}}]})
    assert not res.isError, _text(res)


async def test_create_document_generates_nested_block_ids(monkeypatch):
    from app.mcp import server

    captured = []

    async def fake_ops(ctx, ops, base=None):
        captured.extend(ops)
        return {"ok": True}

    monkeypatch.setattr(server, "_ops", fake_ops)
    res = await _call("create_document", {"title": "Neu", "blocks": [
        {"type": "paragraph", "props": {"content": []}, "children": [
            {"type": "paragraph", "props": {"content": []}},
        ]},
    ]})
    assert not res.isError, _text(res)
    blocks = captured[0]["blocks"]
    assert blocks[0]["id"].startswith("blk_")
    assert blocks[0]["children"][0]["id"].startswith("blk_")
    assert blocks[0]["id"] != blocks[0]["children"][0]["id"]


async def test_generate_ids_and_workflow_playbook():
    res = await _call("generate_ids", {"requests": [
        {"name": "wf", "kind": "workflow"},
        {"name": "form", "kind": "block"},
    ]})
    assert not res.isError, _text(res)
    ids = json.loads(_text(res))["ids"]
    assert ids["wf"].startswith("wf_")
    assert ids["form"].startswith("blk_")
    assert ids["wf"] != ids["form"]

    duplicate = await _call("generate_ids", {"requests": [
        {"name": "same", "kind": "document"},
        {"name": "same", "kind": "block"},
    ]})
    assert duplicate.isError and "eindeutig" in _text(duplicate)

    guide = await _call("get_workflow_playbook", {})
    assert not guide.isError
    assert "exclude_starter: true" in _text(guide)
    assert 'require: ["kommentar"]' in _text(guide)
    assert "publish_workflow" in _text(guide)


async def test_identity_is_forwarded(monkeypatch):
    res = await _call("list_tasks", {})
    assert json.loads(res.content[0].text)["task"]["id"] == "tsk_2"  # chef sieht die Aufgabe
    monkeypatch.setenv("DOCK_TOKEN", "anna")  # Anna sieht keine Aufgabe
    assert (await _call("list_tasks", {})).content == []


async def test_imports_file_path_and_base64(monkeypatch):
    from app.api import routers
    from app.schemas.api import ImportPlan

    async def fake_prepare(source, result, user, session, apply):  # Speichern/Ausführen braucht die DB (test_import_xlsx)
        return ImportPlan(import_id="imp_stub", created=result.created, warnings=result.warnings)

    monkeypatch.setattr(routers, "_prepare_import", fake_prepare)
    xlsx = FILES / "uebersicht.xlsx"
    docx = FILES / "formular.docx"
    for name, args in [
        ("import_xlsx", {"file_path": str(xlsx), "sheet": "Bestellungen", "apply": True}),
        ("import_xlsx", {"content_base64": base64.b64encode(xlsx.read_bytes()).decode(), "filename": "u.xlsx"}),
        ("import_docx", {"file_path": str(docx), "title": "F", "bind_table": "bestellungen"}),
    ]:
        res = await _call(name, args)
        assert not res.isError, _text(res)
        assert json.loads(_text(res))["import_id"] == "imp_stub"


async def test_import_argument_errors():
    res = await _call("import_xlsx", {})
    assert res.isError and "file_path|content_base64" in _text(res)
    res = await _call("import_docx", {"file_path": "/nicht/da.docx"})
    assert res.isError and "NOT_FOUND" in _text(res) and "content_base64" in _text(res)  # B11: Hinweis auf Ausweg


async def test_file_path_falls_back_to_demo_dir(monkeypatch):
    from app.mcp.server import _read_upload

    monkeypatch.setenv("DOCK_DEMO_DIR", str(FILES))  # Host-Pfad existiert nicht, gleicher Dateiname im demo-Verzeichnis
    name, content = _read_upload(r"C:\Users\x\demo\uebersicht.xlsx", None, None)
    assert name == "uebersicht.xlsx" and content == (FILES / "uebersicht.xlsx").read_bytes()


async def test_error_paths_are_readable():
    res = await _call("get_table", {"table": "gibtsnicht"})
    assert res.isError and "NOT_FOUND" in _text(res) and "gibtsnicht" in _text(res)
    res = await _call("complete_task", {"task": "tsk_2", "button": "boom"})
    assert res.isError and "button" in _text(res) and "approve" in _text(res)
    res = await _call("edit_document", {"doc": "d", "ops": [{"op": "table.delete", "table": "t"}]})
    assert res.isError and "ops[0].op" in _text(res)
    res = await _call("create_document", {"title": "x"})
    assert res.isError and "markdown|blocks" in _text(res)


async def test_pipeline_rejections_become_tool_errors(monkeypatch):
    from app.mcp import server as S

    async def fake(ctx, method, path, **kw):
        return {"batch_id": "b", "error": {"code": "CONFLICT", "message": "veraltet",
                                          "details": {"errors": {"ops[2].base_version": "Block blk_x ist bei v5"}}}}

    monkeypatch.setattr(S, "_request", fake)
    res = await _call("update_row", {"table": "t", "row": "r", "values": {}})
    assert res.isError and "CONFLICT at ops[2].base_version: Block blk_x ist bei v5" in _text(res)


def test_error_text_formats():
    from app.mcp.server import _error_text

    assert _error_text(422, {"detail": [{"loc": ["body", "ops", 0, "op"], "msg": "bad"}]}) == "VALIDATION at ops.0.op: bad"
    assert _error_text(409, {"error": {"code": "IN_USE", "message": "belegt", "details": {"uses": ["a"]}}}).startswith("IN_USE: belegt")
    assert _error_text(403, {"detail": "nein"}) == "FORBIDDEN: nein"


async def test_rest_validation_error_has_path():
    from app.mcp import server as S

    with pytest.raises(Exception) as e:
        await S._request(None, "POST", "/api/ops", json={"batch_id": "b", "ops": [{"op": "row.explode"}]})
    assert "VALIDATION at ops.0" in str(e.value)


async def test_http_mount_reachable():
    from app.main import app

    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}}}
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.get("/api/health")).json() == {"status": "ok"}
            for path in ("/mcp", "/mcp/"):
                r = await c.post(path, json=init, headers=headers)
                assert r.status_code == 200, (path, r.status_code, r.text)
                assert "dock" in r.text


def test_lifespan_restartable():
    """Mehrere Lifespans im selben Prozess (z. B. mehrere `with TestClient(app)`) dürfen nicht scheitern."""
    from fastapi.testclient import TestClient

    from app.main import app

    for _ in range(2):
        with TestClient(app) as c:
            assert c.get("/api/health").status_code == 200
