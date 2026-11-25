"""Einbetten (T 3.1, 3.2). Implementierung: Task 5.1 (P5).

Quellen (`source_kind`): "document", "table", "workflow". Die Pipeline (Task 1.2) ruft nach jeder Änderung
`await enqueue_reembed(kind, id)` auf. Der Worker (`python -m app.worker`) führt den Job `reembed` aus.
"""
from __future__ import annotations

import asyncio
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.search import chunking
from app.search.chunking import Chunk

SOURCE_KINDS = ("document", "table", "workflow")


async def enqueue_reembed(source_kind: str, source_id: str) -> None:
    """Legt einen entprellten Job `reembed` an (procrastinate, `queueing_lock` pro Quelle, ca. 30 s Verzögerung).
    Wird von der Op-Pipeline für jedes geänderte Dokument, jede Tabelle und jeden Workflow aufgerufen.

    Ist für die Quelle schon ein Job offen (`AlreadyEnqueued`), passiert nichts: das ist die Entprellung. Der Job
    liest beim Ausführen den dann aktuellen Stand. Die procrastinate-App wird beim ersten Aufruf im Prozess geöffnet."""
    from procrastinate.exceptions import AlreadyEnqueued

    from app.jobs import ensure_open, reembed

    await ensure_open()
    try:
        await reembed.configure(
            queueing_lock=f"{source_kind}:{source_id}",
            schedule_in={"seconds": settings.reembed_delay_seconds},
        ).defer_async(source_kind=source_kind, source_id=source_id)
    except AlreadyEnqueued:
        pass


# ── Embedder ─────────────────────────────────────────────────────────────────


