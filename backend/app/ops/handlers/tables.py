"""Handler für `table.*`, `column.*` und `row.*` (L 2, Task 1.3).

Die Fachregeln stehen in `app.domain.tables` (dieselben Funktionen nutzt `app.ops.memory` für die Fixtures).
Hier steckt nur der Postgres-Teil: laden, Eindeutigkeit und Verweise gegen die Datenbank prüfen, schreiben,
`row_links` und Referenz-Index pflegen, inverse Ops für Undo melden.

Konventionen:
- Ankerloses Einfügen (`column.add`, `row.insert` ohne `after`) hängt ans Ende. `column.move`/`row.move` mit
  `after=None` verschieben an den Anfang.
- Zeilen-Ops melden die Tabelle nur über `ctx.changed` (Suche), nicht über `touch`: deren `version` ist die
  Schema-Version und steigt nur bei `table.*` und `column.*` (L 2.1).
- Fehlerpfade (`details.errors`): Spalten-Key der Zelle, bei mehreren Zeilen in einem `row.insert`
  `rows[<index>].<key>`; bei Definitionen `columns[<index>].<feld>` bzw. `column.<feld>` / `patch.<feld>`.
"""
from __future__ import annotations

import functools
import json
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text

from app.domain import positions, references
from app.domain.tables import (
    DomainError, RowDeletePlan, blocked_error, check_column_definition, check_key, convert_values,
    find_duplicates, in_use_error, plan_row_delete, prepare_values, resolve_default, type_dict, validation_error,
)
from app.ops.context import OpContext
from app.ops.errors import PipelineError
from app.ops.handlers import register

COLUMN_FIELDS = ("id", "key", "name", "type", "required", "unique", "default", "position")
MAX_LISTED = 5  # so viele betroffene Zeilen nennt eine Fehlermeldung höchstens


def op_handler(name: str):
    """Registriert den Handler und übersetzt `DomainError` in `PipelineError`."""
    def decorator(fn: Callable[[OpContext, Any], Awaitable[Any]]):
        @functools.wraps(fn)
        async def wrapper(ctx: OpContext, op: Any):
            try:
                return await fn(ctx, op)
            except DomainError as exc:
                details: dict[str, Any] = dict(exc.details)
                if exc.fields:
                    details["errors"] = exc.fields
                raise PipelineError(exc.code, exc.message, details or None) from exc
        register(name)(wrapper)
        return fn
    return decorator


def fail(fields: dict[str, str], subject: str) -> DomainError:
    return validation_error(fields, subject)


# ── Laden ────────────────────────────────────────────────────────────────────


def _dump(value: Any) -> str | None:
    return None if value is None else json.dumps(value)


async def _table(ctx: OpContext, table_id: str) -> dict[str, Any]:
    row = (await ctx.session.execute(
        text("SELECT id, key, name, display_column, version FROM tables WHERE id = :id AND workspace_id = :ws"),
        {"id": table_id, "ws": ctx.workspace_id})).mappings().first()
    if row is None:
        raise DomainError("NOT_FOUND", f"Tabelle '{table_id}' wurde nicht gefunden")
    return dict(row)


async def _columns(ctx: OpContext, table_id: str) -> list[dict[str, Any]]:
    rows = (await ctx.session.execute(
        text('''SELECT id, key, name, type, required, "unique", "default", position
                FROM columns WHERE table_id = :t ORDER BY position, id'''), {"t": table_id})).mappings().all()
    return [{**r, "type": r["type"], "default": r["default"]} for r in rows]


def _column(columns: list[dict[str, Any]], column_id: str, table: dict[str, Any]) -> dict[str, Any]:
    for col in columns:
        if col["id"] == column_id:
            return col
    raise DomainError("NOT_FOUND", f"Spalte '{column_id}' gehört nicht zur Tabelle „{table['name']}“")


async def _row(ctx: OpContext, table: dict[str, Any], row_id: str) -> dict[str, Any]:
    row = (await ctx.session.execute(
        text("SELECT id, position, values, version FROM rows WHERE id = :id AND table_id = :t"),
        {"id": row_id, "t": table["id"]})).mappings().first()
    if row is None:
        raise DomainError("NOT_FOUND", f"Zeile '{row_id}' wurde in Tabelle „{table['name']}“ nicht gefunden")
    return {**row, "values": row["values"]}


def _actor_json(ctx: OpContext) -> str:
    return json.dumps(ctx.actor.model_dump(mode="json", exclude_none=True))


def _user_id(ctx: OpContext) -> str:
    return ctx.actor.on_behalf_of or ctx.actor.id


def _column_for_inverse(col: dict[str, Any]) -> dict[str, Any]:
    out = {k: col[k] for k in COLUMN_FIELDS}
    if out["default"] is None:
        del out["default"]
    return out


