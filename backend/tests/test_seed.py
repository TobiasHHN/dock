"""Test des Demo-Seeds (Task 5.5). Läuft gegen Postgres (Host-Port 5433); überspringt, wenn nicht erreichbar."""
import asyncio
import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock")
SEED_PATH = Path(__file__).resolve().parents[2] / "demo" / "seed.py"


def _load_seed():
    spec = importlib.util.spec_from_file_location("demo_seed", SEED_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["demo_seed"] = mod
    spec.loader.exec_module(mod)
    return mod


seed = _load_seed()


async def _reachable() -> bool:
    engine = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


if not asyncio.run(_reachable()):
    pytest.skip("Postgres nicht erreichbar", allow_module_level=True)


async def _scenario(tmp: Path):
    """Seed zweimal ausführen und danach alles in EINEM Event-Loop prüfen (die App-Engine ist loop-gebunden)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import get_session
    from app.main import app
    from app.ops import pipeline

    app_engine = create_async_engine(DB_URL, poolclass=NullPool)
    maker = async_sessionmaker(app_engine, expire_on_commit=False)

    async def _session():
        async with maker() as sess:
            yield sess

    app.dependency_overrides[get_session] = _session
    old_maker, pipeline.SessionLocal = pipeline.SessionLocal, maker

    os.environ["DATABASE_URL"] = DB_URL
    mcp = {"anna": tmp / "anna.json", "ben": tmp / "ben.json"}
    await seed.main([], tmp / "tokens.json", mcp)
    tokens = await seed.main([], tmp / "tokens.json", mcp)

    out: dict = {"tokens": tokens}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        def h(tok):
            return {"Authorization": f"Bearer {tok}"}

        out["ben_me"] = await c.get("/api/me", headers=h(tokens["ben"]["user_token"]))
        batch = {"batch_id": f"b_zz55{uuid.uuid4().hex[:8]}", "base": {}, "ops": [
            {"op": "table.create", "id": "tbl_zz55x", "key": "zz55x", "name": "x", "columns": []}]}
        out["ben_ops"] = await c.post("/api/ops", headers=h(tokens["ben"]["agent_token"]), json=batch)
        out["anna_agent_me"] = await c.get("/api/me", headers=h(tokens["anna"]["agent_token"]))
        out["login"] = await c.post("/api/auth/login", json={"email": "chef@demo.local", "password": "demo"})

    engine = create_async_engine(DB_URL, poolclass=NullPool)
    async with engine.connect() as conn:
        async def scalar(sql):
            return (await conn.execute(text(sql))).scalar()
        out["counts"] = (
            await scalar("SELECT count(*) FROM users WHERE email LIKE '%@demo.local'"),
            await scalar("SELECT count(*) FROM roles WHERE workspace_id='ws_demo' AND key IN ('einkauf','mitarbeiter','chef')"),
            await scalar("SELECT count(*) FROM agents WHERE id IN ('agt_anna_assistent','agt_ben_assistent')"),
            await scalar("SELECT count(*) FROM member_roles WHERE member_id IN ('usr_anna','usr_ben','usr_chef')"),
        )
    await engine.dispose()
    await app_engine.dispose()
    app.dependency_overrides.pop(get_session, None)
    pipeline.SessionLocal = old_maker
    return out


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("seed")
    out = asyncio.run(_scenario(tmp))
    out["tmp"] = tmp
    return out


def test_idempotent_rows(result):
    assert result["counts"] == (3, 3, 2, 3)


def test_ben_token_and_forbidden_table_create(result):
    assert result["ben_me"].status_code == 200
    body = result["ben_me"].json()
    assert body["name"] == "Ben Mitarbeiter" and body["roles"] == ["mitarbeiter"]
    assert result["ben_ops"].status_code == 403


def test_anna_agent_token_acts_on_behalf(result):
    r = result["anna_agent_me"]
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "usr_anna" and body["roles"] == ["einkauf"]
    # /api/me gibt den Akteur nicht aus (Vertrag unverändert), daher die Claims des Tokens prüfen.
    import jwt
    claims = jwt.decode(result["tokens"]["anna"]["agent_token"], options={"verify_signature": False})
    assert claims["act"] == {"type": "agent", "id": "agt_anna_assistent", "on_behalf_of": "usr_anna"}
    assert claims["exp"] - claims["iat"] == 7 * 24 * 3600


def test_login_with_seeded_password(result):
    r = result["login"]
    assert r.status_code == 200 and r.json()["user"]["roles"] == ["chef"]


def test_mcp_configs(result):
    t, tmp = result["tokens"], result["tmp"]
    for key in ("anna", "ben"):
        srv = json.loads((tmp / f"{key}.json").read_text(encoding="utf-8"))["mcpServers"]["dock"]
        assert srv["type"] == "http" and srv["url"] == "http://localhost:8000/mcp"
        assert srv["headers"]["Authorization"] == f"Bearer {t[key]['agent_token']}"
    assert set(json.loads((tmp / "tokens.json").read_text(encoding="utf-8"))) == {"anna", "ben", "chef"}
