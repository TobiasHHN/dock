"""Demo-Seed (Task 5.5): Nutzer, Rollen, Agenten, Demo-Tokens und MCP-Konfigurationen.

Aufruf im Repo-Root: `backend/.venv/bin/python demo/seed.py [--fresh-tokens-only]`
Idempotent. DB: DATABASE_URL oder Host-Port 5433. JWT-Secret: JWT_SECRET bzw. Default aus `app.config`
(identisch mit dem Backend-Container in docker-compose.yml).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.auth import ROLE_NAMES, create_access_token, hash_password  # noqa: E402
from app.schemas.common import Actor  # noqa: E402

DEFAULT_DB_URL = "postgresql+asyncpg://dock:dock@localhost:5433/dock"
WS = "ws_demo"
PASSWORD = "demo"
TOKEN_TTL = timedelta(days=7)
MCP_URL = "http://localhost:8000/mcp"

# (user id, name, email, role key, agent id, agent name)
USERS = [
    ("usr_anna", "Anna Beispiel", "anna@demo.local", "einkauf", "agt_anna_assistent", "Annas Assistent"),
    ("usr_ben", "Ben Mitarbeiter", "ben@demo.local", "mitarbeiter", "agt_ben_assistent", "Bens Assistent"),
    ("usr_chef", "Chef Teamleiter", "chef@demo.local", "chef", "agt_chef_assistent", "Chefs Assistent"),
]
ROLE_IDS = {"einkauf": "rol_einkauf", "mitarbeiter": "rol_mitarbeiter", "chef": "rol_chef"}
OUT_TOKENS = ROOT / "demo" / ".tokens.json"
OUT_MCP = {"anna": ROOT / "demo" / "mcp" / "anna.json", "ben": ROOT / "demo" / "mcp" / "ben.json"}


def _static_users() -> dict[str, dict]:
    return {e.split("@")[0]: {"user_id": uid, "role": role, "agent_id": aid, "agent_name": an, "name": n, "email": e}
            for uid, n, e, role, aid, an in USERS}


async def seed_db(url: str) -> dict[str, dict]:
    """Legt Workspace, Rollen, Nutzer, Agenten an (Upsert) und liefert je Nutzer-Key die IDs."""
    engine = create_async_engine(url)
    result = _static_users()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO workspaces (id, name) VALUES (:id, 'Demo') ON CONFLICT (id) DO NOTHING"),
                               {"id": WS})
            role_ids: dict[str, str] = {}
            for key, name in ROLE_NAMES.items():
                await conn.execute(
                    text("""INSERT INTO roles (id, workspace_id, key, name) VALUES (:id, :ws, :key, :name)
                            ON CONFLICT (workspace_id, key) DO UPDATE SET name = EXCLUDED.name"""),
                    {"id": ROLE_IDS[key], "ws": WS, "key": key, "name": name})
                role_ids[key] = (await conn.execute(
                    text("SELECT id FROM roles WHERE workspace_id = :ws AND key = :key"),
                    {"ws": WS, "key": key})).scalar_one()
            for key, u in result.items():
                # Gibt es die E-Mail schon (z. B. per Signup), bleibt deren ID erhalten.
                existing = (await conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": u["email"]})).scalar()
                u["user_id"] = existing or u["user_id"]
                await conn.execute(
                    text("""INSERT INTO users (id, name, email, password_hash, active)
                            VALUES (:id, :name, :email, :ph, true)
                            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, email = EXCLUDED.email,
                              password_hash = EXCLUDED.password_hash, active = true"""),
                    {"id": u["user_id"], "name": u["name"], "email": u["email"], "ph": hash_password(PASSWORD)})
                await conn.execute(text("DELETE FROM member_roles WHERE workspace_id = :ws AND member_id = :m"),
                                   {"ws": WS, "m": u["user_id"]})
                await conn.execute(
                    text("INSERT INTO member_roles (workspace_id, member_id, role_id) VALUES (:ws, :m, :r)"),
                    {"ws": WS, "m": u["user_id"], "r": role_ids[u["role"]]})
                # Agenten handeln im Auftrag mit den Rollen der Person (L 5.8), brauchen keine eigene Mitgliedschaft.
                await conn.execute(
                    text("""INSERT INTO agents (id, workspace_id, name, active) VALUES (:id, :ws, :name, true)
                            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, active = true"""),
                    {"id": u["agent_id"], "ws": WS, "name": u["agent_name"]})
    finally:
        await engine.dispose()
    return result


def make_tokens(users: dict[str, dict], now: datetime | None = None) -> dict[str, dict]:
    now = now or datetime.now(timezone.utc)
    tokens: dict[str, dict] = {}
    for key, u in users.items():
        agent = Actor(type="agent", id=u["agent_id"], on_behalf_of=u["user_id"], name=u["agent_name"])
        tokens[key] = {
            "user_id": u["user_id"], "role": u["role"], "agent_id": u["agent_id"],
            "user_token": create_access_token(u["user_id"], [u["role"]], now=now, ttl=TOKEN_TTL),
            "agent_token": create_access_token(u["user_id"], [u["role"]], actor=agent, now=now, ttl=TOKEN_TTL),
            "expires_at": (now + TOKEN_TTL).isoformat(),
        }
    return tokens


def write_files(tokens: dict[str, dict], tokens_path: Path | None = None, mcp_paths: dict[str, Path] | None = None) -> None:
    tokens_path = tokens_path or OUT_TOKENS
    mcp_paths = mcp_paths or OUT_MCP
    tokens_path.write_text(json.dumps(tokens, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for key, path in mcp_paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        cfg = {"mcpServers": {"dock": {"type": "http", "url": MCP_URL,
                                       "headers": {"Authorization": f"Bearer {tokens[key]['agent_token']}"}}}}
        path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    for p in (tokens_path, *mcp_paths.values()):
        os.chmod(p, 0o600)


async def main(argv: list[str] | None = None, tokens_path: Path | None = None,
               mcp_paths: dict[str, Path] | None = None) -> dict[str, dict]:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fresh-tokens-only", action="store_true", help="nur Tokens und MCP-Konfigurationen neu schreiben")
    args = ap.parse_args(argv)
    url = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
    users = _static_users() if args.fresh_tokens_only else await seed_db(url)
    tokens = make_tokens(users)
    write_files(tokens, tokens_path, mcp_paths)
    print(f"Workspace {WS}: Rollen {', '.join(ROLE_NAMES)}; Passwort aller Demo-Nutzer: '{PASSWORD}'")
    for u in users.values():
        print(f"  {u['email']:<16} {u['name']:<16} {u['role']:<12} {u['user_id']}  Agent {u['agent_name']} ({u['agent_id']})")
    print(f"Tokens (7 Tage) gültig bis {next(iter(tokens.values()))['expires_at']}; JWT-Secret muss dem Backend entsprechen "
          f"({'aus JWT_SECRET' if os.environ.get('JWT_SECRET') else 'config-Default'})")
    print("Geschrieben: " + ", ".join(str(p.relative_to(ROOT)) for p in [OUT_TOKENS, *OUT_MCP.values()]))
    return tokens


if __name__ == "__main__":
    asyncio.run(main())