# ── Positionen ───────────────────────────────────────────────────────────────


async def _position(ctx: OpContext, kind: str, table_id: str, after: str | None, *, none_is_end: bool,
                    moving: str | None = None) -> str:
    """Neue Position für eine Spalte/Zeile hinter `after` (bei `moving` ohne diesen Eintrag selbst)."""
    sql_table = {"column": "columns", "row": "rows"}[kind]
    skip = "AND id <> :moving" if moving else ""
    params: dict[str, Any] = {"t": table_id}
    if moving:
        params["moving"] = moving
    if after is None:
        agg = "max" if none_is_end else "min"
        found = (await ctx.session.execute(
            text(f"SELECT {agg}(position) FROM {sql_table} WHERE table_id = :t {skip}"), params)).scalar_one()
        return positions.between(found, None) if none_is_end else positions.between(None, found)
    ref = (await ctx.session.execute(
        text(f"SELECT position FROM {sql_table} WHERE id = :id AND table_id = :t"),
        {"id": after, "t": table_id})).scalar_one_or_none()
    if ref is None:
        label = "Spalte" if kind == "column" else "Zeile"
        raise DomainError("NOT_FOUND", f"{label} '{after}' (after) gehört nicht zu dieser Tabelle")
    nxt = (await ctx.session.execute(
        text(f"SELECT min(position) FROM {sql_table} WHERE table_id = :t AND position > :p {skip}"),
        {**params, "p": ref})).scalar_one()
    return positions.between(ref, nxt)


async def _predecessor(ctx: OpContext, kind: str, table_id: str, position: str) -> str | None:
    sql_table = {"column": "columns", "row": "rows"}[kind]
    return (await ctx.session.execute(
        text(f"""SELECT id FROM {sql_table} WHERE table_id = :t AND position < :p
                 ORDER BY position DESC LIMIT 1"""), {"t": table_id, "p": position})).scalar_one_or_none()


# ── Prüfungen gegen die Datenbank ────────────────────────────────────────────


async def _target_table(ctx: OpContext, type_: dict[str, Any]) -> dict[str, Any]:
    return await _table(ctx, type_["table"])


async def _check_references(ctx: OpContext, columns: list[dict[str, Any]], values: dict[str, Any]) -> dict[str, str]:
    """Zeigen Referenzwerte auf vorhandene Zeilen der Zieltabelle? Fehler pro Spalten-Key."""
    errors: dict[str, str] = {}
    by_id = {c["id"]: c for c in columns}
    for col_id, value in values.items():
        col = by_id.get(col_id)
        if col is None or value is None or col["type"]["kind"] != "reference":
            continue
        ok = (await ctx.session.execute(
            text("SELECT 1 FROM rows WHERE id = :id AND table_id = :t"),
            {"id": value, "t": col["type"]["table"]})).scalar_one_or_none()
        if ok is None:
            errors[col["key"]] = f"{col['name']}: Die verwiesene Zeile „{value}“ existiert nicht in der Zieltabelle"
    return errors


async def _check_unique(ctx: OpContext, table_id: str, columns: list[dict[str, Any]], values: dict[str, Any],
                        exclude_row: str = "") -> dict[str, str]:
    errors: dict[str, str] = {}
    by_id = {c["id"]: c for c in columns}
    for col_id, value in values.items():
        col = by_id.get(col_id)
        if col is None or value is None or not col["unique"]:
            continue
        other = (await ctx.session.execute(
            text("""SELECT id FROM rows WHERE table_id = :t AND id <> :ex
                    AND values -> CAST(:c AS text) = CAST(:v AS jsonb) LIMIT 1"""),
            {"t": table_id, "ex": exclude_row, "c": col_id, "v": json.dumps(value)})).scalar_one_or_none()
        if other is not None:
            errors[col["key"]] = (f"{col['name']}: Der Wert „{value}“ ist schon vergeben (Zeile {other}), "
                                  "die Spalte verlangt eindeutige Werte")
    return errors


async def _sync_links(ctx: OpContext, row_id: str, columns: list[dict[str, Any]], values: dict[str, Any]) -> None:
    """Spiegelt Referenzwerte in `row_links` (nur die Spalten in `values`, `None` entfernt den Verweis)."""
    by_id = {c["id"]: c for c in columns}
    for col_id, value in values.items():
        if by_id.get(col_id, {}).get("type", {}).get("kind") != "reference":
            continue
        if value is None:
            await ctx.session.execute(text("DELETE FROM row_links WHERE from_row = :r AND column_id = :c"),
                                      {"r": row_id, "c": col_id})
        else:
            await ctx.session.execute(
                text("""INSERT INTO row_links (from_row, column_id, to_row) VALUES (:r, :c, :to)
                        ON CONFLICT (from_row, column_id) DO UPDATE SET to_row = EXCLUDED.to_row"""),
                {"r": row_id, "c": col_id, "to": value})


