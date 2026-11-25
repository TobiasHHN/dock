"""Hintergrundjobs (procrastinate, Queue liegt in Postgres).

- Worker: `python -m app.worker` (öffnet die App selbst, legt das procrastinate-Schema bei Bedarf an).
- Backend-Prozess: `enqueue_reembed` ruft `ensure_open()`, das die App beim ersten Aufruf einmal öffnet
  (Connection-Pool bleibt bis Prozessende offen; optional `await close()` beim Shutdown).
"""
from __future__ import annotations

import asyncio

from procrastinate import App, PsycopgConnector

from app.config import settings


def conninfo(url: str | None = None) -> str:
    """SQLAlchemy-URL (`postgresql+asyncpg://…`) in eine libpq-URL umwandeln."""
    url = url or settings.database_url
    return url.replace("+asyncpg", "", 1).replace("postgres+psycopg", "postgresql", 1)


app = App(connector=PsycopgConnector(conninfo=conninfo()), import_paths=["app.jobs"])

_open_lock = asyncio.Lock()
_opened = False


async def ensure_open() -> None:
    global _opened
    if _opened:
        return
    async with _open_lock:
        if not _opened:
            await app.open_async()
            _opened = True


async def close() -> None:
    global _opened
    if _opened:
        await app.close_async()
        _opened = False


@app.task(name="reembed")
async def reembed(source_kind: str, source_id: str) -> None:
    from app.db.session import SessionLocal
    from app.search.embeddings import reembed_source

    async with SessionLocal() as session:
        stats = await reembed_source(session, source_kind, source_id)
    print(f"reembed {source_kind}:{source_id} {stats}", flush=True)
