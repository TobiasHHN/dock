"""Handler für Rollen und Rollenzuweisung (Task 1.1, L 5.8, L 6.1 „Nutzer und Rollen“, L 9).

Die Pipeline hat Rollen-Keys schon zu IDs aufgelöst, das Recht (`einkauf`) geprüft und die Kanäle `workspace`
bzw. `user:<id>` gesperrt. Rollen haben keine Versionsspalte, deshalb kein `ctx.touch`.
Rollen werden beim Handeln geprüft (L 5.8): Eine Zuweisung wirkt ab dem nächsten Request bzw. Batch.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text

from app.domain import references
from app.ops.context import OpContext
from app.ops.errors import PipelineError
from app.ops.handlers import register

_KEY = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _check_key(key: str, field: str = "key") -> None:
    if key.startswith("rol_") or not _KEY.match(key):
        raise PipelineError("VALIDATION", f"Ungültiger Rollen-Key '{key}'", {"errors": {
            field: "Kleinbuchstaben, Ziffern und _, beginnt mit einem Buchstaben, nicht mit 'rol_'"}})


def _check_name(name: str, field: str = "name") -> None:
    if not name.strip():
        raise PipelineError("VALIDATION", "Der Rollenname darf nicht leer sein", {"errors": {field: "Pflichtfeld"}})


async def _role(ctx: OpContext, role_id: str) -> dict[str, Any]:
    row = (await ctx.session.execute(
        text("SELECT id, key, name FROM roles WHERE id = :id AND workspace_id = :ws"),
        {"id": role_id, "ws": ctx.workspace_id})).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Rolle '{role_id}' wurde nicht gefunden")
    return dict(row)


async def _key_taken(ctx: OpContext, key: str, except_id: str | None = None) -> bool:
    found = (await ctx.session.execute(
        text("SELECT id FROM roles WHERE workspace_id = :ws AND key = :key"),
        {"ws": ctx.workspace_id, "key": key})).scalar_one_or_none()
    return found is not None and found != except_id


@register("role.create")
async def role_create(ctx: OpContext, op: Any) -> dict[str, Any]:
    if not op.id.startswith("rol_"):
        raise PipelineError("VALIDATION", "Rollen-IDs beginnen mit 'rol_'", {"errors": {"id": "Präfix 'rol_'"}})
    _check_key(op.key)
    _check_name(op.name)
    if await _key_taken(ctx, op.key):
        raise PipelineError("VALIDATION", f"Rolle mit Key '{op.key}' existiert bereits",
                            {"errors": {"key": "bereits vergeben"}})
    await ctx.session.execute(
        text("INSERT INTO roles (id, workspace_id, key, name) VALUES (:id, :ws, :key, :name)"),
        {"id": op.id, "ws": ctx.workspace_id, "key": op.key, "name": op.name.strip()})
    ctx.add_inverse({"op": "role.delete", "role": op.id})
    return {"id": op.id}


@register("role.update")
async def role_update(ctx: OpContext, op: Any) -> None:
    old = await _role(ctx, op.role)
    key = old["key"] if op.key is None else op.key
    name = old["name"] if op.name is None else op.name.strip()
    if op.key is not None:
        _check_key(op.key)
        if await _key_taken(ctx, op.key, except_id=op.role):
            raise PipelineError("VALIDATION", f"Rolle mit Key '{op.key}' existiert bereits",
                                {"errors": {"key": "bereits vergeben"}})
    if op.name is not None:
        _check_name(op.name)
    await ctx.session.execute(text("UPDATE roles SET key = :key, name = :name WHERE id = :id"),
                              {"id": op.role, "key": key, "name": name})
    ctx.add_inverse({"op": "role.update", "role": op.role, "key": old["key"], "name": old["name"]})


@register("role.delete")
async def role_delete(ctx: OpContext, op: Any) -> None:
    old = await _role(ctx, op.role)
    used = await references.usages(ctx, "role", op.role)
    members = list((await ctx.session.execute(
        text("SELECT member_id FROM member_roles WHERE role_id = :id ORDER BY member_id"),
        {"id": op.role})).scalars())
    if used or members:
        parts = [f"{u['source_kind']} {u['source_id']} ({u['via']})" for u in used]
        if members:
            parts.append(f"{len(members)} Mitglied(er)")
        raise PipelineError("IN_USE", f"Rolle '{old['key']}' wird noch verwendet: " + ", ".join(parts),
                            {"usages": used, "members": members})
    await ctx.session.execute(text("DELETE FROM roles WHERE id = :id"), {"id": op.role})
    ctx.add_inverse({"op": "role.create", "id": old["id"], "key": old["key"], "name": old["name"]})


async def _set_roles(ctx: OpContext, op_name: str, member_field: str, member_id: str,
                     add: list[str], remove: list[str]) -> dict[str, Any]:
    overlap = set(add) & set(remove)
    if overlap:
        raise PipelineError("VALIDATION", "Eine Rolle kann nicht gleichzeitig hinzugefügt und entfernt werden",
                            {"errors": {"add": f"auch in remove: {', '.join(sorted(overlap))}"}})
    for role_id in [*add, *remove]:
        await _role(ctx, role_id)
    current = set((await ctx.session.execute(
        text("SELECT role_id FROM member_roles WHERE workspace_id = :ws AND member_id = :m"),
        {"ws": ctx.workspace_id, "m": member_id})).scalars())
    added = [r for r in dict.fromkeys(add) if r not in current]
    removed = [r for r in dict.fromkeys(remove) if r in current]
    for role_id in added:
        await ctx.session.execute(
            text("INSERT INTO member_roles (workspace_id, member_id, role_id) VALUES (:ws, :m, :r)"),
            {"ws": ctx.workspace_id, "m": member_id, "r": role_id})
    if removed:
        await ctx.session.execute(
            text("DELETE FROM member_roles WHERE workspace_id = :ws AND member_id = :m AND role_id = ANY(:r)"),
            {"ws": ctx.workspace_id, "m": member_id, "r": removed})
    if added or removed:
        ctx.add_inverse({"op": op_name, member_field: member_id, "add": removed, "remove": added})
    return {"roles": sorted((current | set(added)) - set(removed))}


@register("user.set_roles")
async def user_set_roles(ctx: OpContext, op: Any) -> dict[str, Any]:
    exists = (await ctx.session.execute(text("SELECT 1 FROM users WHERE id = :id"),
                                        {"id": op.user})).scalar_one_or_none()
    if exists is None:
        raise PipelineError("NOT_FOUND", f"Nutzer '{op.user}' wurde nicht gefunden")
    return await _set_roles(ctx, "user.set_roles", "user", op.user, op.add, op.remove)


@register("agent.set_roles")
async def agent_set_roles(ctx: OpContext, op: Any) -> dict[str, Any]:
    exists = (await ctx.session.execute(text("SELECT 1 FROM agents WHERE id = :id AND workspace_id = :ws"),
                                        {"id": op.agent, "ws": ctx.workspace_id})).scalar_one_or_none()
    if exists is None:
        raise PipelineError("NOT_FOUND", f"Agent '{op.agent}' wurde nicht gefunden")
    return await _set_roles(ctx, "agent.set_roles", "agent", op.agent, op.add, op.remove)