def _ref_edges(col: dict[str, Any]) -> list[tuple[str, str, str]]:
    t = col["type"]
    return [("table", t["table"], "reference_column")] if t["kind"] == "reference" else []


def _normalize_default(col: dict[str, Any]) -> Any:
    """Standardwert in Spaltentyp umgewandelt; `{{ }}`-Ausdrücke bleiben als Text stehen."""
    default = col.get("default")
    if default is None:
        return None
    if isinstance(default, str) and default.strip().startswith("{{"):
        return default.strip()
    return resolve_default(default, col["type"])


async def _check_definition(ctx: OpContext, column: dict[str, Any], prefix: str, own_table: str | None = None
                            ) -> dict[str, str]:
    errors = check_column_definition(column, prefix)
    t = type_dict(column["type"])
    if t["kind"] == "reference":
        if column.get("default") is not None:
            errors[f"{prefix}default"] = "Referenzspalten können keinen Standardwert haben"
        if t["table"] != own_table:
            found = (await ctx.session.execute(
                text("SELECT 1 FROM tables WHERE id = :id AND workspace_id = :ws"),
                {"id": t["table"], "ws": ctx.workspace_id})).scalar_one_or_none()
            if found is None:
                errors[f"{prefix}type"] = f"Die Zieltabelle „{t['table']}“ der Referenz existiert nicht"
    return errors


# ── table.* ──────────────────────────────────────────────────────────────────


@op_handler("table.create")
async def table_create(ctx: OpContext, op: Any):
    errors: dict[str, str] = {}
    if msg := check_key("table", op.key):
        errors["key"] = msg
    if not op.name.strip():
        errors["name"] = "Der Tabellenname darf nicht leer sein"
    if (await ctx.session.execute(text("SELECT 1 FROM tables WHERE id = :id"), {"id": op.id})).scalar_one_or_none():
        errors["id"] = f"Die Tabellen-ID „{op.id}“ existiert bereits"
    if (await ctx.session.execute(text("SELECT 1 FROM tables WHERE workspace_id = :ws AND key = :k"),
                                  {"ws": ctx.workspace_id, "k": op.key})).scalar_one_or_none():
        errors["key"] = f"Es gibt schon eine Tabelle mit dem Key „{op.key}“"

    seen_keys: set[str] = set()
    seen_ids: set[str] = set()
    columns: list[dict[str, Any]] = []
    previous: str | None = None
    for i, col_in in enumerate(op.columns):
        col = col_in.model_dump(mode="json")
        prefix = f"columns[{i}]."
        errors.update(await _check_definition(ctx, col, prefix, own_table=op.id))
        if col["key"] in seen_keys:
            errors[f"{prefix}key"] = f"Der Spalten-Key „{col['key']}“ kommt mehrfach vor"
        if col["id"] in seen_ids:
            errors[f"{prefix}id"] = f"Die Spalten-ID „{col['id']}“ kommt mehrfach vor"
        elif (await ctx.session.execute(text("SELECT 1 FROM columns WHERE id = :id"),
                                        {"id": col["id"]})).scalar_one_or_none():
            errors[f"{prefix}id"] = f"Die Spalten-ID „{col['id']}“ existiert bereits"
        seen_keys.add(col["key"])
        seen_ids.add(col["id"])
        col["position"] = col["position"] or positions.between(previous, None)
        previous = col["position"]
        columns.append(col)
    display = None
    if op.display_column:
        display = op.display_column
        if display not in seen_ids:
            errors["display_column"] = "Die Anzeigespalte muss eine Spalte dieser Tabelle sein"
    elif columns:
        display = columns[0]["id"]
    if errors:
        raise fail(errors, f"Die Tabelle „{op.name}“")
    for col in columns:
        col["default"] = _normalize_default(col)

    await ctx.session.execute(
        text("""INSERT INTO tables (id, workspace_id, key, name, display_column)
                VALUES (:id, :ws, :key, :name, :display)"""),
        {"id": op.id, "ws": ctx.workspace_id, "key": op.key, "name": op.name, "display": display})
    for col in columns:
        await _insert_column(ctx, op.id, col)
        if edges := _ref_edges(col):
            ctx.set_references("column", col["id"], edges)
    await ctx.touch("table", op.id, f"table:{op.id}", created=True)
    ctx.add_inverse({"op": "table.delete", "table": op.id})
    return {"id": op.id}


