from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

GET_PATHS = [
    "/api/health", "/api/me", "/api/roles", "/api/users", "/api/documents", "/api/documents/doc_s1",
    "/api/documents/doc_s1/markdown", "/api/tables", "/api/tables/bestellungen", "/api/workflows",
    "/api/workflows/bestellprozess", "/api/runs", "/api/runs/run_42", "/api/tasks", "/api/notifications",
    "/api/search?q=Bestellung", "/api/schema/ws-messages",
]


def test_get_stubs_respond_200():
    for p in GET_PATHS:
        assert client.get(p).status_code == 200, p


def test_chef_sees_task_ben_not():
    assert len(client.get("/api/tasks", headers={"X-Demo-User": "chef"}).json()) == 1
    assert client.get("/api/tasks", headers={"X-Demo-User": "ben"}).json() == []


def test_apply_ops_stub_validates_batch():
    ok = client.post("/api/ops", json={"batch_id": "b1", "ops": [
        {"op": "row.update", "table": "bestellungen", "row": "row_b1", "values": {"status": "genehmigt"}}]})
    assert ok.status_code == 200
    bad = client.post("/api/ops", json={"batch_id": "b2", "ops": [{"op": "row.explode"}]})
    assert bad.status_code == 422


def test_ws_stub():
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "subscribe", "channel": "doc:doc_s1"})
        assert ws.receive_json()["type"] == "snapshot"


def test_openapi_contains_contract():
    comps = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ["OpBatch", "WsMessages", "RunStatusView", "TaskDetail", "ImportPlan"]:
        assert any(k == name or k.startswith(name + "-") for k in comps), name
