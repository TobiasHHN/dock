from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import CurrentUser, create_access_token, current_user, hash_password, require_role, verify_password
from app.db.session import get_session
from app.api.routers import auth
from app.schemas.common import Actor


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self):
        self.users = {}
        self.roles = {}
        self.memberships = {}
        self.agents = {"agt_demo": {"name": "Demo Agent", "active": True}}

    @asynccontextmanager
    async def begin(self):
        yield self

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        if "SELECT 1 FROM users WHERE email" in sql:
            return FakeResult([{}] if any(u["email"] == params["email"] for u in self.users.values()) else [])
        if "INSERT INTO roles" in sql:
            self.roles.setdefault(params["key"], {"id": params["id"], "name": params["name"]})
            return FakeResult([])
        if "SELECT id FROM roles" in sql:
            role = self.roles.get(params["key"])
            return FakeResult([{"id": role["id"]}] if role else [])
        if "INSERT INTO users" in sql:
            self.users[params["id"]] = {
                "id": params["id"], "name": params["name"], "email": params["email"],
                "password_hash": params["password_hash"], "active": True,
            }
            return FakeResult([])
        if "INSERT INTO member_roles" in sql:
            role = next(key for key, value in self.roles.items() if value["id"] == params["role_id"])
            self.memberships.setdefault(params["user_id"], []).append(role)
            return FakeResult([])
        if "FROM users WHERE email" in sql:
            user = next((u for u in self.users.values() if u["email"] == params["email"]), None)
            return FakeResult([user] if user else [])
        if "SELECT r.key FROM roles" in sql:
            return FakeResult([{"key": role} for role in sorted(self.memberships.get(params["user_id"], []))])
        if "FROM users AS u" in sql and "WHERE u.id = :user_id" in sql:
            user = self.users.get(params["user_id"])
            if not user:
                return FakeResult([])
            return FakeResult([{
                **user,
                "roles": sorted(self.memberships.get(user["id"], [])),
            }])
        if "FROM agents WHERE id = :agent_id" in sql:
            agent = self.agents.get(params["agent_id"])
            return FakeResult([agent] if agent else [])
        raise AssertionError(f"Unexpected query: {sql}")


fake_session = FakeSession()


async def override_session():
    yield fake_session


test_app = FastAPI()
test_app.include_router(auth)
test_app.dependency_overrides[get_session] = override_session


@test_app.get("/test/auth-user")
async def auth_user(user: CurrentUser = Depends(current_user)):
    return {"id": user.id, "roles": user.roles, "actor": user.actor.model_dump()}


@test_app.get("/test/einkauf")
async def einkauf(user: CurrentUser = Depends(require_role("einkauf"))):
    return {"id": user.id}


client = TestClient(test_app)


def test_signup_and_login_issue_role_bearing_tokens_and_role_guard_403():
    credentials = [
        ("anna@demo.local", "Anna Beispiel", "einkauf"),
        ("ben@demo.local", "Ben Mitarbeiter", "mitarbeiter"),
        ("chef@demo.local", "Chef Teamleiter", "chef"),
    ]
    tokens = {}
    for email, name, role in credentials:
        signup = client.post("/api/auth/signup", json={
            "email": email, "name": name, "password": "demo-password", "role": role,
        })
        assert signup.status_code == 200
        assert signup.json()["user"]["roles"] == [role]
        tokens[role] = signup.json()["access_token"]

        login = client.post("/api/auth/login", json={"email": email, "password": "demo-password"})
        assert login.status_code == 200
        assert login.json()["user"]["roles"] == [role]

    assert client.get("/test/einkauf", headers={"Authorization": f"Bearer {tokens['einkauf']}"}).status_code == 200
    assert client.get("/test/einkauf", headers={"Authorization": f"Bearer {tokens['mitarbeiter']}"}).status_code == 403
    assert client.get("/test/einkauf", headers={"Authorization": f"Bearer {tokens['chef']}"}).status_code == 403


def test_auth_requires_bearer_and_ignores_demo_user_header():
    assert client.get("/test/auth-user").status_code == 401
    assert client.get("/test/auth-user", headers={"X-Demo-User": "chef"}).status_code == 401
    assert client.get("/test/auth-user", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_signed_agent_claim_is_checked_and_builds_on_behalf_actor():
    user = fake_session.users[next(uid for uid, row in fake_session.users.items() if row["email"] == "ben@demo.local")]
    token = create_access_token(
        user["id"], ["mitarbeiter"], actor=Actor(type="agent", id="agt_demo", on_behalf_of=user["id"]),
    )
    response = client.get("/test/auth-user", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["actor"] == {
        "type": "agent", "id": "agt_demo", "on_behalf_of": user["id"], "name": "Demo Agent",
    }


def test_password_hash_is_salted_and_verified():
    first = hash_password("demo-password")
    second = hash_password("demo-password")
    assert first != second
    assert verify_password("demo-password", first)
    assert not verify_password("wrong-password", first)
    assert not verify_password("demo-password", "malformed")
