"""Worker-Prozess: procrastinate-Worker für den Job `reembed` (Task 5.1)."""
import asyncio

import app.jobs as jobs
from app.search.embeddings import get_embedder


async def ensure_schema() -> None:
    """Legt das procrastinate-Schema an, falls es fehlt."""
    async with jobs.app.connector.pool.connection() as conn:  # type: ignore[union-attr]
        cur = await conn.execute("SELECT to_regclass('public.procrastinate_jobs')")
        exists = (await cur.fetchone())[0] is not None
    if not exists:
        await jobs.app.schema_manager.apply_schema_async()
        print("worker: procrastinate-Schema angelegt", flush=True)


async def main() -> None:
    async with jobs.app.open_async():
        jobs._opened = True
        await ensure_schema()
        print("worker: lade Embedding-Modell …", flush=True)
        await asyncio.to_thread(get_embedder().load)
        print("worker: bereit", flush=True)
        await jobs.app.run_worker_async(queues=None, install_signal_handlers=True)


if __name__ == "__main__":
    asyncio.run(main())
