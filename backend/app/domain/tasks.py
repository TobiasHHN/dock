"""Aufgaben: Zuständige auflösen (L 5.9), can_act, Claim/Release/Reassign. Implementierung: Task 4.2 (P4)."""
from __future__ import annotations

import json
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import text

from app.domain import expressions
from app.domain.expressions import ExpressionError
from app.ops.context import DEFAULT_WORKSPACE
from app.ops.errors import PipelineError
from app.schemas.common import Actor
from app.schemas.workflows import (
    Assignee, AssigneeExpr, AssigneeRole, AssigneeStarter, AssigneeUser,
    Step, Task, TaskCandidates, WorkflowDefinition,
)

_ASSIGNEE_ADAPTER = TypeAdapter(Assignee)


def _j(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _dedup(items: list[str]) -> list[str]:
    return list(dict.fromkeys(x for x in items if x))


def effective_id(actor: Actor | dict[str, Any]) -> str:
    """Wirksame Nutzer-/Agenten-ID: bei `on_behalf_of` die vertretene Person (L 5.8, L 5.9)."""
    if isinstance(actor, dict):
        return str(actor.get("on_behalf_of") or actor["id"])
    return actor.on_behalf_of or actor.id


async def enrich_actor(ctx: Any, actor: Actor) -> Actor:
    """Ergänzt `actor.name` aus `users`/`agents`, falls nicht gesetzt (für Verlauf & `completed_by.name`)."""
    if actor.name:
        return actor
    if actor.type == "system":
        return actor.model_copy(update={"name": "Workflow" if actor.id == "workflow" else actor.id})
    ws = getattr(ctx, "workspace_id", DEFAULT_WORKSPACE)
    if actor.type == "agent":
        name = (await ctx.session.execute(
            text("SELECT name FROM agents WHERE id = :id AND workspace_id = :ws"),
            {"id": actor.id, "ws": ws})).scalar_one_or_none()
    else:
        name = (await ctx.session.execute(
            text("SELECT name FROM users WHERE id = :id"), {"id": actor.id})).scalar_one_or_none()
    return actor.model_copy(update={"name": name or actor.id})


async def actor_role_refs(ctx: Any, actor: Actor) -> list[str]:
    """Alle Rollen-IDs und -Keys des wirksamen Akteurs im Workspace (L 5.8)."""
    ws = getattr(ctx, "workspace_id", DEFAULT_WORKSPACE)
    who = effective_id(actor)
    rows = (await ctx.session.execute(
        text("""SELECT r.id, r.key FROM member_roles mr
                JOIN roles r ON r.id = mr.role_id
                WHERE mr.workspace_id = :ws AND mr.member_id = :m"""),
        {"ws": ws, "m": who})).all()
    refs: list[str] = []
    for rid, rkey in rows:
        refs.append(rid)
        refs.append(rkey)
    return _dedup(refs)


async def resolve_role_id(ctx: Any, ref: str) -> str | None:
    """Löst Rollen-ID oder -Key im Workspace auf. Liefert `None`, wenn nicht vorhanden."""
    ws = getattr(ctx, "workspace_id", DEFAULT_WORKSPACE)
    if ref.startswith("rol_"):
        return (await ctx.session.execute(
            text("SELECT id FROM roles WHERE id = :id AND workspace_id = :ws"),
            {"id": ref, "ws": ws})).scalar_one_or_none()
    return (await ctx.session.execute(
        text("SELECT id FROM roles WHERE key = :key AND workspace_id = :ws"),
        {"key": ref, "ws": ws})).scalar_one_or_none()


async def role_members(ctx: Any, role_ids: list[str]) -> list[str]:
    """Aktive Mitglieder-IDs (`usr_…`/`agt_…`) der angegebenen Rollen (ID oder Key)."""
    if not role_ids:
        return []
    ws = getattr(ctx, "workspace_id", DEFAULT_WORKSPACE)
    rows = (await ctx.session.execute(
        text("""SELECT DISTINCT mr.member_id
                FROM member_roles mr
                JOIN roles r ON r.id = mr.role_id AND r.workspace_id = mr.workspace_id
                LEFT JOIN users u ON u.id = mr.member_id
                LEFT JOIN agents a ON a.id = mr.member_id AND a.workspace_id = mr.workspace_id
                WHERE mr.workspace_id = :ws
                  AND (mr.role_id = ANY(CAST(:refs AS text[])) OR r.key = ANY(CAST(:refs AS text[])))
                  AND (u.id IS NULL OR u.active = true)
                  AND (a.id IS NULL OR a.active = true)
                ORDER BY mr.member_id"""),
        {"ws": ws, "refs": role_ids})).scalars().all()
    return list(rows)


async def _is_inactive_member(ctx: Any, member_id: str) -> bool:
    """True nur, wenn der Nutzer/Agent explizit existiert und deaktiviert (`active = false`) ist."""
    ws = getattr(ctx, "workspace_id", DEFAULT_WORKSPACE)
    u = (await ctx.session.execute(
        text("SELECT active FROM users WHERE id = :id"), {"id": member_id})).scalar_one_or_none()
    if u is not None:
        return not bool(u)
    a = (await ctx.session.execute(
        text("SELECT active FROM agents WHERE id = :id AND workspace_id = :ws"),
        {"id": member_id, "ws": ws})).scalar_one_or_none()
    if a is not None:
        return not bool(a)
    return False


async def user_channels_for_candidates(ctx: Any, candidates: TaskCandidates, excluded: list[str],
                                       extra_users: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Sortierte `user:<id>`-Kanäle für `extra_users` sowie alle nicht ausgeschlossenen Kandidaten."""
    excl = set(excluded)
    members = await role_members(ctx, candidates.roles) if candidates.roles else []
    cand_users = [u for u in [*candidates.users, *members] if u not in excl]
    all_users = _dedup([*extra_users, *cand_users])
    return sorted(f"user:{u}" for u in all_users)


async def _eval_assignee_expr(ctx: Any, expr: str, run: dict[str, Any],
                              actor: Actor | None = None) -> list[str]:
    """Wertet einen `AssigneeExpr` im Run-Kontext aus. Fehler oder leere Werte liefern `[]`."""
    from app.domain.workflows import build_run_expr_context

    eval_ctx = await build_run_expr_context(ctx, run, actor=actor, lookup_exprs=[expr])
    try:
        val = expressions.evaluate(expr, eval_ctx)
    except ExpressionError:
        return []
    if isinstance(val, str):
        return [val] if val.strip() else []
    if isinstance(val, list):
        return [str(v) for v in val if isinstance(v, str) and v.strip()]
    return []


async def _resolve_assignee_list(ctx: Any, assignees: list[Any], run: dict[str, Any],
                                 *, strict_roles: bool = False,
                                 actor: Actor | None = None) -> TaskCandidates:
    users: list[str] = []
    roles: list[str] = []
    starter_id = run.get("started_by_id") or (effective_id(run["started_by"]) if run.get("started_by") else None)
    for raw in assignees:
        a = raw if isinstance(raw, (AssigneeStarter, AssigneeUser, AssigneeRole, AssigneeExpr)) else _ASSIGNEE_ADAPTER.validate_python(raw)
        if a.kind == "starter":
            if starter_id:
                users.append(starter_id)
        elif a.kind == "user":
            if not await _is_inactive_member(ctx, a.user):
                users.append(a.user)
        elif a.kind == "role":
            rid = await resolve_role_id(ctx, a.role)
            if rid is None and strict_roles:
                raise PipelineError("NOT_FOUND", f"Rolle '{a.role}' wurde nicht gefunden")
            roles.append(rid or a.role)
        elif a.kind == "expr":
            for uid in await _eval_assignee_expr(ctx, a.expr, run, actor=actor):
                if not await _is_inactive_member(ctx, uid):
                    users.append(uid)
    return TaskCandidates(users=_dedup(users), roles=_dedup(roles))


async def matches_assignees(ctx: Any, assignees: list[Any], run: dict[str, Any], actor: Actor) -> bool:
    """Prüft, ob `actor` zu einer Assignee-Liste (z. B. `starters` oder `managers`) gehört."""
    if not assignees:
        return False
    cands = await _resolve_assignee_list(ctx, assignees, run, actor=actor)
    who = effective_id(actor)
    if who in cands.users:
        return True
    if cands.roles:
        roles = await actor_role_refs(ctx, actor)
        if set(roles) & set(cands.roles):
            return True
    return False


async def is_manager(ctx: Any, definition: WorkflowDefinition, run: dict[str, Any], actor: Actor) -> bool:
    return await matches_assignees(ctx, definition.managers, run, actor)


async def _load_definition_for_run(ctx: Any, run: dict[str, Any]) -> WorkflowDefinition | None:
    if isinstance(run.get("definition"), WorkflowDefinition):
        return run["definition"]
    if isinstance(run.get("definition"), dict):
        return WorkflowDefinition.model_validate(run["definition"])
    wf_id, version = run.get("workflow_id"), run.get("version")
    if not wf_id or version is None:
        return None
    row = (await ctx.session.execute(
        text("SELECT definition FROM workflow_versions WHERE workflow_id = :w AND version = :v"),
        {"w": wf_id, "v": version})).scalar_one_or_none()
    if row is None:
        return None
    return WorkflowDefinition.model_validate(_j(row))


async def _resolve_assignees(ctx: Any, step: Step, run: dict[str, Any]) -> tuple[TaskCandidates, list[str], bool]:
    """Wie `resolve_assignees`, liefert zusätzlich `unassigned` (True bei Fallback auf `managers`)."""
    step_obj = step if isinstance(step, Step) else Step.model_validate(step)
    cands = await _resolve_assignee_list(ctx, step_obj.assignees, run)

    starter_id = run.get("started_by_id") or (effective_id(run["started_by"]) if run.get("started_by") else None)
    excluded: list[str] = []
    if step_obj.exclude_starter and starter_id:
        excluded.append(starter_id)
    steps_data = _j(run.get("steps")) or {}
    for prev_step in step_obj.exclude_steps:
        res = steps_data.get(prev_step)
        if isinstance(res, dict) and res.get("completed_by"):
            excluded.append(effective_id(res["completed_by"]))
    excluded = _dedup(excluded)

    excl_set = set(excluded)
    remaining_users = [u for u in cands.users if u not in excl_set]
    has_role_candidate = False
    if cands.roles:
        members = await role_members(ctx, cands.roles)
        has_role_candidate = any(m not in excl_set for m in members)

    if not remaining_users and (not cands.roles or not has_role_candidate):
        definition = await _load_definition_for_run(ctx, run)
        if definition is not None and definition.managers:
            mgr_cands = await _resolve_assignee_list(ctx, definition.managers, run)
            if mgr_cands.users or mgr_cands.roles:
                return mgr_cands, excluded, True
        return TaskCandidates(users=remaining_users, roles=cands.roles), excluded, True

    return TaskCandidates(users=remaining_users, roles=cands.roles), excluded, False


async def resolve_assignees(ctx: Any, step: Step, run: dict[str, Any]) -> tuple[TaskCandidates, list[str]]:
    """Löst `step.assignees` auf: starter/user -> users, role bleibt Rolle, expr -> Ausdruck auswerten.
    Rückgabe: (candidates, excluded) mit exclude_starter und exclude_steps. Keine Kandidaten -> managers."""
    cands, excluded, _ = await _resolve_assignees(ctx, step, run)
    return cands, excluded


def can_act(actor: Actor, actor_roles: list[str], task: Task) -> bool:
    """can_act(actor, task) aus L 5.9. Bei `on_behalf_of` wird die vertretene Person geprüft."""
    if task.status != "open":
        return False
    who = effective_id(actor)
    if who in task.excluded:
        return False
    if who not in task.candidates.users and not (set(actor_roles) & set(task.candidates.roles)):
        return False
    if task.claimed_by is not None and effective_id(task.claimed_by) != who:
        return False
    return True


def task_from_row(row: dict[str, Any]) -> Task:
    return Task(
        id=row["id"],
        run_id=row["run_id"],
        step=row["step"],
        status=row["status"],
        candidates=TaskCandidates(
            users=list(row.get("candidate_users") or []),
            roles=list(row.get("candidate_roles") or []),
        ),
        excluded=list(row.get("excluded") or []),
        claimed_by=Actor.model_validate(_j(row["claimed_by"])) if row.get("claimed_by") else None,
        created_at=row["created_at"],
        due_at=row.get("due_at"),
        completed_by=Actor.model_validate(_j(row["completed_by"])) if row.get("completed_by") else None,
        completed_at=row.get("completed_at"),
        outcome=row.get("outcome"),
    )


async def claim(ctx: Any, task_id: str, actor: Actor) -> dict[str, Any]:
    """`task.claim`. Wirft TASK_CLAIMED, wenn schon von jemand anderem übernommen."""
    from app.domain.workflows import load_run_bundle, record_run_event

    row = (await ctx.session.execute(
        text("SELECT * FROM tasks WHERE id = :id FOR UPDATE"), {"id": task_id})).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Aufgabe '{task_id}' wurde nicht gefunden")
    if row["status"] == "done":
        raise PipelineError("TASK_DONE", f"Aufgabe '{task_id}' wurde bereits erledigt",
                            {"completed_by": _j(row["completed_by"]), "outcome": row["outcome"]})
    if row["status"] == "cancelled":
        raise PipelineError("TASK_DONE", f"Aufgabe '{task_id}' wurde abgebrochen", {"status": "cancelled"})

    task = task_from_row(dict(row))
    who = effective_id(actor)
    if actor.type != "system":
        if who in task.excluded:
            raise PipelineError("FORBIDDEN", "Vier-Augen-Prinzip: Sie sind für diese Aufgabe ausgeschlossen",
                                {"task": task_id})
        roles = await actor_role_refs(ctx, actor)
        if who not in task.candidates.users and not (set(roles) & set(task.candidates.roles)):
            raise PipelineError("FORBIDDEN", "Sie sind für diese Aufgabe nicht zuständig", {"task": task_id})

    if task.claimed_by is not None:
        if effective_id(task.claimed_by) != who:
            raise PipelineError("TASK_CLAIMED",
                                f"Aufgabe wird bereits von {task.claimed_by.name or task.claimed_by.id} bearbeitet",
                                {"claimed_by": task.claimed_by.model_dump(mode="json", exclude_none=True)})
        return {"id": task_id, "claimed_by": task.claimed_by.model_dump(mode="json", exclude_none=True)}

    enriched = await enrich_actor(ctx, actor)
    claimed_json = enriched.model_dump(mode="json", exclude_none=True)
    await ctx.session.execute(
        text("UPDATE tasks SET claimed_by = CAST(:cb AS jsonb), claimed_by_id = :cid WHERE id = :id"),
        {"cb": json.dumps(claimed_json), "cid": who, "id": task_id})
    await record_run_event(ctx, task.run_id, "task_claimed", enriched, step=task.step)

    run, _, _ = await load_run_bundle(ctx, task.run_id)
    channels = [f"run:{task.run_id}", *await user_channels_for_candidates(
        ctx, task.candidates, task.excluded, [run["started_by_id"]])]
    for ch in sorted(set(channels)):
        await ctx.lock_channel(ch)
    return {"id": task_id, "claimed_by": claimed_json}


async def release(ctx: Any, task_id: str, actor: Actor) -> dict[str, Any]:
    """`task.release`: gibt eine übernommene Aufgabe wieder frei (Übernehmer oder Manager)."""
    from app.domain.workflows import load_run_bundle, record_run_event

    row = (await ctx.session.execute(
        text("SELECT * FROM tasks WHERE id = :id FOR UPDATE"), {"id": task_id})).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Aufgabe '{task_id}' wurde nicht gefunden")
    if row["status"] == "done":
        raise PipelineError("TASK_DONE", f"Aufgabe '{task_id}' wurde bereits erledigt",
                            {"completed_by": _j(row["completed_by"]), "outcome": row["outcome"]})
    if row["status"] == "cancelled":
        raise PipelineError("TASK_DONE", f"Aufgabe '{task_id}' wurde abgebrochen", {"status": "cancelled"})

    task = task_from_row(dict(row))
    run, definition, _ = await load_run_bundle(ctx, task.run_id)
    who = effective_id(actor)
    if actor.type != "system" and row["claimed_by_id"] != who and not await is_manager(ctx, definition, run, actor):
        raise PipelineError("FORBIDDEN", "Nur der Übernehmer oder ein Manager darf die Aufgabe freigeben",
                            {"task": task_id})

    if row["claimed_by_id"] is not None:
        await ctx.session.execute(
            text("UPDATE tasks SET claimed_by = NULL, claimed_by_id = NULL WHERE id = :id"), {"id": task_id})
        enriched = await enrich_actor(ctx, actor)
        await record_run_event(ctx, task.run_id, "task_released", enriched, step=task.step)
        channels = [f"run:{task.run_id}", *await user_channels_for_candidates(
            ctx, task.candidates, task.excluded, [run["started_by_id"]])]
        for ch in sorted(set(channels)):
            await ctx.lock_channel(ch)
    return {"id": task_id, "claimed_by": None}


async def reassign(ctx: Any, task_id: str, assignees: list[Any], actor: Actor) -> dict[str, Any]:
    """`task.reassign`: ersetzt die Kandidaten einer offenen Aufgabe (nur Manager, L 5.9)."""
    from app.domain.workflows import load_run_bundle, record_run_event

    row = (await ctx.session.execute(
        text("SELECT * FROM tasks WHERE id = :id FOR UPDATE"), {"id": task_id})).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Aufgabe '{task_id}' wurde nicht gefunden")
    if row["status"] == "done":
        raise PipelineError("TASK_DONE", f"Aufgabe '{task_id}' wurde bereits erledigt",
                            {"completed_by": _j(row["completed_by"]), "outcome": row["outcome"]})
    if row["status"] == "cancelled":
        raise PipelineError("TASK_DONE", f"Aufgabe '{task_id}' wurde abgebrochen", {"status": "cancelled"})

    task = task_from_row(dict(row))
    run, definition, _ = await load_run_bundle(ctx, task.run_id)
    if actor.type != "system" and not await is_manager(ctx, definition, run, actor):
        raise PipelineError("FORBIDDEN", "Nur Workflow-Manager dürfen Aufgaben umverteilen", {"task": task_id})

    if not assignees:
        raise PipelineError("VALIDATION", "assignees darf nicht leer sein",
                            {"errors": {"assignees": "Mindestens ein Zuständiger erforderlich"}})

    new_cands = await _resolve_assignee_list(ctx, assignees, run, strict_roles=True)
    if not new_cands.users and not new_cands.roles:
        raise PipelineError("VALIDATION", "Keine gültigen Zuständigen angegeben",
                            {"errors": {"assignees": "Keine gültigen Zuständigen"}})

    await ctx.session.execute(
        text("""UPDATE tasks
                SET candidate_users = CAST(:u AS text[]),
                    candidate_roles = CAST(:r AS text[]),
                    claimed_by = NULL,
                    claimed_by_id = NULL
                WHERE id = :id"""),
        {"u": new_cands.users, "r": new_cands.roles, "id": task_id})

    enriched = await enrich_actor(ctx, actor)
    old_desc = ", ".join([*task.candidates.users, *task.candidates.roles]) or "niemand"
    new_desc = ", ".join([*new_cands.users, *new_cands.roles])
    await record_run_event(ctx, task.run_id, "reassigned", enriched, step=task.step,
                           text_val=f"{old_desc} → {new_desc}")

    old_ch = await user_channels_for_candidates(ctx, task.candidates, task.excluded, [run["started_by_id"]])
    new_ch = await user_channels_for_candidates(ctx, new_cands, task.excluded, [run["started_by_id"]])
    for ch in sorted({f"run:{task.run_id}", *old_ch, *new_ch}):
        await ctx.lock_channel(ch)

    return {"id": task_id, "candidates": new_cands.model_dump()}
