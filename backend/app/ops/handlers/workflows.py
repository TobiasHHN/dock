"""Handler für `workflow.create|update|publish|delete` (L 5.2, L 5.3, L 5.7, L 6.1). Task 4.1.

Regeln:
- Der Entwurf (`draft`) darf unvollständig sein: Schritt-Dokumente und Rollen dürfen auch erst später im selben
  Batch entstehen. Geprüft wird erst bei `workflow.publish` (bzw. `POST /api/workflows/validate`).
- Rollen-Keys in Zuständigen werden beim Speichern zu IDs aufgelöst, soweit die Rolle schon existiert (L 1).
  Unbekannte Keys bleiben stehen und führen bei der Prüfung zu `ROLE_UNKNOWN`. `workflow.publish` löst erneut auf,
  damit Rollen, die nach `workflow.create` im Batch angelegt wurden, ebenfalls als ID gespeichert werden.
- Verweise (L 9): `step.document`, `step.assignee` (Rolle/Nutzer), `workflow.starters`, `workflow.managers`.
  Damit greift der Löschschutz von `doc.delete` und `role.delete`.
- `workflow.delete` nur ohne aktive Runs und ohne `workflow`-Blöcke, die ihn verwenden (IN_USE). Abgeschlossene
  und abgebrochene Runs werden samt Aufgaben, Events und Benachrichtigungen mitgelöscht; die Schritt-Dokumente
  bleiben erhalten. Die inverse Op stellt nur den Entwurf wieder her, nicht die Versionen.
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text

from app.domain import references
from app.domain import tasks as T
from app.domain import workflows as W
from app.ops.context import OpContext
from app.ops.errors import PipelineError
from app.ops.handlers import register
from app.schemas.ops import (
    RunCancel, RunStart, TaskClaim, TaskReassign, TaskRelease,
    WorkflowCreate, WorkflowDelete, WorkflowPublish, WorkflowUpdate,
)
from app.schemas.workflows import WorkflowDefinition

_KEY = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _invalid(path: str, message: str) -> PipelineError:
    return PipelineError("VALIDATION", f"{path}: {message}", {"errors": {path: message}})


def _dump(definition: WorkflowDefinition) -> dict[str, Any]:
    return definition.model_dump(mode="json", by_alias=True)


async def _load(ctx: OpContext, workflow_id: str) -> dict[str, Any]:
    row = (await ctx.session.execute(
        text("SELECT id, key, name, draft, latest_version FROM workflows WHERE id = :id AND workspace_id = :ws"),
        {"id": workflow_id, "ws": ctx.workspace_id})).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Workflow '{workflow_id}' wurde nicht gefunden")
    draft = row["draft"]
    return {**dict(row), "draft": json.loads(draft) if isinstance(draft, str) else draft}


async def resolve_definition(ctx: OpContext, definition: WorkflowDefinition) -> WorkflowDefinition:
    """Rollen-Keys -> Rollen-IDs, soweit bekannt (auch im selben Batch angelegte Rollen)."""
    data = _dump(definition)

    async def fix(assignees: list[dict[str, Any]]) -> None:
        for a in assignees:
            if a.get("kind") == "role" and not a["role"].startswith("rol_"):
                try:
                    a["role"] = await ctx.resolve("role", a["role"])
                except PipelineError:
                    pass  # bleibt als Key stehen, die Prüfung meldet ROLE_UNKNOWN

    for step in data["steps"]:
        await fix(step["assignees"])
    await fix(data["starters"])
    await fix(data["managers"])
    return WorkflowDefinition.model_validate(data)


def definition_edges(definition: WorkflowDefinition) -> list[tuple[str, str, str]]:
    edges: list[tuple[str, str, str]] = []

    def assignees(items: list[Any], via: str) -> None:
        for a in items:
            if a.kind == "role" and a.role.startswith("rol_"):
                edges.append(("role", a.role, via))
            elif a.kind == "user":
                edges.append(("user", a.user, via))

    for step in definition.steps:
        edges.append(("document", step.document, "step.document"))
        assignees(step.assignees, "step.assignee")
    assignees(definition.starters, "workflow.starters")
    assignees(definition.managers, "workflow.managers")
    return edges


async def _save_draft(ctx: OpContext, workflow_id: str, definition: WorkflowDefinition) -> None:
    await ctx.session.execute(text("UPDATE workflows SET draft = CAST(:d AS jsonb) WHERE id = :id"),
                              {"d": json.dumps(_dump(definition)), "id": workflow_id})
    ctx.set_references("workflow", workflow_id, definition_edges(definition))
    await ctx.touch("workflow", workflow_id, "workspace")


@register("workflow.create")
async def workflow_create(ctx: OpContext, op: WorkflowCreate):
    if not op.id.startswith("wf_") or len(op.id) <= 3:
        raise _invalid("id", f"Workflow-IDs beginnen mit 'wf_' (erhalten: '{op.id}')")
    if op.key.startswith("wf_") or not _KEY.match(op.key):
        raise _invalid("key", f"Workflow-Key '{op.key}' ist ungültig: Kleinbuchstaben, Ziffern und '_', beginnend "
                              "mit einem Buchstaben, nicht mit 'wf_'")
    if not op.name.strip():
        raise _invalid("name", "Der Name darf nicht leer sein")
    taken = (await ctx.session.execute(
        text("SELECT id, key FROM workflows WHERE id = :id OR (workspace_id = :ws AND key = :key)"),
        {"id": op.id, "ws": ctx.workspace_id, "key": op.key})).mappings().first()
    if taken is not None:
        if taken["id"] == op.id:
            raise _invalid("id", f"Workflow-ID '{op.id}' existiert bereits")
        raise _invalid("key", f"Workflow-Key '{op.key}' ist bereits vergeben (Workflow '{taken['id']}')")

    definition = await resolve_definition(ctx, op.definition)
    await ctx.session.execute(
        text("""INSERT INTO workflows (id, workspace_id, key, name, draft)
                VALUES (:id, :ws, :key, :name, CAST(:d AS jsonb))"""),
        {"id": op.id, "ws": ctx.workspace_id, "key": op.key, "name": op.name, "d": json.dumps(_dump(definition))})
    ctx.set_references("workflow", op.id, definition_edges(definition))
    await ctx.touch("workflow", op.id, "workspace", created=True)
    ctx.add_inverse({"op": "workflow.delete", "workflow": op.id})
    return {"id": op.id}


@register("workflow.update")
async def workflow_update(ctx: OpContext, op: WorkflowUpdate):
    current = await _load(ctx, op.workflow)
    await _save_draft(ctx, op.workflow, await resolve_definition(ctx, op.definition))
    ctx.add_inverse({"op": "workflow.update", "workflow": op.workflow, "definition": current["draft"]})


@register("workflow.publish")
async def workflow_publish(ctx: OpContext, op: WorkflowPublish):
    current = await _load(ctx, op.workflow)
    resolved = await resolve_definition(ctx, WorkflowDefinition.model_validate(current["draft"]))
    if _dump(resolved) != current["draft"]:
        await _save_draft(ctx, op.workflow, resolved)
    version, warnings = await W.publish_with_issues(ctx, op.workflow)
    await ctx.touch("workflow", op.workflow, "workspace")
    return {"workflow": op.workflow, "version": version,
            "warnings": [w.model_dump(exclude_none=True) for w in warnings]}


@register("workflow.delete")
async def workflow_delete(ctx: OpContext, op: WorkflowDelete):
    current = await _load(ctx, op.workflow)
    active = (await ctx.session.execute(
        text("SELECT id FROM runs WHERE workflow_id = :id AND status = 'active' ORDER BY id"),
        {"id": op.workflow})).scalars().all()
    if active:
        raise PipelineError("IN_USE", f"Workflow '{current['key']}' hat {len(active)} aktive Runs "
                                      f"({', '.join(active[:5])}). Erst abschließen oder abbrechen.",
                            {"runs": list(active)})
    blockers = [u for u in await references.usages(ctx, "workflow", op.workflow) if u["via"] == "workflow_block"]
    if blockers:
        listing = ", ".join(f"Block {u['source_id']}" for u in blockers)
        raise PipelineError("IN_USE", f"Workflow '{current['key']}' wird verwendet von: {listing}",
                            {"usages": blockers})

    for stmt in ("DELETE FROM notifications WHERE run_id IN (SELECT id FROM runs WHERE workflow_id = :id)",
                 "DELETE FROM run_events WHERE run_id IN (SELECT id FROM runs WHERE workflow_id = :id)",
                 "DELETE FROM tasks WHERE run_id IN (SELECT id FROM runs WHERE workflow_id = :id)",
                 "DELETE FROM runs WHERE workflow_id = :id",
                 "DELETE FROM workflows WHERE id = :id"):
        await ctx.session.execute(text(stmt), {"id": op.workflow})
    ctx.set_references("workflow", op.workflow, [])
    await ctx.touch("workflow", op.workflow, "workspace", deleted=True)
    ctx.add_inverse({"op": "workflow.create", "id": op.workflow, "key": current["key"], "name": current["name"],
                     "definition": current["draft"]})


# ── Runs & Aufgaben (Task 4.2) ───────────────────────────────────────────────


@register("run.start")
async def run_start(ctx: OpContext, op: RunStart):
    return await W.start_run(ctx, op.id, op.workflow, op.input, ctx.actor)


@register("run.cancel")
async def run_cancel(ctx: OpContext, op: RunCancel):
    return await W.cancel_run(ctx, op.run, op.reason, ctx.actor)


@register("task.claim")
async def task_claim(ctx: OpContext, op: TaskClaim):
    return await T.claim(ctx, op.task, ctx.actor)


@register("task.release")
async def task_release(ctx: OpContext, op: TaskRelease):
    return await T.release(ctx, op.task, ctx.actor)


@register("task.reassign")
async def task_reassign(ctx: OpContext, op: TaskReassign):
    return await T.reassign(ctx, op.task, op.assignees, ctx.actor)
