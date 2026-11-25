import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, current_user
from app.main import app



@pytest.fixture(autouse=True)
def _logged_in_user():
    """Die Stub-Endpunkte brauchen einen angemeldeten Nutzer; die DB-Anmeldung testet test_auth_stub.py."""
    app.dependency_overrides[current_user] = lambda: CurrentUser(
        id="usr_test", name="Test User", email="test@example.local", roles=["einkauf"]
    )
    yield
    app.dependency_overrides.pop(current_user, None)


client = TestClient(app)


@pytest.fixture(autouse=True)
def _stub_pipeline(monkeypatch):
    """POST /api/ops läuft seit 1.2 durch die echte Pipeline (Handler kommen mit 1.3/1.4). Diese Tests prüfen
    nur den Vertrag der Stubs und die Werkzeuge, nicht die Persistenz."""
    from app.api import routers
    from app.schemas.ops import BatchResult

    async def fake(batch, actor, session=None):
        return BatchResult(batch_id=batch.batch_id, seq={"workspace": 1}, results={})

    monkeypatch.setattr(routers, "apply_batch", fake)

GET_PATHS = [
    "/api/health", "/api/me", "/api/runs", "/api/runs/run_42", "/api/tasks", "/api/notifications",
    "/api/schema/ws-messages",
]


def test_get_stubs_respond_200():
    for p in GET_PATHS:
        assert client.get(p).status_code == 200, p


def test_chef_sees_task_ben_not():
    app.dependency_overrides[current_user] = lambda: CurrentUser(
        id="usr_chef", name="Chef", email="chef@example.local", roles=["chef"]
    )
    assert len(client.get("/api/tasks").json()) == 1
    app.dependency_overrides[current_user] = lambda: CurrentUser(
        id="usr_ben", name="Ben", email="ben@example.local", roles=["mitarbeiter"]
    )
    assert client.get("/api/tasks").json() == []


def test_apply_ops_stub_validates_batch():
    ok = client.post("/api/ops", json={"batch_id": "b1", "ops": [
        {"op": "row.update", "table": "bestellungen", "row": "row_b1", "values": {"status": "genehmigt"}}]})
    assert ok.status_code == 200
    bad = client.post("/api/ops", json={"batch_id": "b2", "ops": [{"op": "row.explode"}]})
    assert bad.status_code == 422


def test_ws_requires_token():
    """Seit 1.5 braucht /ws ein gültiges JWT; die Verteilung testet test_realtime.py."""
    from starlette.websockets import WebSocketDisconnect

    with client.websocket_connect("/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_openapi_contains_contract():
    comps = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ["OpBatch", "WsMessages", "RunStatusView", "TaskDetail", "ImportPlan"]:
        assert any(k == name or k.startswith(name + "-") for k in comps), name


def test_openapi_contains_ws_snapshots():
    comps = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ["SnapshotDoc", "SnapshotTable", "SnapshotRun", "SnapshotUser", "SnapshotWorkspace"]:
        assert any(k == name or k.startswith(name + "-") for k in comps), name