async def _insert_column(ctx: OpContext, table_id: str, col: dict[str, Any]) -> None:
    await ctx.session.execute(
        text('''INSERT INTO columns (id, table_id, key, name, type, required, "unique", "default", position)
                VALUES (:id, :t, :key, :name, CAST(:type AS jsonb), :required, :unique,
                        CAST(:default AS jsonb), :position)'''),
        {"id": col["id"], "t": table_id, "key": col["key"], "name": col["name"], "type": json.dumps(col["type"]),
         "required": col["required"], "unique": col["unique"], "default": _dump(col.get("default")),
         "position": col["position"]})


@op_handler("table.update")
async def table_update(ctx: OpContext, op: Any):
    table = await _table(ctx, op.table)
    errors: dict[str, str] = {}
    fields = op.model_fields_set
    if "name" in fields and (op.name is None or not op.name.strip()):
        errors["name"] = "Der Tabellenname darf nicht leer sein"
    if "key" in fields and op.key is not None:
        if msg := check_key("table", op.key):
            errors["key"] = msg
        elif (await ctx.session.execute(
                text("SELECT 1 FROM tables WHERE workspace_id = :ws AND key = :k AND id <> :id"),
                {"ws": ctx.workspace_id, "k": op.key, "id": table["id"]})).scalar_one_or_none():
            errors["key"] = f"Es gibt schon eine Tabelle mit dem Key „{op.key}“"
    if "display_column" in fields and op.display_column is not None:
        if op.display_column not in {c["id"] for c in await _columns(ctx, table["id"])}:
            errors["display_column"] = "Die Anzeigespalte muss eine Spalte dieser Tabelle sein"
    if errors:
        raise fail(errors, f"Die Tabelle „{table['name']}“")
    changes = {f: getattr(op, f) for f in ("name", "key", "display_column")
               if f in fields and getattr(op, f) is not None}
    if not changes:
        return None
    await ctx.session.execute(
        text("UPDATE tables SET name = :name, key = :key, display_column = :display WHERE id = :id"),
        {"id": table["id"], "name": changes.get("name", table["name"]), "key": changes.get("key", table["key"]),
         "display": changes.get("display_column", table["display_column"])})
    await ctx.touch("table", table["id"], f"table:{table['id']}")
    ctx.add_inverse({"op": "table.update", "table": table["id"], **{k: table[k] for k in changes}})
    return None


@op_handler("table.delete")
async def table_delete(ctx: OpContext, op: Any):
    table = await _table(ctx, op.table)
    columns = await _columns(ctx, table["id"])
    own = {c["id"] for c in columns}
    usages = [u for u in await references.usages(ctx, "table", table["id"])
              if not (u["source_kind"] == "column" and u["source_id"] in own)]
    if usages:
        raise in_use_error(f"Die Tabelle „{table['name']}“", usages)

    rows = (await ctx.session.execute(
        text("SELECT id, values FROM rows WHERE table_id = :t ORDER BY position"), {"t": table["id"]})).mappings().all()
    previous = None
    inverse_rows = []
    for r in rows:
        inverse_rows.append({"id": r["id"], "values": r["values"], **({"after": previous} if previous else {})})
        previous = r["id"]
    if inverse_rows:
        ctx.add_inverse({"op": "row.insert", "table": table["id"], "rows": inverse_rows})
    ctx.add_inverse({"op": "table.create", "id": table["id"], "key": table["key"], "name": table["name"],
                     "columns": [_column_for_inverse(c) for c in columns],
                     **({"display_column": table["display_column"]} if table["display_column"] else {})})
    ids = [r["id"] for r in rows]
    await ctx.session.execute(
        text("DELETE FROM row_links WHERE from_row = ANY(CAST(:ids AS text[])) OR to_row = ANY(CAST(:ids AS text[]))"),
        {"ids": ids})
    await ctx.session.execute(text("DELETE FROM tables WHERE id = :id"), {"id": table["id"]})
    for col in columns:
        ctx.set_references("column", col["id"], [])
    await ctx.touch("table", table["id"], f"table:{table['id']}", deleted=True)
    return None


# ── column.* ─────────────────────────────────────────────────────────────────


