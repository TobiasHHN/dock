"""Hybride Suche (T 3.3, Task 5.2): Vektor + Volltext, Reciprocal Rank Fusion, Rechte pro Treffer."""
from __future__ import annotations

from sqlalchemy import text

from app.auth import CurrentUser
from app.config import settings
from app.db.session import SessionLocal
from app.ops.context import DEFAULT_WORKSPACE
from app.ops.errors import PipelineError
from app.realtime.access import check_read
from app.schemas.api import SearchHit, SearchResponse
from app.schemas.common import Actor
from app.search.embeddings import SOURCE_KINDS, _vec, get_embedder

CANDIDATES = 50  # je Verfahren (Vektor, Volltext)
RRF_K = 60
SNIPPET_CHARS = 200

_FUSED_SQL = text("""
WITH vec AS (
  SELECT id, row_number() OVER (ORDER BY embedding <=> CAST(:qv AS vector)) AS r
  FROM embeddings
  WHERE workspace_id = :ws AND model = :model
    AND (CAST(:kinds AS text[]) IS NULL OR source_kind = ANY(CAST(:kinds AS text[])))
  ORDER BY embedding <=> CAST(:qv AS vector)
  LIMIT :n
), fts AS (
  SELECT e.id, row_number() OVER (ORDER BY ts_rank_cd(e.tsv, q) DESC) AS r
  FROM embeddings e, websearch_to_tsquery('german', :qt) q
  WHERE e.workspace_id = :ws AND e.model = :model AND e.tsv @@ q
    AND (CAST(:kinds AS text[]) IS NULL OR e.source_kind = ANY(CAST(:kinds AS text[])))
  ORDER BY ts_rank_cd(e.tsv, q) DESC
  LIMIT :n
), fused AS (
  SELECT id, sum(1.0 / (:k + r)) AS score
  FROM (SELECT * FROM vec UNION ALL SELECT * FROM fts) x
  GROUP BY id
)
SELECT e.source_kind, e.source_id, e.block_ids, e.content, f.score
FROM fused f JOIN embeddings e ON e.id = f.id
ORDER BY f.score DESC, e.id
LIMIT :pool
""")

_TITLE_SQL = {
    "document": "SELECT title FROM documents WHERE id = :i AND workspace_id = :ws",
    "table": "SELECT name FROM tables WHERE id = :i AND workspace_id = :ws",
    "workflow": "SELECT name FROM workflows WHERE id = :i AND workspace_id = :ws",
}
_CHANNEL = {"document": "doc:{}", "table": "table:{}"}  # Workflows haben keinen Kanal: Workspace-Mitgliedschaft


def _snippet(content: str) -> str:
    """Erste Zeile ist der Präfix „Titel > Überschrift“ (5.1): weglassen, Rest auf ~200 Zeichen kürzen."""
    head, sep, body = content.partition("\n")
    body = (body if sep else head).replace("\n", " ").strip()
    if len(body) > SNIPPET_CHARS:
        body = body[:SNIPPET_CHARS].rsplit(" ", 1)[0].rstrip() + " …"
    return body


def _reader(actor: Actor) -> CurrentUser:
    """Leserechte gelten für die Person (bei Agenten: die Person, in deren Auftrag er handelt)."""
    uid = actor.on_behalf_of if actor.type == "agent" and actor.on_behalf_of else actor.id
    return CurrentUser(id=uid, name=actor.name or uid, email="", roles=[])


async def hybrid_search(query: str, actor: Actor, kinds: list[str] | None = None, limit: int = 10) -> SearchResponse:
    """Vektor + Volltext mit Reciprocal Rank Fusion; Rechte pro Treffer vor der Rückgabe prüfen."""
    q = (query or "").strip()
    if kinds:
        kinds = [k for k in kinds if k in SOURCE_KINDS]
        if not kinds:
            return SearchResponse(query=query, hits=[])
    else:
        kinds = None
    if not q or limit < 1:
        return SearchResponse(query=query, hits=[])

    embedder = get_embedder()
    (qvec,) = await embedder.embed([q])
    reader = _reader(actor)

    async with SessionLocal() as session:
        rows = (await session.execute(_FUSED_SQL, {
            "qv": _vec(qvec), "qt": q, "ws": DEFAULT_WORKSPACE,
            "model": getattr(embedder, "model_name", None) or settings.embedding_model,
            "kinds": kinds, "n": CANDIDATES, "k": RRF_K, "pool": 2 * CANDIDATES,
        })).mappings().all()

        hits: list[SearchHit] = []
        seen: set[tuple[str, str]] = set()
        for r in rows:  # absteigend nach Score: erster Chunk einer Quelle = bester
            key = (r["source_kind"], r["source_id"])
            if key in seen:
                continue
            seen.add(key)
            title = (await session.execute(
                text(_TITLE_SQL[key[0]]), {"i": key[1], "ws": DEFAULT_WORKSPACE})).scalar_one_or_none()
            if title is None:  # Quelle existiert nicht mehr (Embedding noch nicht aufgeräumt)
                continue
            if key[0] in _CHANNEL:
                try:
                    await check_read(session, reader, _CHANNEL[key[0]].format(key[1]))
                except PipelineError:
                    continue  # stillschweigend auslassen
            hits.append(SearchHit(
                kind=key[0], id=key[1], title=title, snippet=_snippet(r["content"]),
                block_ids=list(r["block_ids"] or []), score=float(r["score"]),
            ))
            if len(hits) >= limit:
                break
    return SearchResponse(query=query, hits=hits)
