"""Die transaktionale Op-Pipeline (T 2.4, T 2.5, L 6.2).

Reihenfolge in einer Transaktion:
  0. Advisory-Lock auf `batch_id` (parallele Wiederholung wartet), dann Idempotenz-Treffer in `batches`
  1. `import.include` ersetzen (L 8.3)
  2. Rechte pro Op prüfen (L 6.2 Schritt 2, vor allem anderen Zugriff auf Daten)
  3. Keys in IDs auflösen
  4. Kanäle sortiert sperren (`seq + 1`), erst danach `base`-Versionen prüfen (sonst Lost Update)
  5. Handler ausführen (Registry in `ops/handlers`), danach Versionen erhöhen
  6. Referenz-Index aktualisieren
  7. Op-Log mit inversen Ops pro Kanal schreiben, Ergebnis in `batches` ablegen
  8. `pg_notify('ops', {channel, seq})` je Kanal: Postgres liefert das erst beim Commit aus (T 2.7)
Nach dem Commit: `enqueue_reembed` für geänderte Dokumente, Tabellen und Workflows (T 3.2).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.domain import references
from app.imports.store import take_ops
from app.ops.context import VERSIONED, OpContext
from app.ops.errors import PipelineError
from app.ops.handlers import HANDLERS, load_handlers
from app.schemas.common import Actor
from app.schemas.ops import BatchResult, Op, OpBatch
from app.search.embeddings import enqueue_reembed

log = logging.getLogger(__name__)

_OP_ADAPTER = TypeAdapter(Op)

# Demo-Vereinfachung (hackathon-plan.md, Abschnitt Rechte): Schema-, Dokument-, Workflow- und Rollenänderungen
# nur für `einkauf`. Zeilen-, Entwurfs-, Run- und Aufgaben-Ops stehen jedem angemeldeten Akteur offen; ihre
# fachlichen Regeln (Startberechtigung, can_act, Sichtbarkeit) prüfen die Handler der Engine (4.2, 3.3).
PRIVILEGED_ROLE = "einkauf"
PRIVILEGED_PREFIXES = ("table.", "column.", "doc.", "block.", "workflow.", "role.")
PRIVILEGED_OPS = {"text.edit", "user.set_roles", "agent.set_roles"}
# Ops, die Listen im Kanal `workspace` ändern (L 7.2). Zeilen- und Blockänderungen sperren ihn bewusst nicht,
# sonst liefen alle Batches nacheinander (T 2.5).
WORKSPACE_PREFIXES = ("workflow.", "role.")
WORKSPACE_OPS = {"table.create", "table.update", "table.delete", "doc.create", "doc.update", "doc.delete",
                 "user.set_roles", "agent.set_roles"}


async def apply_batch(batch: OpBatch, actor: Actor, session: AsyncSession | None = None) -> BatchResult:
    """Führt einen Batch atomar aus. Wirft `PipelineError` bei Ablehnung (Transaktion ist dann zurückgerollt).

    Ohne `session` öffnet die Funktion eine eigene Sitzung und committet. Mit `session` (Tests, Aufrufer mit
    eigener Transaktion) läuft der Batch in einer eigenen Transaktion bzw. einem Savepoint; ist die Sitzung
    schon in einer Transaktion, commitet der Aufrufer, dann entfällt auch das Einreihen der Neu-Einbettung."""
    load_handlers()
    owns_session = session is None
    db = session or SessionLocal()
    outer = db.in_transaction()
    try:
        async with (db.begin_nested() if outer else db.begin()):
            ctx, result = await _run(db, batch, actor)
    except IntegrityError as exc:
        raise PipelineError("VALIDATION", f"Die Änderung verletzt eine Datenbankregel: {_db_message(exc)}",
                            {"errors": {"batch": _db_message(exc)}}) from exc
    finally:
        if owns_session:
            await db.close()

    if ctx is not None and not outer:  # ctx ist None bei Idempotenz-Treffer: dann nichts neu einreihen
        for source_kind, source_id in ctx.reembed:
            try:
                await enqueue_reembed(source_kind, source_id)
            except Exception:  # Suche ist nachrangig, der Batch ist bereits committet
                log.exception("enqueue_reembed(%s, %s) fehlgeschlagen", source_kind, source_id)
    return result


async def _run(db: AsyncSession, batch: OpBatch, actor: Actor) -> tuple[OpContext | None, BatchResult]:
    # Parallele Wiederholung mit gleicher batch_id wartet hier, bis der erste Versuch committet hat.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 0))"), {"id": batch.batch_id})
    cached = await _cached_result(db, batch.batch_id)
    if cached is not None:
        return None, cached

    ctx = OpContext(session=db, actor=actor)
    ops, origins = await _expand_includes(ctx, batch.ops)
    for op in ops:
        await _check_permission(ctx, op)
    ops = [await _resolve_keys(ctx, op) for op in ops]

    for channel in sorted(await channels_for(ctx, ops)):
        await ctx.lock_channel(channel)
    await _check_base_versions(ctx, batch.base)

    for index, op in enumerate(ops):
        handler = HANDLERS.get(op.op)
        if handler is None:
            raise PipelineError("VALIDATION", f"Operation '{op.op}' ist noch nicht verfügbar",
                                {"errors": {f"ops[{origins[index][0]}].op": f"'{op.op}' ist nicht implementiert"}})
        ctx.op_index = origins[index][0]
        item = await handler(ctx, op)
        if item is not None and origins[index][1]:
            ctx.results[str(origins[index][0])] = item

    await _bump_versions(ctx)
    await references.update(ctx, list(ctx.reference_sources))
    await _append_oplog(ctx, batch.batch_id, ops)

    result = BatchResult(batch_id=batch.batch_id, seq=dict(ctx.seq), results=ctx.results)
    await db.execute(
        text("INSERT INTO batches (batch_id, result) VALUES (:id, CAST(:result AS jsonb))"),
        {"id": batch.batch_id, "result": json.dumps(result.model_dump(mode="json"))},
    )
    for channel, seq in ctx.seq.items():
        await db.execute(text("SELECT pg_notify('ops', :payload)"),
                         {"payload": json.dumps({"channel": channel, "seq": seq})})
    return ctx, result


# ── Idempotenz ───────────────────────────────────────────────────────────────


async def _cached_result(session: AsyncSession, batch_id: str) -> BatchResult | None:
    row = await session.execute(text("SELECT result FROM batches WHERE batch_id = :id"), {"id": batch_id})
    stored = row.scalar_one_or_none()
    if stored is None:
        return None
    return BatchResult.model_validate(json.loads(stored) if isinstance(stored, str) else stored)


# ── import.include (L 8.3) ───────────────────────────────────────────────────


async def _expand_includes(ctx: OpContext, ops: Iterable[Op]) -> tuple[list[Op], list[tuple[int, bool]]]:
    """Ersetzt `import.include` durch die gespeicherten Ops. Rückgabe: Ops und je Op
    `(Index im gesendeten Batch, darf Handler-Ergebnis unter diesem Index liefern)`."""
    expanded: list[Op] = []
    origins: list[tuple[int, bool]] = []
    for index, op in enumerate(ops):
        if op.op != "import.include":
            expanded.append(op)
            origins.append((index, True))
            continue
        imported = [_OP_ADAPTER.validate_python(item) for item in await _take_import(ctx, op.import_id)]
        if any(item.op == "import.include" for item in imported):
            raise PipelineError("IMPORT_INVALID", f"Import '{op.import_id}' enthält selbst ein import.include")
        ctx.results[str(index)] = {"included": len(imported)}
        expanded.extend(imported)
        origins.extend((index, False) for _ in imported)
    return expanded, origins


async def _take_import(ctx: OpContext, import_id: str) -> list[dict[str, Any]]:
    return await take_ops(ctx, import_id, ctx.actor)


# ── Rechte (L 5.8, Demo-Vereinfachung) ───────────────────────────────────────


async def _check_permission(ctx: OpContext, op: Op) -> None:
    if ctx.actor.type == "system":
        return
    if op.op.startswith(PRIVILEGED_PREFIXES) or op.op in PRIVILEGED_OPS:
        if PRIVILEGED_ROLE not in await ctx.actor_roles():
            raise PipelineError("FORBIDDEN", f"'{op.op}' erfordert die Rolle '{PRIVILEGED_ROLE}'", {"op": op.op})


# ── Keys auflösen (L 1) ──────────────────────────────────────────────────────


def _dump(op: Op) -> dict[str, Any]:
    return op.model_dump(mode="json", exclude_unset=True)


async def _resolve_keys(ctx: OpContext, op: Op) -> Op:
    """Ersetzt Tabellen-, Spalten-, Rollen- und Workflow-Keys durch IDs. Im selben Batch angelegte Objekte
    sind schon mit ihrem Key auffindbar (ID und Key kommen im selben `*.create`-Op vom Client).
    Keys innerhalb von Block-Props (table_view, Felder, Actions) lösen die Block-Handler (1.4) mit
    `ctx.resolve` auf, sie kennen die Struktur."""
    v = _dump(op)
    name = v["op"]

    async def table(field: str = "table") -> str:
        v[field] = await ctx.resolve("table", v[field])
        return v[field]

    async def col_type(type_: dict[str, Any] | None) -> None:
        if type_ and type_.get("kind") == "reference":
            type_["table"] = await ctx.resolve("table", type_["table"])

    if name == "table.create":
        ctx.remember_ref("table", v["key"], v["id"])
        for column in v["columns"]:
            ctx.remember_ref("column", column["key"], column["id"], v["id"])
        for column in v["columns"]:
            await col_type(column.get("type"))
        if v.get("display_column"):
            v["display_column"] = await ctx.resolve("column", v["display_column"], v["id"])
    elif name in {"table.update", "table.delete", "column.add", "column.update", "column.move",
                  "column.delete", "row.insert", "row.update", "row.move", "row.delete"}:
        table_id = await table()
        if name == "table.update" and v.get("display_column"):
            v["display_column"] = await ctx.resolve("column", v["display_column"], table_id)
        if name == "column.add":
            ctx.remember_ref("column", v["column"]["key"], v["column"]["id"], table_id)
            await col_type(v["column"].get("type"))
        if name == "column.update":
            await col_type(v["patch"].get("type"))
        if name in {"column.update", "column.move", "column.delete"}:
            v["column"] = await ctx.resolve("column", v["column"], table_id)
        if name in {"column.add", "column.move"} and v.get("after"):
            v["after"] = await ctx.resolve("column", v["after"], table_id)
        if name == "row.insert":
            for row in v["rows"]:
                row["values"] = await _resolve_value_keys(ctx, table_id, row["values"])
        if name == "row.update":
            v["values"] = await _resolve_value_keys(ctx, table_id, v["values"])
    elif name in {"role.create", "workflow.create"}:
        ctx.remember_ref(name.split(".")[0], v["key"], v["id"])
    elif name in {"role.update", "role.delete"}:
        v["role"] = await ctx.resolve("role", v["role"])
    elif name in {"workflow.update", "workflow.publish", "workflow.delete", "run.start"}:
        v["workflow"] = await ctx.resolve("workflow", v["workflow"])
    elif name in {"user.set_roles", "agent.set_roles"}:
        for field in ("add", "remove"):
            v[field] = [await ctx.resolve("role", ref) for ref in v.get(field, [])]
    else:
        return op
    return _OP_ADAPTER.validate_python(v)


async def _resolve_value_keys(ctx: OpContext, table_id: str, values: dict[str, Any]) -> dict[str, Any]:
    return {await ctx.resolve("column", key, table_id): value for key, value in values.items()}


# ── Kanäle (T 2.5) ───────────────────────────────────────────────────────────


async def channels_for(ctx: OpContext, ops: Iterable[Op]) -> set[str]:
    """Kanäle, die ein Batch mit diesen (aufgelösten) Ops sicher betrifft. Alles Weitere melden Handler
    über `ctx.lock_channel` / `ctx.touch(..., channel=...)`."""
    channels: set[str] = set()
    for op in ops:
        d, name = _dump(op), op.op
        if name in WORKSPACE_OPS or name.startswith(WORKSPACE_PREFIXES):
            channels.add("workspace")
        if name == "table.create":
            channels.add(f"table:{d['id']}")
        elif isinstance(d.get("table"), str):
            channels.add(f"table:{d['table']}")
        if name == "doc.create":
            channels.add(f"doc:{d['id']}")
        elif isinstance(d.get("doc"), str):
            channels.add(f"doc:{d['doc']}")
        if isinstance(d.get("block"), str):
            doc_id = (await ctx.session.execute(
                text("SELECT doc_id FROM blocks WHERE id = :id"), {"id": d["block"]})).scalar_one_or_none()
            if doc_id:
                channels.add(f"doc:{doc_id}")
        if name == "run.start":
            channels.add(f"run:{d['id']}")
        elif isinstance(d.get("run"), str):
            channels.add(f"run:{d['run']}")
        if isinstance(d.get("task"), str):
            run_id = (await ctx.session.execute(
                text("SELECT run_id FROM tasks WHERE id = :id"), {"id": d["task"]})).scalar_one_or_none()
            if run_id:
                channels.add(f"run:{run_id}")
        if name in {"user.set_roles"} and isinstance(d.get("user"), str):
            channels.add(f"user:{d['user']}")
    return channels


# ── Versionen (L 6.2 Schritte 4 und 6) ───────────────────────────────────────


async def _check_base_versions(ctx: OpContext, bases: dict[str, int]) -> None:
    """Läuft NACH dem Sperren der Kanäle, damit zwei Batches mit gleicher Basis nicht beide durchkommen."""
    tables = {"tbl": "tables", "row": "rows", "doc": "documents", "blk": "blocks"}
    conflicts: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for ref, expected in bases.items():
        table = tables.get(ref.partition("_")[0])
        if table is None:
            raise PipelineError("VALIDATION", f"base: unbekannter Objekttyp '{ref}'",
                                {"errors": {f"base.{ref}": "Nur tbl_, row_, doc_ und blk_ haben eine Version"}})
        current = (await ctx.session.execute(
            text(f"SELECT version FROM {table} WHERE id = :id"), {"id": ref})).scalar_one_or_none()
        if current is None:
            raise PipelineError("NOT_FOUND", f"Objekt '{ref}' wurde nicht gefunden")
        if current != expected:
            conflicts[ref] = {"expected": expected, "current": current}
            errors[f"base.{ref}"] = f"{ref} ist bei Version {current}, erwartet war {expected}"
    if conflicts:
        raise PipelineError("CONFLICT", "Eine oder mehrere Versionen sind nicht mehr aktuell",
                            {"versions": conflicts, "errors": errors})


async def _bump_versions(ctx: OpContext) -> None:
    for kind, id_ in ctx.touched:
        table = VERSIONED.get(kind)
        if table and (kind, id_) not in ctx.created and (kind, id_) not in ctx.deleted:
            await ctx.session.execute(text(f"UPDATE {table} SET version = version + 1 WHERE id = :id"), {"id": id_})


# ── Op-Log (L 6.2 Schritt 8) ─────────────────────────────────────────────────


async def _append_oplog(ctx: OpContext, batch_id: str, ops: list[Op]) -> None:
    # mit API-Schreibweise (`from` statt `from_`), so geht es auch an die Clients
    ops_json = json.dumps([op.model_dump(mode="json", exclude_unset=True, by_alias=True) for op in ops])
    inverse_json = json.dumps(list(reversed(ctx.inverse_ops)))
    actor_json = json.dumps(ctx.actor.model_dump(mode="json", exclude_none=True))
    for channel, seq in ctx.seq.items():
        await ctx.session.execute(
            text("""INSERT INTO oplog (channel, seq, batch_id, actor, ops, inverse)
                    VALUES (:channel, :seq, :batch_id, CAST(:actor AS jsonb), CAST(:ops AS jsonb),
                            CAST(:inverse AS jsonb))"""),
            {"channel": channel, "seq": seq, "batch_id": batch_id, "actor": actor_json,
             "ops": ops_json, "inverse": inverse_json})


def _db_message(exc: IntegrityError) -> str:
    return str(getattr(exc, "orig", exc)).splitlines()[0]