@op_handler("column.add")
async def column_add(ctx: OpContext, op: Any):
    table = await _table(ctx, op.table)
    columns = await _columns(ctx, table["id"])
    col = op.column.model_dump(mode="json")
    errors = await _check_definition(ctx, col, "column.", own_table=table["id"])
    if any(c["key"] == col["key"] for c in columns):
        errors["column.key"] = f"Die Tabelle „{table['name']}“ hat schon eine Spalte mit dem Key „{col['key']}“"
    if (await ctx.session.execute(text("SELECT 1 FROM columns WHERE id = :id"),
                                  {"id": col["id"]})).scalar_one_or_none():
        errors["column.id"] = f"Die Spalten-ID „{col['id']}“ existiert bereits"
    count = (await ctx.session.execute(text("SELECT count(*) FROM rows WHERE table_id = :t"),
                                       {"t": table["id"]})).scalar_one()
    if not errors:
        col["default"] = _normalize_default(col)
        fill = resolve_default(col["default"], col["type"], user_id=_user_id(ctx)) if col["default"] is not None else None
        if count and col["required"] and fill is None:
            errors["column.required"] = (f"„{col['name']}“ kann kein Pflichtfeld sein: die Tabelle hat schon {count} "
                                         "Zeilen ohne Wert. Gib einen Standardwert an oder lege die Spalte "
                                         "zuerst als optional an")
        if count > 1 and col["unique"] and fill is not None:
            errors["column.unique"] = (f"„{col['name']}“ kann nicht eindeutig sein: der Standardwert würde in "
                                       f"{count} Zeilen stehen")
    if errors:
        raise fail(errors, f"Die Spalte „{col['name']}“")
    col["position"] = col["position"] or await _position(ctx, "column", table["id"], op.after, none_is_end=True)
    await _insert_column(ctx, table["id"], col)
    if fill is not None and count:
        await ctx.session.execute(
            text("""UPDATE rows SET values = values || jsonb_build_object(CAST(:c AS text), CAST(:v AS jsonb))
                    WHERE table_id = :t"""), {"c": col["id"], "v": json.dumps(fill), "t": table["id"]})
    if edges := _ref_edges(col):
        ctx.set_references("column", col["id"], edges)
    await ctx.touch("table", table["id"], f"table:{table['id']}")
    ctx.add_inverse({"op": "column.delete", "table": table["id"], "column": col["id"]})
    return {"id": col["id"]}


@op_handler("column.update")
async def column_update(ctx: OpContext, op: Any):
    table = await _table(ctx, op.table)
    columns = await _columns(ctx, table["id"])
    col = _column(columns, op.column, table)
    patch = op.patch
    given = patch.model_fields_set
    new = dict(col)
    errors: dict[str, str] = {}
    if "key" in given and patch.key is not None:
        new["key"] = patch.key
        if any(c["key"] == patch.key and c["id"] != col["id"] for c in columns):
            errors["patch.key"] = f"Die Tabelle „{table['name']}“ hat schon eine Spalte mit dem Key „{patch.key}“"
    if "name" in given and patch.name is not None:
        new["name"] = patch.name
    if "type" in given and patch.type is not None:
        new["type"] = type_dict(patch.type)
    for flag in ("required", "unique"):
        if flag in given and getattr(patch, flag) is not None:
            new[flag] = getattr(patch, flag)
    if "default" in given:
        new["default"] = patch.default
    errors.update({k: v for k, v in (await _check_definition(ctx, new, "patch.", own_table=table["id"])).items()
                   if k != "patch.key" or "patch.key" not in errors})
    if errors:
        raise fail(errors, f"Die Spalte „{col['name']}“")
    new["default"] = _normalize_default(new)

    old_type, new_type = col["type"], new["type"]
    type_changed = old_type != new_type
    rows = (await ctx.session.execute(
        text("SELECT id, values -> CAST(:c AS text) AS v FROM rows WHERE table_id = :t ORDER BY position"),
        {"c": col["id"], "t": table["id"]})).mappings().all()
    old_vals = {r["id"]: r["v"] for r in rows}
    final = dict(old_vals)
    lost: dict[str, str] = {}
    if type_changed:
        converted, lost = convert_values(old_vals, new_type)
        if new_type["kind"] == "reference":
            wanted = [v for v in converted.values() if v is not None]
            existing = set((await ctx.session.execute(
                text("SELECT id FROM rows WHERE table_id = :t AND id = ANY(CAST(:ids AS text[]))"),
                {"t": new_type["table"], "ids": wanted})).scalars())
            for row_id, value in list(converted.items()):
                if value is not None and value not in existing:
                    converted[row_id] = None
                    lost[row_id] = f"Zeile „{value}“ existiert nicht in der Zieltabelle"
        final.update(converted)

    if new["required"] and (type_changed or not col["required"]):
        empty = [r for r, v in final.items() if v is None]
        if empty:
            listed = ", ".join(f"{r} ({lost.get(r) or 'leer'})" for r in empty[:MAX_LISTED])
            more = f" und {len(empty) - MAX_LISTED} weitere" if len(empty) > MAX_LISTED else ""
            what = "Die Typänderung" if type_changed else "Die Änderung zum Pflichtfeld"
            raise DomainError(
                "VALIDATION",
                f"{what} wird abgelehnt: „{new['name']}“ ist ein Pflichtfeld, aber {len(empty)} Zeilen hätten "
                f"keinen Wert: {listed}{more}. Korrigiere diese Zeilen zuerst.",
                {"patch.type" if type_changed else "patch.required": f"{len(empty)} Zeilen ohne Wert: {listed}{more}"},
                {"rows": {r: lost.get(r) or "leer" for r in empty}})
    if new["unique"] and (type_changed or not col["unique"]):
        dup = find_duplicates(final)
        if dup:
            value, ids = next(iter(dup.items()))
            msg = f"„{new['name']}“ kann nicht eindeutig sein: der Wert „{value}“ steht in {', '.join(ids[:MAX_LISTED])}"
            raise DomainError("VALIDATION", msg, {"patch.unique": msg}, {"rows": {r: f"doppelt: {value}" for r in ids}})

    changed_cols = {k: new[k] for k in ("key", "name", "type", "required", "unique", "default") if new[k] != col[k]}
    if not changed_cols:
        return {"id": col["id"]}
    await ctx.session.execute(
        text('''UPDATE columns SET key = :key, name = :name, type = CAST(:type AS jsonb), required = :required,
                "unique" = :unique, "default" = CAST(:default AS jsonb) WHERE id = :id'''),
        {"id": col["id"], "key": new["key"], "name": new["name"], "type": json.dumps(new["type"]),
         "required": new["required"], "unique": new["unique"], "default": _dump(new["default"])})

    changed_rows = {r: v for r, v in final.items() if v != old_vals[r]}
    for row_id, value in changed_rows.items():
        if value is None:
            await ctx.session.execute(
                text("UPDATE rows SET values = values - CAST(:c AS text) WHERE id = :id"), {"c": col["id"], "id": row_id})
        else:
            await ctx.session.execute(
                text("""UPDATE rows SET values = values || jsonb_build_object(CAST(:c AS text), CAST(:v AS jsonb))
                        WHERE id = :id"""), {"c": col["id"], "v": json.dumps(value), "id": row_id})
    if type_changed and (old_type["kind"] == "reference" or new_type["kind"] == "reference"):
        await ctx.session.execute(text("DELETE FROM row_links WHERE column_id = :c"), {"c": col["id"]})
        if new_type["kind"] == "reference":
            for row_id, value in final.items():
                if value is not None:
                    await _sync_links(ctx, row_id, [new], {col["id"]: value})
        ctx.set_references("column", col["id"], _ref_edges(new))

    for row_id, value in changed_rows.items():  # Undo: erst Spalte zurück, dann die Werte
        ctx.add_inverse({"op": "row.update", "table": table["id"], "row": row_id,
                         "values": {col["id"]: old_vals[row_id]}})
    ctx.add_inverse({"op": "column.update", "table": table["id"], "column": col["id"],
                     "patch": {k: col[k] for k in changed_cols}})
    await ctx.touch("table", table["id"], f"table:{table['id']}")
    return {"id": col["id"], "converted": len(changed_rows) - len(lost), "nulled": len(lost)}


