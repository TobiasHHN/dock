"""In-Memory-Fassung der Op-Handler für die gemeinsamen Fixtures (spec/fixtures/README.md).

`apply_ops(state, ops)` wendet einen Batch auf einen Zustand `{"tables": [...], "documents": [...]}` an, ohne
Datenbank. Der Aufrufer-Zustand bleibt unverändert, das Ergebnis ist ein neuer Zustand (Atomarität: bei einem
Fehler wird `OpError` geworfen, es entsteht nichts Halbes). Die Fachregeln kommen aus `app.domain.tables`, wie
bei den Postgres-Handlern (`ops/handlers/tables.py`); dieses Modul ersetzt nur Laden und Speichern.

Erweitern (Dokument-/Block-Ops, Task 1.4): in einem eigenen Modul `app/ops/memory_documents.py` mit
`@memory_op("block.insert")` registrieren. `apply_ops` importiert es, falls es existiert. Ops ohne
Registrierung werfen `UnsupportedOp`, die Fixture-Tests überspringen sie dann.

Zeilen- und Tabellenversionen verhalten sich wie in der Pipeline: neue Objekte starten mit 1, geänderte Objekte
steigen pro Batch genau einmal; Zeilen-Ops erhöhen die Tabellenversion nicht (nur Schemaänderungen).
"""
from __future__ import annotations

import copy
import importlib
from collections.abc import Callable
from typing import Any

from app.domain import positions
from app.domain.tables import (
    DomainError, RowDeletePlan, blocked_error, check_column_definition, check_key, convert_values,
    drive_sync, find_duplicates, in_use_error, plan_row_delete, prepare_values, resolve_default, type_dict,
    validation_error,
)

State = dict[str, Any]
COLUMN_KEYS = ("id", "key", "name", "type", "required", "unique", "default", "position")
MAX_LISTED = 5


