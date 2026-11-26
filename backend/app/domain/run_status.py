"""Statusansicht, Events, Benachrichtigungen (L 5.10, T 4, T 5.7, L 8.1). Implementierung: Task 4.4 (P4)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import tasks as T
from app.domain.ids import new_id
from app.ops.context import DEFAULT_WORKSPACE
from app.ops.errors import PipelineError
from app.ops.pipeline import PRIVILEGED_ROLE
from app.schemas.common import Actor
from app.schemas.workflows import (
    ButtonInfo, Notification, RunEvent, RunListItem, RunStatusView,
    StatusCandidates, StatusCurrent, StatusStep, TaskDetail, TaskListItem, WorkflowDefinition,
)


def _j(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _ctx(s: AsyncSession, workspace: str = DEFAULT_WORKSPACE) -> Any:
    return type("_Ctx", (), {"session": s, "workspace_id": workspace})()


async def _lookup_member_name(s: AsyncSession, member_id: str, workspace: str = DEFAULT_WORKSPACE) -> str:
    name = (await s.execute(text("SELECT name FROM users WHERE id = :id"), {"id": member_id})).scalar_one_or_none()
    if name:
        return name
    name = (await s.execute(
        text("SELECT name FROM agents WHERE id = :id AND workspace_id = :ws"),
        {"id": member_id, "ws": workspace})).scalar_one_or_none()
    return name or member_id


async def _format_actor_label(s: AsyncSession, actor_raw: Any, workspace: str = DEFAULT_WORKSPACE) -> str:
    """Formatiert `Actor` für Status/Verlauf inkl. „Agent im Auftrag von …“ (L 5.8, L 5.10)."""
    actor = actor_raw if isinstance(actor_raw, Actor) else Actor.model_validate(_j(actor_raw))
    own = actor.name or await _lookup_member_name(s, actor.id, workspace)
    if actor.type == "agent" and actor.on_behalf_of:
        principal = await _lookup_member_name(s, actor.on_behalf_of, workspace)
        return f"{own} im Auftrag von {principal}"
    return own


async def _resolve_status_candidates(s: AsyncSession, candidate_users: list[str], candidate_roles: list[str],
                                     workspace: str = DEFAULT_WORKSPACE) -> StatusCandidates:
    users: list[dict[str, str]] = []
    if candidate_users:
        rows = (await s.execute(
            text("""SELECT id, name FROM users WHERE id = ANY(CAST(:ids AS text[]))
                    UNION ALL
                    SELECT id, name FROM agents WHERE workspace_id = :ws AND id = ANY(CAST(:ids AS text[]))"""),
            {"ids": list(candidate_users), "ws": workspace})).mappings().all()
        names = {r["id"]: r["name"] for r in rows}
        for uid in candidate_users:
            users.append({"id": uid, "name": names.get(uid, uid)})

    roles: list[dict[str, str]] = []
    if candidate_roles:
        rows = (await s.execute(
            text("""SELECT id, key, name FROM roles WHERE workspace_id = :ws
                      AND (id = ANY(CAST(:refs AS text[])) OR key = ANY(CAST(:refs AS text[])))"""),
            {"ws": workspace, "refs": list(candidate_roles)})).mappings().all()
        by_ref: dict[str, dict[str, str]] = {}
        for r in rows:
            entry = {"key": r["key"], "name": r["name"]}
            by_ref[r["id"]] = entry
            by_ref[r["key"]] = entry
        for ref in candidate_roles:
            roles.append(by_ref.get(ref, {"key": ref, "name": ref}))
    return StatusCandidates(users=users, roles=roles)


async def can_view_run(ctx: Any, run_dict: dict[str, Any], definition: WorkflowDefinition, viewer: Actor) -> bool:
    """Prüft Sichtbarkeit laut L 5.10 (plus Rolle `einkauf` laut P1-Festlegung)."""
    if viewer.type == "system":
        return True
    who = T.effective_id(viewer)
    if run_dict.get("started_by_id") == who:
        return True
    roles = await T.actor_role_refs(ctx, viewer)
    if PRIVILEGED_ROLE in roles:
        return True
    if await T.is_manager(ctx, definition, run_dict, viewer):
        return True
    involved = (await ctx.session.execute(
        text("""SELECT 1 FROM tasks WHERE run_id = :run AND (
                    :u = ANY(candidate_users) OR candidate_roles && CAST(:roles AS text[])
                    OR claimed_by_id = :u
                    OR completed_by->>'id' = :u
                    OR completed_by->>'on_behalf_of' = :u) LIMIT 1"""),
        {"run": run_dict["id"], "u": who, "roles": roles})).scalar_one_or_none()
    return involved is not None


async def ensure_run_view(ctx: Any, run_dict: dict[str, Any], definition: WorkflowDefinition, viewer: Actor) -> None:
    if not await can_view_run(ctx, run_dict, definition, viewer):
        raise PipelineError("FORBIDDEN", "Kein Zugriff auf diesen Run", {"run": run_dict["id"]})


# ── Events & Benachrichtigungen (L 5.10) ─────────────────────────────────────


async def _task_recipients(ctx: Any, task_row: dict[str, Any] | None) -> list[str]:
    if task_row is None:
        return []
    excluded = set(task_row.get("excluded") or [])
    users = list(task_row.get("candidate_users") or [])
    roles = list(task_row.get("candidate_roles") or [])
    members = await T.role_members(ctx, roles) if roles else []
    return [u for u in dict.fromkeys([*users, *members]) if u not in excluded]


async def _manager_recipients(ctx: Any, definition: WorkflowDefinition, run_dict: dict[str, Any]) -> list[str]:
    if not definition.managers:
        return []
    cands = await T._resolve_assignee_list(ctx, definition.managers, run_dict)
    members = await T.role_members(ctx, cands.roles) if cands.roles else []
    return list(dict.fromkeys([*cands.users, *members]))


async def record_event(ctx: Any, run_id: str, type: str, actor: Actor, **fields: Any) -> str:
    """Schreibt ein `run_events`-Event und erzeugt Benachrichtigungen nach der Tabelle in L 5.10."""
    from app.domain.workflows import load_run_bundle

    step = fields.get("step")
    outcome = fields.get("outcome")
    label = fields.get("label")
    text_val = fields["text"] if "text" in fields else fields.get("text_val")
    task_id = fields.get("task_id")

    evt_id = new_id("event")
    now = datetime.now(timezone.utc)
    await ctx.session.execute(
        text("""INSERT INTO run_events (id, run_id, at, actor, type, step, outcome, label, text)
                VALUES (:id, :run_id, :at, CAST(:actor AS jsonb), :type, :step, :outcome, :label, :text)"""),
        {
            "id": evt_id,
            "run_id": run_id,
            "at": now,
            "actor": json.dumps(actor.model_dump(mode="json", exclude_none=True)),
            "type": type,
            "step": step,
            "outcome": outcome,
            "label": label,
            "text": text_val,
        },
    )

    if type not in {"step_entered", "step_completed", "completed", "cancelled", "comment", "overdue", "unassigned"}:
        return evt_id

    run_dict, definition, _ = await load_run_bundle(ctx, run_id)
    open_task: dict[str, Any] | None = None
    if type in {"step_entered", "comment", "overdue", "unassigned"}:
        if task_id:
            row = (await ctx.session.execute(
                text("SELECT * FROM tasks WHERE id = :id"), {"id": task_id})).mappings().first()
        else:
            row = (await ctx.session.execute(
                text("SELECT * FROM tasks WHERE run_id = :r AND status = 'open' ORDER BY created_at DESC LIMIT 1"),
                {"r": run_id})).mappings().first()
        open_task = dict(row) if row else None

    recipients: list[str] = []
    if type == "step_entered":
        recipients = await _task_recipients(ctx, open_task)
    elif type in {"step_completed", "completed", "cancelled"}:
        if run_dict.get("started_by_id"):
            recipients = [run_dict["started_by_id"]]
    elif type == "comment":
        task_users = await _task_recipients(ctx, open_task)
        starter = [run_dict["started_by_id"]] if run_dict.get("started_by_id") else []
        recipients = list(dict.fromkeys([*starter, *task_users]))
    elif type in {"overdue", "unassigned"}:
        task_users = await _task_recipients(ctx, open_task)
        mgrs = await _manager_recipients(ctx, definition, run_dict)
        recipients = list(dict.fromkeys([*task_users, *mgrs]))

    if not recipients:
        return evt_id

    ws = getattr(ctx, "workspace_id", DEFAULT_WORKSPACE)
    step_def = next((s for s in definition.steps if s.key == step), None) if step else None
    actor_label = await _format_actor_label(ctx.session, actor, ws)
    raw_payload = {
        "title": run_dict.get("title"),
        "step": step,
        "step_name": step_def.name if step_def else None,
        "status_label": step_def.status_label if step_def else None,
        "outcome": outcome,
        "label": label,
        "text": text_val,
        "actor": actor_label,
    }
    payload = {k: v for k, v in raw_payload.items() if v is not None}
    eff_task_id = task_id or (open_task["id"] if open_task else None)

    if hasattr(ctx, "lock_channel"):
        for rid in sorted(set(recipients)):
            await ctx.lock_channel(f"user:{rid}")

    for rid in recipients:
        ntf_id = new_id("notification")
        await ctx.session.execute(
            text("""INSERT INTO notifications (id, recipient_id, run_id, task_id, type, payload, created_at)
                    VALUES (:id, :rec, :run_id, :task_id, :type, CAST(:payload AS jsonb), :at)"""),
            {
                "id": ntf_id,
                "rec": rid,
                "run_id": run_id,
                "task_id": eff_task_id,
                "type": type,
                "payload": json.dumps(payload),
                "at": now,
            },
        )
        ntf_event = {
            "type": "notification",
            "notification": {
                "id": ntf_id,
                "recipient_id": rid,
                "run_id": run_id,
                "task_id": eff_task_id,
                "type": type,
                "payload": payload,
                "created_at": now.isoformat(),
                "read_at": None,
            },
        }
        if hasattr(ctx, "emit"):
            ctx.emit(f"user:{rid}", ntf_event)
        else:
            from app.realtime import hub

            await hub.publish(f"user:{rid}", ntf_event)

    return evt_id


async def add_comment(ctx: Any, run_id: str, text_val: str, actor: Actor) -> dict[str, Any]:
    """Handler für `run.comment` (L 5.10): jeder, der den Run sieht, darf kommentieren."""
    from app.domain.workflows import load_run_bundle

    cleaned = (text_val or "").strip()
    if not cleaned:
        raise PipelineError("VALIDATION", "Kommentar darf nicht leer sein",
                            {"errors": {"text": "Kommentar darf nicht leer sein"}})
    run_dict, definition, _ = await load_run_bundle(ctx, run_id)
    await ensure_run_view(ctx, run_dict, definition, actor)
    enriched = await T.enrich_actor(ctx, actor)
    if hasattr(ctx, "lock_channel"):
        await ctx.lock_channel(f"run:{run_id}")
    evt_id = await record_event(ctx, run_id, "comment", enriched, step=run_dict.get("current_step"), text=cleaned)
    return {"id": evt_id, "run": run_id}


# ── Statusansicht & Listen (L 5.10, T 5.7, L 8.1) ────────────────────────────


async def build_status_view(ctx: Any, run_id: str, viewer: Actor) -> RunStatusView:
    """Statusansicht (gleich für Browser und `get_run`). Prüft, ob der Betrachter den Run sehen darf."""
    from app.domain.workflows import load_run_bundle

    ws = getattr(ctx, "workspace_id", DEFAULT_WORKSPACE)
    run_dict, definition, wf_name = await load_run_bundle(ctx, run_id)
    await ensure_run_view(ctx, run_dict, definition, viewer)

    current_step = run_dict.get("current_step")
    current_obj: StatusCurrent | None = None
    if run_dict["status"] == "active" and current_step:
        open_row = (await ctx.session.execute(
            text("""SELECT * FROM tasks WHERE run_id = :r AND step = :s AND status = 'open'
                    ORDER BY created_at DESC LIMIT 1"""),
            {"r": run_id, "s": current_step})).mappings().first()
        step_def = next((st for st in definition.steps if st.key == current_step), None)
        if open_row is not None:
            cands = await _resolve_status_candidates(
                ctx.session, list(open_row["candidate_users"] or []), list(open_row["candidate_roles"] or []), ws
            )
            current_obj = StatusCurrent(
                step=current_step,
                label=(step_def.status_label or step_def.name) if step_def else current_step,
                since=open_row["created_at"],
                candidates=cands,
                claimed_by=Actor.model_validate(_j(open_row["claimed_by"])) if open_row.get("claimed_by") else None,
                due_at=open_row.get("due_at"),
            )

    step_names = {st.key: st.name for st in definition.steps}
    steps_data = _j(run_dict.get("steps")) or {}
    done_entries = [
        (k, v) for k, v in steps_data.items()
        if not (run_dict["status"] == "active" and k == current_step)
    ]
    done_entries.sort(key=lambda kv: str(kv[1].get("completed_at") or ""))

    status_steps: list[StatusStep] = []
    seen_steps: set[str] = set()
    for step_key, res in done_entries:
        seen_steps.add(step_key)
        by_label = await _format_actor_label(ctx.session, res["completed_by"], ws) if res.get("completed_by") else None
        status_steps.append(StatusStep(
            step=step_key,
            name=step_names.get(step_key, step_key),
            state="done",
            label=res.get("label"),
            by=by_label,
            at=res.get("completed_at"),
        ))

    if run_dict["status"] == "active" and current_step:
        seen_steps.add(current_step)
        status_steps.append(StatusStep(
            step=current_step,
            name=step_names.get(current_step, current_step),
            state="active",
        ))

    for st in definition.steps:
        if st.key not in seen_steps:
            status_steps.append(StatusStep(step=st.key, name=st.name, state="pending"))

    event_rows = (await ctx.session.execute(
        text("SELECT id, run_id, at, actor, type, step, outcome, label, text FROM run_events "
             "WHERE run_id = :r ORDER BY at ASC, id ASC"),
        {"r": run_id})).mappings().all()
    events = [
        RunEvent(
            id=r["id"],
            run_id=r["run_id"],
            at=r["at"],
            actor=Actor.model_validate(_j(r["actor"])),
            type=r["type"],
            step=r["step"],
            outcome=r["outcome"],
            label=r["label"],
            text=r["text"],
        )
        for r in event_rows
    ]

    return RunStatusView(
        id=run_dict["id"],
        title=run_dict["title"],
        workflow={"id": run_dict["workflow_id"], "name": wf_name, "version": run_dict["version"]},
        status=run_dict["status"],
        result=_j(run_dict.get("result")),
        started_by=Actor.model_validate(_j(run_dict["started_by"])),
        started_at=run_dict["started_at"],
        current=current_obj,
        steps=status_steps,
        events=events,
    )


async def list_runs(s: AsyncSession, viewer: Actor, *, workflow: str | None = None,
                    started_by: str = "me", status: str | None = None,
                    workspace: str = DEFAULT_WORKSPACE) -> list[RunListItem]:
    """„Meine Anträge“ (`started_by="me"`) oder alle sichtbaren Runs (`started_by="any"`)."""
    ctx = _ctx(s, workspace)
    where = ["w.workspace_id = :ws"]
    params: dict[str, Any] = {"ws": workspace}

    if workflow:
        wf_id = (await s.execute(
            text("SELECT id FROM workflows WHERE workspace_id = :ws AND (id = :w OR key = :w)"),
            {"ws": workspace, "w": workflow})).scalar_one_or_none()
        if wf_id is None:
            return []
        where.append("r.workflow_id = :wf")
        params["wf"] = wf_id

    if status:
        where.append("r.status = :st")
        params["st"] = status

    who = T.effective_id(viewer)
    if started_by == "me":
        where.append("r.started_by_id = :me")
        params["me"] = who

    rows = (await s.execute(
        text(f"""SELECT r.*, w.name AS wf_name, v.definition AS wf_def
                 FROM runs r
                 JOIN workflows w ON w.id = r.workflow_id
                 JOIN workflow_versions v ON v.workflow_id = r.workflow_id AND v.version = r.version
                 WHERE {' AND '.join(where)}
                 ORDER BY r.started_at DESC, r.id DESC"""),
        params)).mappings().all()

    out: list[RunListItem] = []
    for row in rows:
        run_dict = {**dict(row)}
        for col in ("result", "input", "steps", "started_by"):
            run_dict[col] = _j(run_dict[col])
        definition = WorkflowDefinition.model_validate(_j(run_dict.pop("wf_def")))
        wf_name = str(run_dict.pop("wf_name"))
        if started_by != "me" and not await can_view_run(ctx, run_dict, definition, viewer):
            continue

        status_label: str | None = None
        cands: StatusCandidates | None = None
        if run_dict["status"] == "active" and run_dict.get("current_step"):
            step_def = next((st for st in definition.steps if st.key == run_dict["current_step"]), None)
            status_label = (step_def.status_label or step_def.name) if step_def else run_dict["current_step"]
            open_t = (await s.execute(
                text("""SELECT candidate_users, candidate_roles FROM tasks
                        WHERE run_id = :r AND step = :s AND status = 'open'
                        ORDER BY created_at DESC LIMIT 1"""),
                {"r": run_dict["id"], "s": run_dict["current_step"]})).mappings().first()
            if open_t is not None:
                cands = await _resolve_status_candidates(
                    s, list(open_t["candidate_users"] or []), list(open_t["candidate_roles"] or []), workspace
                )

        out.append(RunListItem(
            id=run_dict["id"],
            title=run_dict["title"],
            workflow_name=wf_name,
            status=run_dict["status"],
            status_label=status_label,
            candidates=cands,
            result=run_dict.get("result"),
            started_at=run_dict["started_at"],
        ))
    return out


async def list_tasks(s: AsyncSession, viewer: Actor, *, assigned_to: str = "me", status: str = "open",
                     workflow: str | None = None, workspace: str = DEFAULT_WORKSPACE) -> list[TaskListItem]:
    """Aufgabenliste des Aufrufers (T 4 / T 5.7)."""
    ctx = _ctx(s, workspace)
    who = T.effective_id(viewer)
    roles = await T.actor_role_refs(ctx, viewer)

    where = ["w.workspace_id = :ws"]
    params: dict[str, Any] = {"ws": workspace, "me": who, "roles": roles}

    if status != "all":
        where.append("t.status = :st")
        params["st"] = status

    if status == "open":
        where.append("NOT (:me = ANY(t.excluded))")
        where.append("(:me = ANY(t.candidate_users) OR t.candidate_roles && CAST(:roles AS text[]) OR t.claimed_by_id = :me)")
    else:
        where.append("(:me = ANY(t.candidate_users) OR t.candidate_roles && CAST(:roles AS text[]) "
                     "OR t.claimed_by_id = :me OR t.completed_by->>'id' = :me OR t.completed_by->>'on_behalf_of' = :me)")

    if workflow:
        wf_id = (await s.execute(
            text("SELECT id FROM workflows WHERE workspace_id = :ws AND (id = :w OR key = :w)"),
            {"ws": workspace, "w": workflow})).scalar_one_or_none()
        if wf_id is None:
            return []
        where.append("r.workflow_id = :wf")
        params["wf"] = wf_id

    rows = (await s.execute(
        text(f"""SELECT t.*, r.title AS run_title, w.name AS wf_name, v.definition AS wf_def
                 FROM tasks t
                 JOIN runs r ON r.id = t.run_id
                 JOIN workflows w ON w.id = r.workflow_id
                 JOIN workflow_versions v ON v.workflow_id = r.workflow_id AND v.version = r.version
                 WHERE {' AND '.join(where)}
                 ORDER BY t.due_at ASC NULLS LAST, t.created_at ASC"""),
        params)).mappings().all()

    out: list[TaskListItem] = []
    for row in rows:
        task_model = T.task_from_row(dict(row))
        definition = WorkflowDefinition.model_validate(_j(row["wf_def"]))
        step_def = next((st for st in definition.steps if st.key == task_model.step), None)
        claimed_name = (
            await _format_actor_label(s, task_model.claimed_by, workspace)
            if task_model.claimed_by is not None else None
        )
        out.append(TaskListItem(
            task=task_model,
            run_title=row["run_title"],
            step_name=step_def.name if step_def else task_model.step,
            workflow_name=row["wf_name"],
            can_act=T.can_act(viewer, roles, task_model),
            claimed_by_name=claimed_name,
        ))
    return out


async def get_task_detail(s: AsyncSession, task_id: str, user: Any,
                          workspace: str = DEFAULT_WORKSPACE) -> TaskDetail:
    """`GET /api/tasks/{task}` (L 8.1): Aufgabe mit Schritt-Dokument (Markdown), Buttons, Feldern und `can_act`."""
    from app.domain import forms as F
    from app.domain import queries as Q

    row = (await s.execute(
        text("""SELECT t.*, r.title AS run_title, r.status AS run_status, r.current_step AS run_current_step,
                       r.workflow_id, r.version, r.started_by_id, r.started_by, r.input, r.steps, r.result,
                       v.definition AS wf_def, v.documents AS wf_docs
                FROM tasks t
                JOIN runs r ON r.id = t.run_id
                JOIN workflows w ON w.id = r.workflow_id
                JOIN workflow_versions v ON v.workflow_id = r.workflow_id AND v.version = r.version
                WHERE t.id = :id AND w.workspace_id = :ws"""),
        {"id": task_id, "ws": workspace})).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Aufgabe '{task_id}' wurde nicht gefunden")

    task_model = T.task_from_row(dict(row))
    run_dict = {
        "id": task_model.run_id,
        "workflow_id": row["workflow_id"],
        "version": row["version"],
        "title": row["run_title"],
        "status": row["run_status"],
        "current_step": row["run_current_step"],
        "started_by_id": row["started_by_id"],
        "started_by": _j(row["started_by"]),
        "input": _j(row["input"]),
        "steps": _j(row["steps"]),
        "result": _j(row["result"]),
    }
    definition = WorkflowDefinition.model_validate(_j(row["wf_def"]))
    frozen_docs = _j(row["wf_docs"]) or {}

    ctx = _ctx(s, workspace)
    actor = getattr(user, "actor", user)
    await ensure_run_view(ctx, run_dict, definition, actor)

    step_def = next((st for st in definition.steps if st.key == task_model.step), None)
    if step_def is None:
        raise PipelineError("NOT_FOUND", f"Schritt '{task_model.step}' nicht in Workflow-Version gefunden")

    doc_id = step_def.document
    md_out = await Q.fetch_document_markdown(s, doc_id, run=task_model.run_id, user=user)
    blocks = frozen_docs.get(doc_id) or []
    form_blk = next((b for b in blocks if b.get("type") == "form"), None)

    buttons_out: list[ButtonInfo] = []
    fields_out: list[dict[str, Any]] = []
    can_act_val = False

    roles = await T.actor_role_refs(ctx, actor)
    is_active_step = run_dict["status"] == "active" and run_dict["current_step"] == task_model.step
    can_act_val = (
        is_active_step
        and (actor.type == "system" or T.can_act(actor, roles, task_model))
        and not await F._has_waiting_subrun(s, task_model.run_id, task_model.step, blocks)
    )

    if form_blk is not None:
        columns = await F._load_columns(s, blocks)
        form = F.Form(form_blk, blocks, columns, owner={"workflow": row["workflow_id"], "step": task_model.step})
        if can_act_val:
            buttons_out = [
                ButtonInfo(
                    id=b["id"],
                    label=b.get("label") or b["id"],
                    style=b.get("style") or "secondary",
                    outcome=b.get("outcome"),
                    require=list(b.get("require") or []),
                    confirm=b.get("confirm"),
                )
                for b in form.buttons
            ]
        for f in form.fields.values():
            entry: dict[str, Any] = {
                "key": f["key"],
                "label": f["label"],
                "input": f["type"]["kind"],
                "required": f["required"],
            }
            if f["type"].get("options"):
                entry["options"] = f["type"]["options"]
            fields_out.append(entry)
        for li in form.items.values():
            fields_out.append({
                "key": li["key"],
                "label": li["label"],
                "input": "line_items",
                "required": bool(li.get("min_rows")),
                "min_rows": li.get("min_rows"),
                "columns": [
                    {"key": c["key"], "label": c["label"], "input": c["type"]["kind"], "required": c["required"]}
                    for c in li["columns"].values()
                ],
            })

    return TaskDetail(
        task=task_model,
        run_title=row["run_title"],
        document_id=doc_id,
        document_markdown=md_out["markdown"],
        form_block=form_blk["id"] if form_blk else None,
        buttons=buttons_out,
        fields=fields_out,
        can_act=can_act_val,
    )


async def list_notifications(s: AsyncSession, viewer: Actor, *, unread: bool = False) -> list[Notification]:
    who = T.effective_id(viewer)
    cond = "recipient_id = :u" + (" AND read_at IS NULL" if unread else "")
    rows = (await s.execute(
        text(f"SELECT id, recipient_id, run_id, task_id, type, payload, created_at, read_at "
             f"FROM notifications WHERE {cond} ORDER BY created_at DESC, id DESC LIMIT 100"),
        {"u": who})).mappings().all()
    return [
        Notification(
            id=r["id"],
            recipient_id=r["recipient_id"],
            run_id=r["run_id"],
            task_id=r["task_id"],
            type=r["type"],
            payload=_j(r["payload"]) or {},
            created_at=r["created_at"],
            read_at=r["read_at"],
        )
        for r in rows
    ]


async def delete_notification(s: AsyncSession, notification_id: str, viewer: Actor) -> None:
    """Entfernt eine Benachrichtigung der eigenen Person (3.F5, B21)."""
    who = T.effective_id(viewer)
    row = (await s.execute(
        text("SELECT recipient_id FROM notifications WHERE id = :id"),
        {"id": notification_id})).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Benachrichtigung '{notification_id}' wurde nicht gefunden")
    if viewer.type != "system" and row["recipient_id"] != who:
        raise PipelineError("FORBIDDEN", "Diese Benachrichtigung gehört einer anderen Person",
                            {"notification": notification_id})
    await s.execute(text("DELETE FROM notifications WHERE id = :id"), {"id": notification_id})
    await s.commit()


async def mark_notification_read(s: AsyncSession, notification_id: str, viewer: Actor) -> Notification:
    who = T.effective_id(viewer)
    row = (await s.execute(
        text("SELECT id, recipient_id, run_id, task_id, type, payload, created_at, read_at "
             "FROM notifications WHERE id = :id"),
        {"id": notification_id})).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Benachrichtigung '{notification_id}' wurde nicht gefunden")
    if viewer.type != "system" and row["recipient_id"] != who:
        raise PipelineError("FORBIDDEN", "Diese Benachrichtigung gehört einer anderen Person",
                            {"notification": notification_id})
    if row["read_at"] is None:
        row = (await s.execute(
            text("""UPDATE notifications SET read_at = now() WHERE id = :id
                    RETURNING id, recipient_id, run_id, task_id, type, payload, created_at, read_at"""),
            {"id": notification_id})).mappings().first()
        await s.commit()
    return Notification(
        id=row["id"],
        recipient_id=row["recipient_id"],
        run_id=row["run_id"],
        task_id=row["task_id"],
        type=row["type"],
        payload=_j(row["payload"]) or {},
        created_at=row["created_at"],
        read_at=row["read_at"],
    )