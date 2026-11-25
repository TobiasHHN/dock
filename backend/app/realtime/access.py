"""Leserechte pro Kanal (L 7.3: „Jeder Client sieht nur Kanäle, für die er Leserechte hat“).

Demo-Regeln (Rechte-Modell im Detail ist laut Plan nicht im Scope):
- `workspace`, `table:<id>`, `doc:<id>`: jeder angemeldete Nutzer, wenn das Objekt im Workspace existiert.
- `user:<id>`: nur die Person selbst (auch ein Agent in ihrem Auftrag).
- `run:<id>`: Antragsteller, Kandidaten/Übernehmer/Erledigende einer Aufgabe des Runs (Person oder Rolle)
  und die Rolle `einkauf` (Verwalter, sieht alle Runs).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.ops.context import DEFAULT_WORKSPACE
from app.ops.errors import PipelineError
from app.ops.pipeline import PRIVILEGED_ROLE

CHANNEL_KINDS = {"doc", "table", "run", "user"}


def parse_channel(channel: str) -> tuple[str, str]:
    """`doc:doc_1` -> ("doc", "doc_1"); `workspace` -> ("workspace", ""). Wirft VALIDATION bei Unbekanntem."""
    if channel == "workspace":
        return "workspace", ""
    kind, sep, id_ = channel.partition(":")
    if not sep or not id_ or kind not in CHANNEL_KINDS:
        raise PipelineError("VALIDATION", f"Unbekannter Kanal '{channel}'", {"errors": {"channel": "unbekannt"}})
    return kind, id_


async def load_roles(session: AsyncSession, user_id: str) -> tuple[list[str], list[str]]:
    """Aktuelle Rollen der Person: (Keys, IDs). Rollen werden beim Handeln geprüft, nicht beim Verbinden."""
    rows = (await session.execute(
        text("""SELECT r.key, r.id FROM member_roles mr JOIN roles r ON r.id = mr.role_id
                WHERE mr.member_id = :u AND mr.workspace_id = :ws"""),
        {"u": user_id, "ws": DEFAULT_WORKSPACE})).all()
    return [r[0] for r in rows], [r[1] for r in rows]


async def check_read(session: AsyncSession, user: CurrentUser, channel: str) -> None:
    """Wirft `PipelineError` (FORBIDDEN, NOT_FOUND, VALIDATION), wenn `user` den Kanal nicht lesen darf."""
    kind, id_ = parse_channel(channel)
    if kind == "workspace":
        return
    if kind == "user":
        if id_ != user.id:
            raise PipelineError("FORBIDDEN", "Dieser Kanal gehört einer anderen Person", {"channel": channel})
        return
    if kind in {"doc", "table"}:
        table = "documents" if kind == "doc" else "tables"
        found = (await session.execute(
            text(f"SELECT 1 FROM {table} WHERE id = :id AND workspace_id = :ws"),
            {"id": id_, "ws": DEFAULT_WORKSPACE})).scalar_one_or_none()
        if found is None:
            raise PipelineError("NOT_FOUND", f"'{channel}' wurde nicht gefunden", {"channel": channel})
        return

    run = (await session.execute(text("SELECT started_by_id FROM runs WHERE id = :id"), {"id": id_})).first()
    if run is None:
        raise PipelineError("NOT_FOUND", f"'{channel}' wurde nicht gefunden", {"channel": channel})
    keys, ids = await load_roles(session, user.id)
    if run[0] == user.id or PRIVILEGED_ROLE in keys:
        return
    involved = (await session.execute(
        text("""SELECT 1 FROM tasks WHERE run_id = :run AND (
                    :u = ANY(candidate_users) OR candidate_roles && CAST(:roles AS text[])
                    OR claimed_by_id = :u OR completed_by->>'id' = :u) LIMIT 1"""),
        {"run": id_, "u": user.id, "roles": keys + ids})).scalar_one_or_none()
    if involved is None:
        raise PipelineError("FORBIDDEN", "Kein Zugriff auf diesen Run", {"channel": channel})
