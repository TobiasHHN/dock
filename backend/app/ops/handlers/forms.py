"""Handler für `draft.*` (L 4.4, L 7.6) und `form.submit` (L 4.6). Task 3.3.

Entwürfe liegen in `form_drafts` (Schlüssel: Formular-Block + Scope `user:<id>` oder `run:<id>`). Zeilen von
`line_items` stehen als `[{id, position, values}]` unter dem Feld-Key. Jede Entwurfs-Op sperrt den Kanal ihres
Scopes (`user:<id>` bzw. `run:<id>`), damit sie dort live verteilt wird. Rechte: ein `user`-Entwurf gehört dem
Akteur (bzw. der vertretenen Person), für `run`-Entwürfe prüft Task 4.3 zusätzlich `can_act`.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.domain import forms as F
from app.domain import positions
from app.ops.context import OpContext
from app.ops.errors import PipelineError
from app.ops.handlers import register
from app.schemas.ops import DraftItemDelete, DraftItemInsert, DraftItemUpdate, DraftSet, FormSubmit


def _invalid(path: str, message: str) -> PipelineError:
    return PipelineError("VALIDATION", f"{path}: {message}", {"errors": {path: message}})


async def _target(ctx: OpContext, form_block: str, scope: dict[str, str]) -> tuple[str, F.Form]:
    """Prüft Scope und Formular, sperrt den Kanal und liefert den Scope-Schlüssel."""
    if len(scope) != 1 or next(iter(scope)) not in ("run", "user"):
        raise _invalid("scope", "erwartet {\"run\": <id>} oder {\"user\": <id>}")
    kind, id_ = next(iter(scope.items()))
    if kind == "user":
        form = await F.load_form(ctx.session, form_block, ctx.workspace_id)
        member = ctx.actor.on_behalf_of or ctx.actor.id
        if ctx.actor.type != "system" and id_ != member:
            raise PipelineError("FORBIDDEN", "Ein Nutzer-Entwurf gehört dem jeweiligen Nutzer", {"scope": scope})
    else:
        from app.domain import tasks as T

        form, run_dict, _, step_key, _, open_task = await F.load_run_form(
            ctx.session, id_, form_block, ctx.workspace_id)
        if run_dict["status"] != "active" or run_dict["current_step"] != step_key:
            raise PipelineError("FORBIDDEN", "Formulare in abgeschlossenen oder inaktiven Schritten sind schreibgeschützt",
                                {"run": id_, "step": step_key})
        if open_task is None:
            raise PipelineError("TASK_DONE", f"Für Schritt '{step_key}' gibt es keine offene Aufgabe",
                                {"run": id_, "step": step_key})
        if ctx.actor.type != "system":
            task_model = T.task_from_row(open_task)
            roles = await T.actor_role_refs(ctx, ctx.actor)
            if not T.can_act(ctx.actor, roles, task_model):
                who = T.effective_id(ctx.actor)
                if who in task_model.excluded:
                    raise PipelineError("FORBIDDEN", "Vier-Augen-Prinzip: Sie sind für diese Aufgabe ausgeschlossen",
                                        {"task": task_model.id})
                is_cand = who in task_model.candidates.users or bool(set(roles) & set(task_model.candidates.roles))
                if is_cand and task_model.claimed_by is not None:
                    raise PipelineError(
                        "TASK_CLAIMED",
                        f"Aufgabe wird bereits von {task_model.claimed_by.name or task_model.claimed_by.id} bearbeitet",
                        {"claimed_by": task_model.claimed_by.model_dump(mode="json", exclude_none=True)},
                    )
                raise PipelineError("FORBIDDEN", "Sie sind für diese Aufgabe nicht zuständig", {"task": task_model.id})
    await ctx.lock_channel(f"{kind}:{id_}")
    return f"{kind}:{id_}", form


async def _load(ctx: OpContext, form_block: str, scope: str) -> dict[str, Any]:
    row = (await ctx.session.execute(
        text('SELECT "values" FROM form_drafts WHERE form_block = :b AND scope = :s FOR UPDATE'),
        {"b": form_block, "s": scope})).scalar_one_or_none()
    return F._j(row) or {} if row is not None else {}


async def _save(ctx: OpContext, form_block: str, scope: str, values: dict[str, Any]) -> int:
    res = await ctx.session.execute(
        text("""INSERT INTO form_drafts (form_block, scope, "values") VALUES (:b, :s, CAST(:v AS jsonb))
                ON CONFLICT (form_block, scope) DO UPDATE
                SET "values" = EXCLUDED."values", version = form_drafts.version + 1, updated_at = now()
                RETURNING version"""),
        {"b": form_block, "s": scope, "v": json.dumps(values)})
    return res.scalar_one()


def _ordered(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda i: i.get("position") or "")


def _scope(op: Any) -> dict[str, str]:
    return dict(op.scope)


@register("draft.set")
async def draft_set(ctx: OpContext, op: DraftSet) -> dict[str, Any]:
    scope, form = await _target(ctx, op.form_block, op.scope)
    if op.key in form.items:
        raise _invalid("key", f"„{op.key}“ ist eine Zeilenliste, Zeilen ändern draft.item_insert/update/delete")
    if op.key not in form.fields:
        raise _invalid("key", f"Das Formular hat kein Feld „{op.key}“")
    values = await _load(ctx, op.form_block, scope)
    old = values.get(op.key)
    if op.value is None:
        values.pop(op.key, None)
    else:
        values[op.key] = op.value
    ctx.add_inverse({"op": "draft.set", "form_block": op.form_block, "scope": _scope(op), "key": op.key,
                     "value": old})
    return {"version": await _save(ctx, op.form_block, scope, values)}


def _item_values(form: F.Form, key: str, values: dict[str, Any], path: str) -> None:
    unknown = [k for k in values if k not in form.items[key]["columns"]]
    if unknown:
        raise _invalid(path, f"unbekannte Spalte(n) {', '.join(unknown)} in „{key}“")


def _items_target(form: F.Form, key: str) -> None:
    if key not in form.items:
        raise _invalid("key", f"Das Formular hat keine Zeilenliste „{key}“")


@register("draft.item_insert")
async def draft_item_insert(ctx: OpContext, op: DraftItemInsert) -> dict[str, Any]:
    scope, form = await _target(ctx, op.form_block, op.scope)
    _items_target(form, op.key)
    item_id = op.item.get("id")
    if not isinstance(item_id, str) or not item_id:
        raise _invalid("item.id", "jede Zeile braucht eine ID")
    cells = op.item.get("values") or {}
    _item_values(form, op.key, cells, "item.values")
    values = await _load(ctx, op.form_block, scope)
    items = _ordered(values.get(op.key) or [])
    if any(i["id"] == item_id for i in items):
        raise _invalid("item.id", f"Zeile „{item_id}“ existiert schon")
    ids = [i["id"] for i in items]
    if op.after is None:
        position = positions.between(items[-1]["position"] if items else None, None)
    elif op.after == "^":
        position = positions.between(None, items[0]["position"] if items else None)
    elif op.after in ids:
        index = ids.index(op.after)
        upper = items[index + 1]["position"] if index + 1 < len(items) else None
        position = positions.between(items[index]["position"], upper)
    else:
        raise _invalid("after", f"„{op.after}“ ist keine Zeile in „{op.key}“")
    items.append({"id": item_id, "position": position, "values": cells})
    values[op.key] = _ordered(items)
    ctx.add_inverse({"op": "draft.item_delete", "form_block": op.form_block, "scope": _scope(op), "key": op.key,
                     "item_id": item_id})
    return {"version": await _save(ctx, op.form_block, scope, values)}


def _find(items: list[dict[str, Any]], item_id: str, key: str) -> dict[str, Any]:
    found = next((i for i in items if i["id"] == item_id), None)
    if found is None:
        raise PipelineError("NOT_FOUND", f"Zeile „{item_id}“ in „{key}“ wurde nicht gefunden",
                            {"errors": {"item_id": "unbekannte Zeile"}})
    return found


@register("draft.item_update")
async def draft_item_update(ctx: OpContext, op: DraftItemUpdate) -> dict[str, Any]:
    scope, form = await _target(ctx, op.form_block, op.scope)
    _items_target(form, op.key)
    _item_values(form, op.key, op.values, "values")
    values = await _load(ctx, op.form_block, scope)
    item = _find(values.get(op.key) or [], op.item_id, op.key)
    old = {k: item["values"].get(k) for k in op.values}
    for k, v in op.values.items():
        if v is None:
            item["values"].pop(k, None)
        else:
            item["values"][k] = v
    ctx.add_inverse({"op": "draft.item_update", "form_block": op.form_block, "scope": _scope(op), "key": op.key,
                     "item_id": op.item_id, "values": old})
    return {"version": await _save(ctx, op.form_block, scope, values)}


@register("draft.item_delete")
async def draft_item_delete(ctx: OpContext, op: DraftItemDelete) -> dict[str, Any]:
    scope, form = await _target(ctx, op.form_block, op.scope)
    _items_target(form, op.key)
    values = await _load(ctx, op.form_block, scope)
    items = _ordered(values.get(op.key) or [])
    item = _find(items, op.item_id, op.key)
    index = items.index(item)
    ctx.add_inverse({"op": "draft.item_insert", "form_block": op.form_block, "scope": _scope(op), "key": op.key,
                     "item": {"id": item["id"], "values": item["values"]},
                     "after": items[index - 1]["id"] if index else "^"})
    values[op.key] = [i for i in items if i["id"] != op.item_id]
    return {"version": await _save(ctx, op.form_block, scope, values)}


@register("form.submit")
async def form_submit(ctx: OpContext, op: FormSubmit) -> dict[str, Any]:
    return await F.submit_form(ctx, op)
