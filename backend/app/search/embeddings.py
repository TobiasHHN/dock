"""Einbetten (T 3.1, 3.2). Implementierung: Task 5.1 (P5)."""


async def enqueue_reembed(source_kind: str, source_id: str) -> None:
    """Legt einen entprellten Job `reembed` an (procrastinate, `queueing_lock` pro Quelle, ca. 30 s Verzögerung).
    Wird von der Op-Pipeline für jedes geänderte Dokument, jede Tabelle und jeden Workflow aufgerufen."""
    ...
