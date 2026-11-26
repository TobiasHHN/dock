"""Eigene Test-Datenbank (`dock_test`) statt der Demo-Datenbank `dock`.

Die Tests schreiben über die echte Op-Pipeline ins Op-Log und lösen `pg_notify` aus. Liefen sie gegen `dock`, bekämen
offene Browser die Test-Dokumente live geschickt („Geister-Dokumente“, die nach dem Neuladen verschwinden, B26).

Standard: `postgresql+asyncpg://dock:dock@localhost:5433/dock_test`, überschreibbar mit TEST_DATABASE_URL. Die Datenbank
wird bei Bedarf angelegt und mit `db/init.sql` aufgesetzt; ändert sich `init.sql`, wird sie neu erzeugt.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

INIT_SQL = Path(__file__).resolve().parents[2] / "db" / "init.sql"
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock_test")

# Vor dem ersten Import von `app.config`: auch Code, der DATABASE_URL liest, landet in der Test-Datenbank.
os.environ["TEST_DATABASE_URL"] = TEST_DB_URL
os.environ["DATABASE_URL"] = TEST_DB_URL


def _dsn(url: str, db: str | None = None) -> str:
    parts = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://"))
    return urlunsplit(parts._replace(path=f"/{db}")) if db else urlunsplit(parts)


async def _prepare() -> None:
    import asyncpg

    name = urlsplit(TEST_DB_URL).path.lstrip("/")
    if name == "dock":
        raise RuntimeError("TEST_DATABASE_URL zeigt auf die Demo-Datenbank 'dock'. Bitte eine eigene Datenbank nehmen.")
    digest = hashlib.sha256(INIT_SQL.read_bytes()).hexdigest()
    try:
        admin = await asyncpg.connect(_dsn(TEST_DB_URL, "postgres"), timeout=5)
    except Exception:
        return  # Postgres nicht erreichbar: DB-Tests überspringen sich selbst
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if exists:
            conn = await asyncpg.connect(_dsn(TEST_DB_URL))
            try:
                current = await conn.fetchval(
                    "SELECT hash FROM _test_schema LIMIT 1") if await conn.fetchval(
                    "SELECT to_regclass('_test_schema') IS NOT NULL") else None
            finally:
                await conn.close()
            if current == digest:
                return
            await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    conn = await asyncpg.connect(_dsn(TEST_DB_URL))
    try:
        await conn.execute(INIT_SQL.read_text(encoding="utf-8"))
        await conn.execute("CREATE TABLE _test_schema (hash text NOT NULL)")
        await conn.execute("INSERT INTO _test_schema VALUES ($1)", digest)
    finally:
        await conn.close()


asyncio.run(_prepare())
