"""Die Op-Pipeline: der einzige Schreibweg (T 2.4, L 6.2). Implementierung: Task 1.2 (P1)."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import Actor
from app.schemas.ops import BatchResult, OpBatch


async def apply_batch(batch: OpBatch, actor: Actor, session: AsyncSession | None = None) -> BatchResult:
    """Führt einen Batch atomar aus: Idempotenz (batch_id), Rechte, `import.include` ersetzen, Keys auflösen,
    base-Versionen prüfen, Handler ausführen, Referenz-Index, Op-Log (+ inverse Ops), NOTIFY nach Commit.
    Wirft ApiError-Exceptions (CONFLICT, IN_USE, BLOCK_IN_USE, VALIDATION, FORBIDDEN, NOT_FOUND)."""
    ...