@op_handler("column.move")
async def column_move(ctx: OpContext, op: Any):
    table = await _table(ctx, op.table)
    col = _column(await _columns(ctx, table["id"]), op.column, table)
    if op.after == col["id"]:
        return None
    previous = await _predecessor(ctx, "column", table["id"], col["position"])
    position = await _position(ctx, "column", table["id"], op.after, none_is_end=False, moving=col["id"])
    await ctx.session.execute(text("UPDATE columns SET position = :p WHERE id = :id"),
                              {"p": position, "id": col["id"]})
    await ctx.touch("table", table["id"], f"table:{table['id']}")
    ctx.add_inverse({"op": "column.move", "table": table["id"], "column": col["id"], "after": previous})
    return None


@op_handler("column.delete")
async def column_delete(ctx: OpContext, op: Any):
    table = await _table(ctx, op.table)
    columns = await _columns(ctx, table["id"])
    col = _column(columns, op.column, table)
    if usages := await references.usages(ctx, "column", col["id"]):
        raise in_use_error(f"Die Spalte „{col['name']}“", usages)

    rows = (await ctx.session.execute(
        text("""SELECT id, values -> CAST(:c AS text) AS v FROM rows
                WHERE table_id = :t AND jsonb_exists(values, CAST(:c AS text))"""),
        {"c": col["id"], "t": table["id"]})).mappings().all()
    if table["display_column"] == col["id"]:
        rest = [c for c in columns if c["id"] != col["id"]]
        replacement = rest[0]["id"] if rest else None
        await ctx.session.execute(text("UPDATE tables SET display_column = :d WHERE id = :id"),
                                  {"d": replacement, "id": table["id"]})
        ctx.add_inverse({"op": "table.update", "table": table["id"], "display_column": col["id"]})
    for r in rows:
        ctx.add_inverse({"op": "row.update", "table": table["id"], "row": r["id"], "values": {col["id"]: r["v"]}})
    previous = await _predecessor(ctx, "column", table["id"], col["position"])
    ctx.add_inverse({"op": "column.add", "table": table["id"], "column": _column_for_inverse(col),
                     **({"after": previous} if previous else {})})
    await ctx.session.execute(text("UPDATE rows SET values = values - CAST(:c AS text) WHERE table_id = :t "
                                   "AND jsonb_exists(values, CAST(:c AS text))"), {"c": col["id"], "t": table["id"]})
    await ctx.session.execute(text("DELETE FROM row_links WHERE column_id = :c"), {"c": col["id"]})
    await ctx.session.execute(text("DELETE FROM columns WHERE id = :id"), {"id": col["id"]})
    ctx.set_references("column", col["id"], [])
    await ctx.touch("table", table["id"], f"table:{table['id']}")
    return None