class OpError(Exception):
    """Abgelehnter Batch. `code` wie `ErrorCode` aus `schemas/common.py`, `fields`: Pfad -> Meldung."""

    def __init__(self, code: str, message: str, fields: dict[str, str] | None = None,
                 details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or {}
        self.details = details or {}


class UnsupportedOp(NotImplementedError):
    """Die Op hat (noch) keine In-Memory-Fassung."""


MemHandler = Callable[["Mem", dict[str, Any]], None]
MEMORY_OPS: dict[str, MemHandler] = {}


def memory_op(name: str):
    def decorator(fn: MemHandler) -> MemHandler:
        MEMORY_OPS[name] = fn
        return fn
    return decorator


class Mem:
    """Arbeitskopie des Zustands samt Buchführung über angelegte/geänderte/gelöschte Objekte."""

    def __init__(self, state: State):
        self.state = state
        self.state.setdefault("tables", [])
        self.state.setdefault("documents", [])
        self.touched: set[tuple[str, str]] = set()
        self.created: set[tuple[str, str]] = set()
        self.deleted: set[tuple[str, str]] = set()

    def touch(self, kind: str, id_: str, *, created: bool = False, deleted: bool = False) -> None:
        self.touched.add((kind, id_))
        if created:
            self.created.add((kind, id_))
        if deleted:
            self.deleted.add((kind, id_))

    # ── Suchen ───────────────────────────────────────────────────────────────

    def table(self, ref: str) -> dict[str, Any]:
        for t in self.state["tables"]:
            if ref in (t["id"], t["key"]):
                return t
        raise DomainError("NOT_FOUND", f"Tabelle '{ref}' wurde nicht gefunden")

    def column(self, table: dict[str, Any], ref: str) -> dict[str, Any]:
        for c in table["columns"]:
            if ref in (c["id"], c["key"]):
                return c
        raise DomainError("NOT_FOUND", f"Spalte '{ref}' wurde nicht gefunden")

    def row(self, table: dict[str, Any], row_id: str) -> dict[str, Any]:
        for r in table["rows"]:
            if r["id"] == row_id:
                return r
        raise DomainError("NOT_FOUND", f"Zeile '{row_id}' wurde in Tabelle „{table['name']}“ nicht gefunden")

    def values_by_id(self, table: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        return {self.column(table, k)["id"]: v for k, v in values.items()}

    def all_rows(self):
        for t in self.state["tables"]:
            for r in t["rows"]:
                yield t, r

    def ref_columns(self):
        for t in self.state["tables"]:
            for c in t["columns"]:
                if c["type"]["kind"] == "reference":
                    yield t, c

    # ── Positionen ───────────────────────────────────────────────────────────

    @staticmethod
    def sorted(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(items, key=lambda i: i["position"].encode())

    def position_after(self, items: list[dict[str, Any]], after: str | None, *, none_is_end: bool,
                       moving: str | None = None) -> str:
        ordered = [i for i in self.sorted(items) if i["id"] != moving]
        if after is None:
            if not ordered:
                return positions.between(None, None)
            return positions.between(ordered[-1]["position"], None) if none_is_end \
                else positions.between(None, ordered[0]["position"])
        index = next((n for n, i in enumerate(ordered) if i["id"] == after), None)
        if index is None:
            raise DomainError("NOT_FOUND", f"'{after}' (after) gehört nicht zu dieser Tabelle")
        nxt = ordered[index + 1]["position"] if index + 1 < len(ordered) else None
        return positions.between(ordered[index]["position"], nxt)

    # ── Verwendungen (L 9) ───────────────────────────────────────────────────

    def usages(self, kind: str, target: dict[str, Any], table: dict[str, Any]) -> list[dict[str, Any]]:
        """Wer verwendet Tabelle (`kind="table"`) oder Spalte (`kind="column"`)? Liest Blöcke der Dokumente im
        Zustand und Referenzspalten anderer Tabellen. Weitere Quellen (Formular-Actions, Workflows) ergänzt 1.4."""
        names = {target["id"], target["key"], f"{table['key']}.{target['key']}"} if kind == "column" \
            else {table["id"], table["key"]}
        found: list[dict[str, Any]] = []
        for doc in self.state["documents"]:
            for block in doc.get("blocks", []):
                props = block.get("props") or {}
                on_table = props.get("table") in {table["id"], table["key"]}
                if block["type"] == "table_view" and on_table:
                    if kind == "table":
                        found.append({"source_kind": "block", "source_id": block["id"], "via": "table_view"})
                    else:
                        if names & set(props.get("columns") or []):
                            found.append({"source_kind": "block", "source_id": block["id"], "via": "table_view"})
                        if any(f.get("column") in names for f in props.get("filter") or []) or \
                                any(s.get("column") in names for s in props.get("sort") or []):
                            found.append({"source_kind": "block", "source_id": block["id"], "via": "filter"})
                if kind == "column" and block["type"] == "field" and props.get("column") in names:
                    found.append({"source_kind": "block", "source_id": block["id"], "via": "field.column"})
        if kind == "table":
            found += [{"source_kind": "column", "source_id": c["id"], "via": "reference_column"}
                      for t, c in self.ref_columns() if c["type"]["table"] == table["id"] and t["id"] != table["id"]]
        return found


# ── Einstieg ─────────────────────────────────────────────────────────────────


def apply_ops(state: State, ops: list[dict[str, Any]]) -> State:
    """Wendet `ops` atomar an und gibt den neuen Zustand zurück (der übergebene bleibt unverändert)."""
    _load_extensions()
    mem = Mem(copy.deepcopy(state))
    try:
        for op in ops:
            handler = MEMORY_OPS.get(op["op"])
            if handler is None:
                raise UnsupportedOp(f"Operation '{op['op']}' hat noch keine In-Memory-Fassung")
            handler(mem, op)
    except DomainError as exc:
        raise OpError(exc.code, exc.message, exc.fields, exc.details) from exc
    _bump_versions(mem)
    return mem.state


def _load_extensions() -> None:
    try:
        importlib.import_module("app.ops.memory_documents")
    except ModuleNotFoundError as exc:
        if exc.name != "app.ops.memory_documents":
            raise


def _bump_versions(mem: Mem) -> None:
    for kind, id_ in mem.touched:
        if (kind, id_) in mem.created or (kind, id_) in mem.deleted:
            continue
        pool = mem.state["tables"] if kind == "table" else [r for _, r in mem.all_rows()] if kind == "row" else []
        for item in pool:
            if item["id"] == id_:
                item["version"] = item.get("version", 1) + 1


# ── Hilfen ───────────────────────────────────────────────────────────────────


def _clean_column(col: dict[str, Any]) -> dict[str, Any]:
    out = {k: copy.deepcopy(col.get(k)) for k in COLUMN_KEYS}
    out["type"] = type_dict(out["type"])
    out["required"] = bool(out["required"])
    out["unique"] = bool(out["unique"])
    return out


def _normalize_default(col: dict[str, Any]) -> Any:
    default = col.get("default")
    if default is None:
        return None
    if isinstance(default, str) and default.strip().startswith("{{"):
        return default.strip()
    return resolve_default(default, col["type"])


def _check_definition(mem: Mem, col: dict[str, Any], prefix: str, own_table: str | None) -> dict[str, str]:
    errors = check_column_definition(col, prefix)
    t = type_dict(col["type"])
    if t["kind"] == "reference":
        if col.get("default") is not None:
            errors[f"{prefix}default"] = "Referenzspalten können keinen Standardwert haben"
        if t["table"] != own_table and not any(tb["id"] == t["table"] for tb in mem.state["tables"]):
            errors[f"{prefix}type"] = f"Die Zieltabelle „{t['table']}“ der Referenz existiert nicht"
    return errors


def _resolve_type(mem: Mem, type_: dict[str, Any], own_ids: dict[str, str] | None = None) -> dict[str, Any]:
    t = dict(type_)
    if t.get("kind") == "reference":
        ref = t["table"]
        t["table"] = (own_ids or {}).get(ref) or mem.table(ref)["id"]
    return t


def _check_references(mem: Mem, columns: list[dict[str, Any]], values: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    by_id = {c["id"]: c for c in columns}
    for col_id, value in values.items():
        col = by_id.get(col_id)
        if col is None or value is None or col["type"]["kind"] != "reference":
            continue
        target = next((t for t in mem.state["tables"] if t["id"] == col["type"]["table"]), None)
        if target is None or not any(r["id"] == value for r in target["rows"]):
            errors[col["key"]] = f"{col['name']}: Die verwiesene Zeile „{value}“ existiert nicht in der Zieltabelle"
    return errors


def _check_unique(table: dict[str, Any], values: dict[str, Any], exclude: str = "") -> dict[str, str]:
    errors: dict[str, str] = {}
    by_id = {c["id"]: c for c in table["columns"]}
    for col_id, value in values.items():
        col = by_id.get(col_id)
        if col is None or value is None or not col["unique"]:
            continue
        other = next((r["id"] for r in table["rows"] if r["id"] != exclude and r["values"].get(col_id) == value), None)
        if other:
            errors[col["key"]] = (f"{col['name']}: Der Wert „{value}“ ist schon vergeben (Zeile {other}), "
                                  "die Spalte verlangt eindeutige Werte")
    return errors


def _row_errors(errors: dict[str, str], index: int, total: int) -> dict[str, str]:
    return errors if total == 1 else {f"rows[{index}].{k}": v for k, v in errors.items()}


# ── table.* ──────────────────────────────────────────────────────────────────


@memory_op("table.create")
def _table_create(mem: Mem, op: dict[str, Any]) -> None:
    errors: dict[str, str] = {}
    if msg := check_key("table", op["key"]):
        errors["key"] = msg
    if not op["name"].strip():
        errors["name"] = "Der Tabellenname darf nicht leer sein"
    if any(t["id"] == op["id"] for t in mem.state["tables"]):
        errors["id"] = f"Die Tabellen-ID „{op['id']}“ existiert bereits"
    if any(t["key"] == op["key"] for t in mem.state["tables"]):
        errors["key"] = f"Es gibt schon eine Tabelle mit dem Key „{op['key']}“"
    own = {op["key"]: op["id"], op["id"]: op["id"]}
    columns: list[dict[str, Any]] = []
    previous: str | None = None
    for i, raw in enumerate(op["columns"]):
        prefix = f"columns[{i}]."
        col = _clean_column({**raw, "type": _resolve_type(mem, type_dict(raw["type"]), own)})
        errors.update(_check_definition(mem, col, prefix, op["id"]))
        if any(c["key"] == col["key"] for c in columns):
            errors[f"{prefix}key"] = f"Der Spalten-Key „{col['key']}“ kommt mehrfach vor"
        if any(c["id"] == col["id"] for c in columns):
            errors[f"{prefix}id"] = f"Die Spalten-ID „{col['id']}“ kommt mehrfach vor"
        col["position"] = col["position"] or positions.between(previous, None)
        previous = col["position"]
        columns.append(col)
    display = op.get("display_column")
    if display:
        display = next((c["id"] for c in columns if display in (c["id"], c["key"])), None)
        if display is None:
            errors["display_column"] = "Die Anzeigespalte muss eine Spalte dieser Tabelle sein"
    elif columns:
        display = columns[0]["id"]
    if errors:
        raise validation_error(errors, f"Die Tabelle „{op['name']}“")
    for col in columns:
        col["default"] = _normalize_default(col)
    mem.state["tables"].append({"id": op["id"], "key": op["key"], "name": op["name"], "display_column": display,
                                "version": 1, "columns": columns, "rows": []})
    mem.touch("table", op["id"], created=True)


@memory_op("table.update")
def _table_update(mem: Mem, op: dict[str, Any]) -> None:
    table = mem.table(op["table"])
    errors: dict[str, str] = {}
    if "name" in op and (op["name"] is None or not op["name"].strip()):
        errors["name"] = "Der Tabellenname darf nicht leer sein"
    if op.get("key") is not None:
        if msg := check_key("table", op["key"]):
            errors["key"] = msg
        elif any(t["key"] == op["key"] and t["id"] != table["id"] for t in mem.state["tables"]):
            errors["key"] = f"Es gibt schon eine Tabelle mit dem Key „{op['key']}“"
    display = None
    if op.get("display_column") is not None:
        display = next((c["id"] for c in table["columns"] if op["display_column"] in (c["id"], c["key"])), None)
        if display is None:
            errors["display_column"] = "Die Anzeigespalte muss eine Spalte dieser Tabelle sein"
    if errors:
        raise validation_error(errors, f"Die Tabelle „{table['name']}“")
    for field in ("name", "key"):
        if op.get(field) is not None:
            table[field] = op[field]
    if display:
        table["display_column"] = display
    mem.touch("table", table["id"])


@memory_op("table.delete")
def _table_delete(mem: Mem, op: dict[str, Any]) -> None:
    table = mem.table(op["table"])
    if usages := mem.usages("table", table, table):
        raise in_use_error(f"Die Tabelle „{table['name']}“", usages)
    mem.state["tables"].remove(table)
    mem.touch("table", table["id"], deleted=True)


# ── column.* ─────────────────────────────────────────────────────────────────


@memory_op("column.add")
def _column_add(mem: Mem, op: dict[str, Any]) -> None:
    table = mem.table(op["table"])
    raw = op["column"]
    col = _clean_column({**raw, "type": _resolve_type(mem, type_dict(raw["type"]), {table["key"]: table["id"]})})
    errors = _check_definition(mem, col, "column.", table["id"])
    if any(c["key"] == col["key"] for c in table["columns"]):
        errors["column.key"] = f"Die Tabelle „{table['name']}“ hat schon eine Spalte mit dem Key „{col['key']}“"
    if any(c["id"] == col["id"] for t in mem.state["tables"] for c in t["columns"]):
        errors["column.id"] = f"Die Spalten-ID „{col['id']}“ existiert bereits"
    count = len(table["rows"])
    fill = None
    if not errors:
        col["default"] = _normalize_default(col)
        fill = resolve_default(col["default"], col["type"]) if col["default"] is not None else None
        if count and col["required"] and fill is None:
            errors["column.required"] = (f"„{col['name']}“ kann kein Pflichtfeld sein: die Tabelle hat schon {count} "
                                         "Zeilen ohne Wert. Gib einen Standardwert an oder lege die Spalte "
                                         "zuerst als optional an")
        if count > 1 and col["unique"] and fill is not None:
            errors["column.unique"] = (f"„{col['name']}“ kann nicht eindeutig sein: der Standardwert würde in "
                                       f"{count} Zeilen stehen")
    if errors:
        raise validation_error(errors, f"Die Spalte „{col['name']}“")
    after = mem.column(table, op["after"])["id"] if op.get("after") else None
    col["position"] = col["position"] or mem.position_after(table["columns"], after, none_is_end=True)
    table["columns"].append(col)
    if fill is not None:
        for row in table["rows"]:
            row["values"][col["id"]] = fill
    mem.touch("table", table["id"])


@memory_op("column.update")
def _column_update(mem: Mem, op: dict[str, Any]) -> None:
    table = mem.table(op["table"])
    col = mem.column(table, op["column"])
    patch = op["patch"]
    new = copy.deepcopy(col)
    errors: dict[str, str] = {}
    if patch.get("key") is not None:
        new["key"] = patch["key"]
        if any(c["key"] == patch["key"] and c["id"] != col["id"] for c in table["columns"]):
            errors["patch.key"] = f"Die Tabelle „{table['name']}“ hat schon eine Spalte mit dem Key „{patch['key']}“"
    if patch.get("name") is not None:
        new["name"] = patch["name"]
    if patch.get("type") is not None:
        new["type"] = _resolve_type(mem, type_dict(patch["type"]), {table["key"]: table["id"]})
    for flag in ("required", "unique"):
        if patch.get(flag) is not None:
            new[flag] = patch[flag]
    if "default" in patch:
        new["default"] = patch["default"]
    for path, msg in _check_definition(mem, new, "patch.", table["id"]).items():
        errors.setdefault(path, msg)
    if errors:
        raise validation_error(errors, f"Die Spalte „{col['name']}“")
    new["default"] = _normalize_default(new)

    type_changed = col["type"] != new["type"]
    old_vals = {r["id"]: r["values"].get(col["id"]) for r in table["rows"]}
    final = dict(old_vals)
    lost: dict[str, str] = {}
    if type_changed:
        converted, lost = convert_values(old_vals, new["type"])
        if new["type"]["kind"] == "reference":
            target = next(t for t in mem.state["tables"] if t["id"] == new["type"]["table"])
            known = {r["id"] for r in target["rows"]}
            for row_id, value in list(converted.items()):
                if value is not None and value not in known:
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
    for key in ("key", "name", "type", "required", "unique", "default"):
        col[key] = new[key]
    for row in table["rows"]:
        value = final[row["id"]]
        if value is None:
            row["values"].pop(col["id"], None)
        else:
            row["values"][col["id"]] = value
    mem.touch("table", table["id"])


@memory_op("column.move")
def _column_move(mem: Mem, op: dict[str, Any]) -> None:
    table = mem.table(op["table"])
    col = mem.column(table, op["column"])
    after = mem.column(table, op["after"])["id"] if op.get("after") else None
    if after != col["id"]:
        col["position"] = mem.position_after(table["columns"], after, none_is_end=False, moving=col["id"])
    mem.touch("table", table["id"])


@memory_op("column.delete")
def _column_delete(mem: Mem, op: dict[str, Any]) -> None:
    table = mem.table(op["table"])
    col = mem.column(table, op["column"])
    if usages := mem.usages("column", col, table):
        raise in_use_error(f"Die Spalte „{col['name']}“", usages)
    table["columns"].remove(col)
    if table.get("display_column") == col["id"]:
        rest = mem.sorted(table["columns"])
        table["display_column"] = rest[0]["id"] if rest else None
    for row in table["rows"]:
        row["values"].pop(col["id"], None)
    mem.touch("table", table["id"])


# ── row.* ────────────────────────────────────────────────────────────────────


@memory_op("row.insert")
def _row_insert(mem: Mem, op: dict[str, Any]) -> None:
    table = mem.table(op["table"])
    total = len(op["rows"])
    for index, new_row in enumerate(op["rows"]):
        subject = "Die Zeile" if total == 1 else f"Zeile {index + 1}"
        try:
            values = prepare_values(table["columns"], mem.values_by_id(table, new_row["values"]), insert=True,
                                    subject=subject)
        except DomainError as exc:
            raise DomainError(exc.code, exc.message, _row_errors(exc.fields, index, total)) from exc
        errors = {**_check_references(mem, table["columns"], values), **_check_unique(table, values)}
        if any(r["id"] == new_row["id"] for _, r in mem.all_rows()):
            errors["id"] = f"Die Zeilen-ID „{new_row['id']}“ existiert bereits"
        if errors:
            raise validation_error(_row_errors(errors, index, total), subject)
        position = mem.position_after(table["rows"], new_row.get("after"), none_is_end=True)
        table["rows"].append({"id": new_row["id"], "position": position, "version": 1, "values": values})
        mem.touch("row", new_row["id"], created=True)


@memory_op("row.update")
def _row_update(mem: Mem, op: dict[str, Any]) -> None:
    table = mem.table(op["table"])
    row = mem.row(table, op["row"])
    changes = prepare_values(table["columns"], mem.values_by_id(table, op["values"]), insert=False)
    changes = {k: v for k, v in changes.items() if v != row["values"].get(k)}
    errors = {**_check_references(mem, table["columns"], changes), **_check_unique(table, changes, row["id"])}
    if errors:
        raise validation_error(errors, "Die Zeile")
    for col_id, value in changes.items():
        if value is None:
            row["values"].pop(col_id, None)
        else:
            row["values"][col_id] = value
    mem.touch("row", row["id"])


@memory_op("row.move")
def _row_move(mem: Mem, op: dict[str, Any]) -> None:
    table = mem.table(op["table"])
    row = mem.row(table, op["row"])
    after = op.get("after")
    if after != row["id"]:
        row["position"] = mem.position_after(table["rows"], after, none_is_end=False, moving=row["id"])
    mem.touch("row", row["id"])


@memory_op("row.delete")
def _row_delete(mem: Mem, op: dict[str, Any]) -> None:
    table = mem.table(op["table"])
    wanted = list(dict.fromkeys(op["rows"]))
    if missing := [r for r in wanted if not any(x["id"] == r for x in table["rows"])]:
        raise DomainError("NOT_FOUND", f"Zeile(n) {', '.join(missing)} in Tabelle „{table['name']}“ nicht gefunden")
    ref_cols = {c["id"]: (t, c) for t, c in mem.ref_columns()}

    def incoming(ids: set[str]) -> list[tuple[str, str, str]]:
        links = []
        for _, row in mem.all_rows():
            for col_id, (_, _col) in ref_cols.items():
                if row["values"].get(col_id) in ids:
                    links.append((row["id"], col_id, row["values"][col_id]))
        return links

    plan: RowDeletePlan = drive_sync(
        plan_row_delete(wanted, lambda c: ref_cols[c][1]["type"].get("on_delete", "restrict")), incoming)
    if plan.blocked:
        def describe(link: tuple[str, str, str]) -> str:
            t, c = ref_cols[link[1]]
            return f"Zeile {link[0]} (Tabelle „{t['name']}“, Spalte „{c['name']}“) verweist auf {link[2]}"
        raise blocked_error(plan, describe)
    for from_row, col_id in plan.set_null:
        row = next(r for _, r in mem.all_rows() if r["id"] == from_row)
        row["values"].pop(col_id, None)
        mem.touch("row", from_row)
    gone = set(plan.delete)
    for t in mem.state["tables"]:
        for row in [r for r in t["rows"] if r["id"] in gone]:
            t["rows"].remove(row)
            mem.touch("row", row["id"], deleted=True)
