"""Hybride Suche (T 3.3). Implementierung: Task 5.2 (P5)."""
from app.schemas.api import SearchResponse
from app.schemas.common import Actor


async def hybrid_search(query: str, actor: Actor, kinds: list[str] | None = None, limit: int = 10) -> SearchResponse:
    """Vektor + Volltext mit Reciprocal Rank Fusion; Rechte pro Treffer vor der Rückgabe prüfen."""
    ...