# ── row.* ────────────────────────────────────────────────────────────────────


def _row_errors(errors: dict[str, str], index: int, total: int) -> dict[str, str]:
    return errors if total == 1 else {f"rows[{index}].{k}": v for k, v in errors.items()}


@op_handler("row.insert")
async def row_insert(ctx: OpContext, op: Any):
    table = await _table(ctx, op.table)
    columns = await _columns(ctx, table["id"])
    total = len(op.rows)
    ids: list[str] = []
    for index, new_row in enumerate(op.rows):
        subject = "Die Zeile" if total == 1 else f"Zeile {index + 1}"
        try:
            values = prepare_values(columns, new_row.values, insert=True, user_id=_user_id(ctx), subject=subject)
        except DomainError as exc:
            raise DomainError(exc.code, exc.message, _row_errors(exc.fields, index, total)) from exc
        errors = {**await _check_references(ctx, columns, values), **await _check_unique(ctx, table["id"], columns, values)}
        if (await ctx.session.execute(text("SELECT 1 FROM rows WHERE id = :id"), {"id": new_row.id})).scalar_one_or_none():
            errors["id"] = f"Die Zeilen-ID „{new_row.id}“ existiert bereits"
        if errors:
            raise fail(_row_errors(errors, index, total), subject)
        position = await _position(ctx, "row", table["id"], new_row.after, none_is_end=True)
        await ctx.session.execute(
            text("""INSERT INTO rows (id, table_id, position, values, created_by, updated_by)
                    VALUES (:id, :t, :p, CAST(:v AS jsonb), CAST(:a AS jsonb), CAST(:a AS jsonb))"""),
            {"id": new_row.id, "t": table["id"], "p": position, "v": json.dumps(values), "a": _actor_json(ctx)})
        await _sync_links(ctx, new_row.id, columns, values)
        await ctx.touch("row", new_row.id, created=True)
        ids.append(new_row.id)
    ctx.changed("table", table["id"])
    if ids:
        ctx.add_inverse({"op": "row.delete", "table": table["id"], "rows": ids})
    return {"ids": ids}


@op_handler("row.update")
async def row_update(ctx: OpContext, op: Any):
    table = await _table(ctx, op.table)
    columns = await _columns(ctx, table["id"])
    row = await _row(ctx, table, op.row)
    changes = prepare_values(columns, op.values, insert=False)
    changes = {k: v for k, v in changes.items() if v != row["values"].get(k)}  # unveränderte Zellen ignorieren
    errors = {**await _check_references(ctx, columns, changes), **await _check_unique(ctx, table["id"], columns, changes, row["id"])}
    if errors:
        raise fail(errors, "Die Zeile")
    merged = {**row["values"], **changes}
    merged = {k: v for k, v in merged.items() if v is not None}
    await ctx.session.execute(
        text("""UPDATE rows SET values = CAST(:v AS jsonb), updated_at = now(), updated_by = CAST(:a AS jsonb)
                WHERE id = :id"""), {"v": json.dumps(merged), "a": _actor_json(ctx), "id": row["id"]})
    await _sync_links(ctx, row["id"], columns, changes)
    await ctx.touch("row", row["id"])
    ctx.changed("table", table["id"])
    ctx.add_inverse({"op": "row.update", "table": table["id"], "row": row["id"],
                     "values": {k: row["values"].get(k) for k in changes}})
    return None


@op_handler("row.move")
async def row_move(ctx: OpContext, op: Any):
    table = await _table(ctx, op.table)
    row = await _row(ctx, table, op.row)
    if op.after == row["id"]:
        return None
    previous = await _predecessor(ctx, "row", table["id"], row["position"])
    position = await _position(ctx, "row", table["id"], op.after, none_is_end=False, moving=row["id"])
    await ctx.session.execute(text("UPDATE rows SET position = :p, updated_at = now(), updated_by = CAST(:a AS jsonb) "
                                   "WHERE id = :id"), {"p": position, "a": _actor_json(ctx), "id": row["id"]})
    await ctx.touch("row", row["id"])
    ctx.add_inverse({"op": "row.move", "table": table["id"], "row": row["id"], "after": previous})
    return None


