"""Snapshots je Kanaltyp (L 7.3, Datenform: `SnapshotDoc` … `SnapshotWorkspace` in `schemas/ws.py`).

`build(channel, user)` ist der einzige Einstieg. Es liest Stand und `seq` in EINER Transaktion mit
Snapshot-Isolation, damit nach dem Snapshot lückenlos ab `seq + 1` weiterverteilt werden kann.

`_doc` und `_table` nutzen die Leselogik aus `domain/queries.py` (Task 1.4).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db import session as db
from app.domain import queries
from app.ops.context import DEFAULT_WORKSPACE
from app.ops.errors import PipelineError
from app.realtime.access import load_roles, parse_channel

# Nur jsonb-Spalten der hier gelesenen Tabellen. NICHT "type": in run_events, notifications und blocks ist
# das Text ("run_started", ...); columns.type (jsonb) liest `queries` selbst (2.I2-Bug).
_JSON_COLUMNS = {"props", "values", "default", "result", "input", "steps", "started_by", "claimed_by",
                 "completed_by", "actor", "payload", "draft", "created_by", "updated_by"}


def _row(mapping: Any) -> dict[str, Any]:
    out = dict(mapping)
    for key in _JSON_COLUMNS & out.keys():
        if isinstance(out[key], str):
            out[key] = json.loads(out[key])
    return out


async def _all(s: AsyncSession, sql: str, **params: Any) -> list[dict[str, Any]]:
    return [_row(r) for r in (await s.execute(text(sql), params)).mappings().all()]


async def build(channel: str, user: CurrentUser) -> tuple[int, dict[str, Any]]:
    """Liefert `(seq, data)`. Wirft `PipelineError(NOT_FOUND)`, wenn das Objekt nicht mehr existiert."""
    kind, id_ = parse_channel(channel)
    async with db.SessionLocal() as s:
        await s.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        seq = (await s.execute(text("SELECT seq FROM channels WHERE id = :c"), {"c": channel})).scalar_one_or_none()
        data = await _READERS[kind](s, id_, user)
        return int(seq or 0), jsonable_encoder(data)


async def _doc(s: AsyncSession, id_: str, user: CurrentUser) -> dict[str, Any]:
    return await queries.fetch_document(s, id_)


async def _table(s: AsyncSession, id_: str, user: CurrentUser) -> dict[str, Any]:
    return await queries.fetch_table_snapshot(s, id_)


async def _run(s: AsyncSession, id_: str, user: CurrentUser) -> dict[str, Any]:
    runs = await _all(s, "SELECT * FROM runs WHERE id = :id", id=id_)
    if not runs:
        raise PipelineError("NOT_FOUND", f"run:{id_} wurde nicht gefunden")
    tasks = await _all(s, "SELECT * FROM tasks WHERE run_id = :id AND status = 'open' ORDER BY created_at LIMIT 1",
                       id=id_)
    events = await _all(s, "SELECT * FROM run_events WHERE run_id = :id ORDER BY at, id", id=id_)
    drafts = await _all(s, 'SELECT form_block, scope, "values", version, updated_at FROM form_drafts '
                           "WHERE scope = :scope", scope=f"run:{id_}")
    return {"run": runs[0], "task": tasks[0] if tasks else None, "events": events, "drafts": drafts}


async def _user(s: AsyncSession, id_: str, user: CurrentUser) -> dict[str, Any]:
    keys, ids = await load_roles(s, id_)
    tasks = await _all(
        s, """SELECT * FROM tasks WHERE status = 'open' AND NOT (:u = ANY(excluded)) AND (
                  :u = ANY(candidate_users) OR candidate_roles && CAST(:roles AS text[]) OR claimed_by_id = :u)
              ORDER BY created_at""", u=id_, roles=keys + ids)
    runs = await _all(s, "SELECT * FROM runs WHERE started_by_id = :u ORDER BY started_at DESC", u=id_)
    notes = await _all(s, "SELECT * FROM notifications WHERE recipient_id = :u ORDER BY created_at DESC LIMIT 100",
                       u=id_)
    drafts = await _all(s, 'SELECT form_block, scope, "values", version, updated_at FROM form_drafts '
                           "WHERE scope = :scope", scope=f"user:{id_}")
    return {"tasks": tasks, "runs": runs, "notifications": notes, "drafts": drafts}


async def _workspace(s: AsyncSession, id_: str, user: CurrentUser) -> dict[str, Any]:
    ws = {"ws": DEFAULT_WORKSPACE}
    return {
        "documents": await _all(s, "SELECT id, title, version, updated_at FROM documents WHERE workspace_id = :ws "
                                   "ORDER BY title, id", **ws),
        "tables": await _all(s, "SELECT id, key, name, version FROM tables WHERE workspace_id = :ws "
                                "ORDER BY name, id", **ws),
        "workflows": await _all(s, "SELECT id, key, name, latest_version FROM workflows WHERE workspace_id = :ws "
                                   "ORDER BY name, id", **ws),
        "roles": await _all(s, "SELECT id, key, name FROM roles WHERE workspace_id = :ws ORDER BY name, id", **ws),
    }


_READERS = {"doc": _doc, "table": _table, "run": _run, "user": _user, "workspace": _workspace}
