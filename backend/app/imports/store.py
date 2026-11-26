"""Vorbereitete Imports (T 2.9, Task 3.6). Tabelle `imports`, 1 h gültig, einmalig verwendbar.

`ctx` ist alles mit `session` (AsyncSession), `actor` (Actor) und optional `workspace_id`, also auch der
`OpContext` der Pipeline.
"""
import json
from typing import Any

from sqlalchemy import text

from app.domain.ids import new_id
from app.imports.preview import summarize_ops
from app.ops.errors import PipelineError
from app.schemas.api import ImportPlan

DEFAULT_WORKSPACE = "ws_demo"


def _workspace(ctx: Any) -> str:
    return getattr(ctx, "workspace_id", None) or DEFAULT_WORKSPACE


async def save_plan(ctx: Any, source: str, ops: list[dict[str, Any]], created: dict[str, Any],
                    warnings: list[str]) -> ImportPlan:
    """Speichert die Ops unter einer neuen `import_id` (1 h gültig) und gibt Plan, Warnungen und Vorschau zurück.
    Schreibt nur in `imports`, nie in den Workspace. Die Transaktion des Aufrufers committet."""
    session, workspace = ctx.session, _workspace(ctx)
    await session.execute(
        text("DELETE FROM imports WHERE workspace_id = :ws "
             "AND (used_at IS NOT NULL OR created_at < now() - interval '1 day')"),
        {"ws": workspace})
    import_id = new_id("import")
    await session.execute(
        text("""INSERT INTO imports (id, workspace_id, actor, source, ops, created, warnings)
                VALUES (:id, :ws, CAST(:actor AS jsonb), :source, CAST(:ops AS jsonb), CAST(:created AS jsonb),
                        CAST(:warnings AS jsonb))"""),
        {"id": import_id, "ws": workspace, "actor": json.dumps(ctx.actor.model_dump(mode="json", exclude_none=True)),
         "source": source, "ops": json.dumps(ops, default=str), "created": json.dumps(created, default=str),
         "warnings": json.dumps(warnings)})
    return ImportPlan(import_id=import_id, created=created, warnings=warnings, preview=summarize_ops(ops))


async def take_ops(ctx: Any, import_id: str, actor: Any = None) -> list[dict[str, Any]]:
    """Für den Handler `import.include`: prüft Akteur und Gültigkeit, markiert den Import als verbraucht
    (`IMPORT_USED` bei zweitem Versuch) und liefert die Ops. `used_at` gilt erst mit dem Commit des Batches:
    scheitert dieser, wird auch die Markierung zurückgerollt."""
    actor = actor or ctx.actor
    row = (await ctx.session.execute(
        text("""SELECT ops, actor, used_at, created_at > now() - interval '1 hour' AS fresh
                FROM imports WHERE id = :id AND workspace_id = :ws FOR UPDATE"""),
        {"id": import_id, "ws": _workspace(ctx)})).mappings().first()
    if row is None:
        raise PipelineError("IMPORT_INVALID", f"Import '{import_id}' existiert nicht")
    if row["used_at"] is not None:
        raise PipelineError("IMPORT_USED", f"Import '{import_id}' wurde bereits verwendet")
    if not row["fresh"]:
        raise PipelineError("IMPORT_INVALID", f"Import '{import_id}' ist abgelaufen")
    owner = row["actor"]
    owner = json.loads(owner) if isinstance(owner, str) else owner
    if actor.type != "system" and owner and owner.get("id") != actor.id:
        raise PipelineError("FORBIDDEN", f"Import '{import_id}' gehört einem anderen Akteur")
    await ctx.session.execute(text("UPDATE imports SET used_at = now() WHERE id = :id"), {"id": import_id})
    ops = row["ops"]
    return json.loads(ops) if isinstance(ops, str) else ops