async def _plan_delete(ctx: OpContext, ids: list[str]) -> tuple[RowDeletePlan, dict[str, dict[str, Any]]]:
    ref_cols = {r["id"]: dict(r) for r in (await ctx.session.execute(
        text("""SELECT c.id, c.name, c.table_id, t.name AS table_name, c.type ->> 'on_delete' AS on_delete
                FROM columns c JOIN tables t ON t.id = c.table_id
                WHERE c.type ->> 'kind' = 'reference' AND t.workspace_id = :ws"""),
        {"ws": ctx.workspace_id})).mappings()}
    gen = plan_row_delete(ids, lambda col_id: ref_cols[col_id]["on_delete"] or "restrict")
    try:
        need = next(gen)
        while True:
            links = (await ctx.session.execute(
                text("SELECT from_row, column_id, to_row FROM row_links WHERE to_row = ANY(CAST(:ids AS text[]))"),
                {"ids": list(need)})).all()
            need = gen.send([(a, b, c) for a, b, c in links])
    except StopIteration as stop:
        return stop.value, ref_cols
    raise AssertionError("unreachable")


@op_handler("row.delete")
async def row_delete(ctx: OpContext, op: Any):
    table = await _table(ctx, op.table)
    wanted = list(dict.fromkeys(op.rows))
    found = {r["id"]: r["values"] for r in (await ctx.session.execute(
        text("SELECT id, values FROM rows WHERE table_id = :t AND id = ANY(CAST(:ids AS text[]))"),
        {"t": table["id"], "ids": wanted})).mappings()}
    if missing := [r for r in wanted if r not in found]:
        raise DomainError("NOT_FOUND", f"Zeile(n) {', '.join(missing)} in Tabelle „{table['name']}“ nicht gefunden")

    plan, ref_cols = await _plan_delete(ctx, wanted)
    if plan.blocked:
        def describe(link: tuple[str, str, str]) -> str:
            col = ref_cols[link[1]]
            return f"Zeile {link[0]} (Tabelle „{col['table_name']}“, Spalte „{col['name']}“) verweist auf {link[2]}"
        raise blocked_error(plan, describe)

    info = {r["id"]: r for r in (await ctx.session.execute(
        text("""SELECT id, table_id, values FROM rows WHERE id = ANY(CAST(:ids AS text[]))
                OR id = ANY(CAST(:ids2 AS text[]))"""),
        {"ids": plan.delete, "ids2": [f for f, _ in plan.set_null]})).mappings()}
    # Undo-Reihenfolge: gelöschte Zeilen zuerst anlegen (Auswahl vor Abhängigen), dann Verweise zurücksetzen
    for from_row, col_id in plan.set_null:
        old = info[from_row]["values"].get(col_id)
        ctx.add_inverse({"op": "row.update", "table": info[from_row]["table_id"], "row": from_row,
                         "values": {col_id: old}})
    for row_id in reversed(plan.delete):
        ctx.add_inverse({"op": "row.insert", "table": info[row_id]["table_id"],
                         "rows": [{"id": row_id, "values": info[row_id]["values"]}]})

    touched_tables = {table["id"]}
    for from_row, col_id in plan.set_null:
        tid = info[from_row]["table_id"]
        await ctx.session.execute(text("UPDATE rows SET values = values - CAST(:c AS text), updated_at = now(), "
                                       "updated_by = CAST(:a AS jsonb) WHERE id = :id"),
                                  {"c": col_id, "a": _actor_json(ctx), "id": from_row})
        await ctx.session.execute(text("DELETE FROM row_links WHERE from_row = :r AND column_id = :c"),
                                  {"r": from_row, "c": col_id})
        await ctx.touch("row", from_row, f"table:{tid}")
        touched_tables.add(tid)
    await ctx.session.execute(
        text("DELETE FROM row_links WHERE from_row = ANY(CAST(:ids AS text[])) OR to_row = ANY(CAST(:ids AS text[]))"),
        {"ids": plan.delete})
    await ctx.session.execute(text("DELETE FROM rows WHERE id = ANY(CAST(:ids AS text[]))"), {"ids": plan.delete})
    for row_id in plan.delete:
        tid = info[row_id]["table_id"]
        await ctx.touch("row", row_id, f"table:{tid}", deleted=True)
        touched_tables.add(tid)
    for tid in touched_tables:
        ctx.changed("table", tid)
    return {"deleted": plan.delete}
