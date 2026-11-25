import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import CurrentUser, current_user, require_role

app = FastAPI()


@app.get("/me")
async def me(u: CurrentUser = Depends(current_user)):
    return u


@app.get("/einkauf")
async def einkauf(u: CurrentUser = Depends(require_role("einkauf"))):
    return u.id


client = TestClient(app)


def test_default_is_anna():
    assert client.get("/me").json()["id"] == "usr_anna"


@pytest.mark.parametrize("who,role", [("ben", "mitarbeiter"), ("chef", "chef")])
def test_header_switches_user(who, role):
    assert client.get("/me", headers={"X-Demo-User": who}).json()["roles"] == [role]


def test_role_check():
    assert client.get("/einkauf").status_code == 200
    assert client.get("/einkauf", headers={"X-Demo-User": "ben"}).status_code == 403
    assert client.get("/me", headers={"X-Demo-User": "x"}).status_code == 401