class Embedder(Protocol):
    model_name: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedder:
    """Lazy angelegtes fastembed-Modell (CPU, ONNX). Das erste Laden lädt das Modell herunter
    (Cache: Umgebungsvariable FASTEMBED_CACHE_PATH)."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.embedding_model
        self._model: Any = None

    def load(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(self.model_name)
        return self._model

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in self.load().embed(texts)]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts)


_embedder: FastEmbedder | None = None


def get_embedder() -> FastEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = FastEmbedder()
    return _embedder


# ── Quellen laden und in Abschnitte teilen ──────────────────────────────────


async def _document_text(session: AsyncSession, doc_id: str) -> str:
    rows = (
        await session.execute(
            text("SELECT id, parent_id, position, type, props FROM blocks WHERE doc_id = :d"), {"d": doc_id}
        )
    ).mappings().all()
    return chunking.document_plain_text([dict(r) for r in rows])


async def load_chunks(session: AsyncSession, source_kind: str, source_id: str) -> tuple[str, list[Chunk]] | None:
    """Gibt (workspace_id, Abschnitte) zurück oder None, wenn die Quelle nicht (mehr) existiert."""
    if source_kind == "document":
        doc = (
            await session.execute(
                text("SELECT workspace_id, title FROM documents WHERE id = :i"), {"i": source_id}
            )
        ).mappings().first()
        if doc is None:
            return None
        rows = (
            await session.execute(
                text("SELECT id, parent_id, position, type, props FROM blocks WHERE doc_id = :d"), {"d": source_id}
            )
        ).mappings().all()
        return doc["workspace_id"], chunking.chunk_document(doc["title"], [dict(r) for r in rows])

    if source_kind == "table":
        tbl = (
            await session.execute(
                text("SELECT workspace_id, key, name FROM tables WHERE id = :i"), {"i": source_id}
            )
        ).mappings().first()
        if tbl is None:
            return None
        cols = (
            await session.execute(
                text('SELECT key, name, type FROM columns WHERE table_id = :i ORDER BY position'), {"i": source_id}
            )
        ).mappings().all()
        return tbl["workspace_id"], chunking.chunk_table(tbl["name"], tbl["key"], [dict(c) for c in cols])

    if source_kind == "workflow":
        wf = (
            await session.execute(
                text("SELECT workspace_id, key, name, draft FROM workflows WHERE id = :i"), {"i": source_id}
            )
        ).mappings().first()
        if wf is None:
            return None
        steps = (wf["draft"] or {}).get("steps", [])
        step_docs: dict[str, str] = {}
        for s in steps:
            doc_id = s.get("document")
            if doc_id and doc_id not in step_docs:
                step_docs[doc_id] = await _document_text(session, doc_id)
        return wf["workspace_id"], chunking.chunk_workflow(wf["name"], wf["key"], steps, step_docs)

    raise ValueError(f"unbekannte source_kind: {source_kind!r}")


# ── Abgleich mit der Tabelle `embeddings` ───────────────────────────────────


def _vec(v: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


async def reembed_source(
    session: AsyncSession, source_kind: str, source_id: str, embedder: Embedder | None = None
) -> dict[str, int]:
    """Berechnet die Abschnitte neu und gleicht sie per `chunk_hash` mit `embeddings` ab:
    neue Hashes werden eingebettet und eingefügt, verschwundene gelöscht, bei gleichem Hash werden nur
    `block_ids` (und Modell, falls abweichend: dann wird neu eingebettet) aktualisiert.
    Existiert die Quelle nicht mehr, werden alle ihre Einträge gelöscht. Committet selbst."""
    embedder = embedder or get_embedder()
    stats = {"inserted": 0, "deleted": 0, "updated": 0, "kept": 0}
    loaded = await load_chunks(session, source_kind, source_id)
    existing = (
        await session.execute(
            text(
                "SELECT id, chunk_hash, block_ids, model FROM embeddings "
                "WHERE source_kind = :k AND source_id = :s"
            ),
            {"k": source_kind, "s": source_id},
        )
    ).mappings().all()

    if loaded is None:
        if existing:
            await session.execute(
                text("DELETE FROM embeddings WHERE source_kind = :k AND source_id = :s"),
                {"k": source_kind, "s": source_id},
            )
            stats["deleted"] = len(existing)
        await session.commit()
        return stats

    workspace_id, chunks = loaded
    # Abschnitte mit identischem Inhalt (gleicher Hash) zusammenfassen
    wanted: dict[str, Chunk] = {}
    for c in chunks:
        if c.chunk_hash in wanted:
            for b in c.block_ids:
                if b not in wanted[c.chunk_hash].block_ids:
                    wanted[c.chunk_hash].block_ids.append(b)
        else:
            wanted[c.chunk_hash] = c

    model = embedder.model_name
    have: dict[str, Any] = {}
    stale_ids: list[int] = []
    for r in existing:
        if r["chunk_hash"] in wanted and r["model"] == model and r["chunk_hash"] not in have:
            have[r["chunk_hash"]] = r
        else:
            stale_ids.append(r["id"])  # verschwunden, doppelt oder anderes Modell

    new = [c for h, c in wanted.items() if h not in have]
    vectors = await embedder.embed([c.content for c in new]) if new else []

    if stale_ids:
        await session.execute(text("DELETE FROM embeddings WHERE id = ANY(:ids)"), {"ids": stale_ids})
        stats["deleted"] = len(stale_ids)
    for c, v in zip(new, vectors):
        await session.execute(
            text(
                "INSERT INTO embeddings (workspace_id, source_kind, source_id, block_ids, chunk_hash, content, embedding, model) "
                "VALUES (:w, :k, :s, :b, :h, :c, CAST(:e AS vector), :m)"
            ),
            {"w": workspace_id, "k": source_kind, "s": source_id, "b": c.block_ids, "h": c.chunk_hash,
             "c": c.content, "e": _vec(v), "m": model},
        )
        stats["inserted"] += 1
    for h, r in have.items():
        if list(r["block_ids"]) != wanted[h].block_ids:
            await session.execute(
                text("UPDATE embeddings SET block_ids = :b, updated_at = now() WHERE id = :i"),
                {"b": wanted[h].block_ids, "i": r["id"]},
            )
            stats["updated"] += 1
        else:
            stats["kept"] += 1
    await session.commit()
    return stats
