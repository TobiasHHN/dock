"""MCP-Server (Task 5.3): alle Tools aus L 8.1 gegen die REST-Stubs."""
import base64
import json
import os
from pathlib import Path

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from app.mcp.server import mcp

FILES = Path(__file__).resolve().parents[2] / "spec" / "fixtures" / "files"

EXPECTED_TOOLS = {
    "search", "list_tables", "get_table", "query_rows", "create_table", "update_table", "add_column",
    "update_column", "delete_column", "insert_rows", "update_row", "delete_rows", "get_document",
    "create_document", "edit_document", "import_xlsx", "import_docx", "validate_form", "list_workflows",
    "get_workflow", "create_workflow", "update_workflow", "validate_workflow", "publish_workflow", "start_run",
    "list_runs", "get_run", "cancel_run", "comment_run", "list_tasks", "get_task", "claim_task", "release_task",
    "reassign_task", "complete_task", "list_roles", "list_users", "create_role", "set_user_roles",
    "set_agent_roles", "apply_ops",
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


@pytest.fixture(autouse=True)
def _demo_user(monkeypatch):
    monkeypatch.setenv("DOCK_DEMO_USER", "chef")


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
    assert "row.update" in json.dumps(apply.inputSchema)  # Schema stammt aus dem Pydantic-Vertrag


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


async def test_identity_is_forwarded(monkeypatch):
    res = await _call("list_tasks", {})
    assert json.loads(res.content[0].text)["task"]["id"] == "tsk_2"  # chef sieht die Aufgabe
    monkeypatch.delenv("DOCK_DEMO_USER")  # -> Default Anna, keine Aufgabe
    assert (await _call("list_tasks", {})).content == []


async def test_imports_file_path_and_base64():
    xlsx = FILES / "uebersicht.xlsx"
    docx = FILES / "formular.docx"
    for name, args in [
        ("import_xlsx", {"file_path": str(xlsx), "sheet": "Tabelle1", "apply": True}),
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
    assert res.isError and "NOT_FOUND" in _text(res)


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
