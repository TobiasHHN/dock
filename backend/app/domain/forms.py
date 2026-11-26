"""Formulare: Button-Sichtbarkeit (L 4.3), Entwürfe (L 4.4), Absenden (L 4.6). Task 3.3 (P3), Prüfung 3.5.

Die reine Logik (Formular aus flachen Blöcken lesen, Werte prüfen) hat keine Datenbank. `load_form`,
`visible_buttons` und `submit_form` brauchen eine Sitzung. Die Ops `draft.*` und `form.submit` registrieren sich in
`ops/handlers/forms.py`. Im Run-Kontext (`run`) ist hier noch nichts verdrahtet, das kommt mit Task 4.3.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from ulid import ULID
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import expressions
from app.domain.expressions import ExpressionError
from app.domain.ids import new_id
from app.domain.tables import coerce_value
from app.ops.context import DEFAULT_WORKSPACE
from app.ops.errors import PipelineError
from app.schemas.common import Actor
from app.schemas.ops import FormSubmit

INPUT_TYPES: dict[str, dict[str, Any]] = {
    "text": {"kind": "text"}, "textarea": {"kind": "long_text"}, "integer": {"kind": "integer"},
    "number": {"kind": "number"}, "currency": {"kind": "currency"}, "date": {"kind": "date"},
    "boolean": {"kind": "boolean"}, "user": {"kind": "user"},
}


def _j(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _item_id() -> str:
    return f"li_{ULID()}"


def _blank(value: Any) -> bool:
    return value is None or value == "" or value == []


def _fail(errors: dict[str, str], subject: str = "Das Formular") -> PipelineError:
    return PipelineError("VALIDATION", f"{subject} ist ungültig: " + "; ".join(errors.values()), {"errors": errors})


# ── Formular aus Blöcken lesen (rein) ────────────────────────────────────────


def descendants(blocks: list[dict[str, Any]], root_id: str) -> list[dict[str, Any]]:
    """Alle Nachfahren eines Blocks in Dokumentreihenfolge (`blocks` flach mit `parent_id`, `position`)."""
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for b in blocks:
        by_parent.setdefault(b.get("parent_id"), []).append(b)
    out: list[dict[str, Any]] = []

    def visit(parent: str) -> None:
        for b in sorted(by_parent.get(parent, []), key=lambda x: x.get("position") or ""):
            out.append(b)
            visit(b["id"])

    visit(root_id)
    return out


def effective_buttons(props: dict[str, Any], editable_fields: int) -> list[dict[str, Any]]:
    """Regel aus L 4.3: explizite Buttons, sonst automatischer „Speichern“ (nur mit Eingabefeldern)."""
    if props.get("buttons") is not None:
        return [dict(b) for b in props["buttons"]]
    if editable_fields > 0:
        return [{"id": "save", "label": "Speichern", "style": "primary",
                 "actions": [a["key"] for a in props.get("actions") or []]}]
    return []


class Form:
    """Gelesenes Formular: Props, Buttons, Felder und Zeilenlisten mit wirksamem Typ."""

    def __init__(self, block: dict[str, Any], blocks: list[dict[str, Any]], columns: dict[str, dict[str, Any]],
                 owner: dict[str, Any] | None = None):
        self.block = block
        self.props = block["props"]
        self.owner = owner
        self.actions: dict[str, dict[str, Any]] = {a["key"]: a for a in self.props.get("actions") or []}
        self.fields: dict[str, dict[str, Any]] = {}
        self.items: dict[str, dict[str, Any]] = {}
        editable = 0
        for b in descendants(blocks, block["id"]):
            if b["type"] == "field":
                editable += 1
                self.fields.setdefault(b["props"]["key"], self._spec(b, b["props"], columns))
            elif b["type"] == "line_items":
                editable += 1
                p = b["props"]
                cols = {c["key"]: self._spec(b, c, columns) for c in p.get("columns") or []}
                self.items.setdefault(p["key"], {"key": p["key"], "label": p.get("label") or p["key"],
                                                 "min_rows": p.get("min_rows"), "columns": cols, "block": b["id"]})
        self.buttons = effective_buttons(self.props, editable)

    @staticmethod
    def _spec(block: dict[str, Any], p: dict[str, Any], columns: dict[str, dict[str, Any]]) -> dict[str, Any]:
        col = columns.get(p.get("column") or "")
        if col:
            type_, required, label = col["type"], bool(col.get("required")) or bool(p.get("required")), \
                p.get("label") or col["name"]
        else:
            input_ = p.get("input") or "text"
            if input_ == "select":
                type_ = {"kind": "select", "options": [{"id": o["id"], "label": o.get("label", o["id"])}
                                                       for o in p.get("options") or []]}
            elif input_ == "reference":
                type_ = {"kind": "reference", "table": p.get("reference_table") or "tbl_unbekannt"}
            else:
                type_ = INPUT_TYPES.get(input_, {"kind": "text"})
            required, label = bool(p.get("required")), p.get("label") or p["key"]
        return {"key": p["key"], "label": label, "type": type_, "required": required,
                "default": p.get("default"), "block": block["id"]}

    def button(self, button_id: str) -> dict[str, Any] | None:
        return next((b for b in self.buttons if b["id"] == button_id), None)

    @property
    def lookup_tables(self) -> set[str]:
        found: set[str] = set()
        for a in self.actions.values():
            for v in [a.get("for_each"), a.get("row"), *(a.get("values") or {}).values()]:
                if isinstance(v, str):
                    found |= expressions.lookup_tables(v)
        for f in self.fields.values():
            if isinstance(f["default"], str):
                found |= expressions.lookup_tables(f["default"])
        return found


def normalize_items(raw: Any) -> list[dict[str, Any]]:
    """Zeilen aus Entwurf (`{id, position, values}`) oder von Agenten (reine Wert-Objekte) -> `[{id, values}]`."""
    out = []
    for item in raw or []:
        if not isinstance(item, dict):
            raise ValueError("Zeilen müssen Objekte sein")
        if isinstance(item.get("values"), dict):
            out.append({"id": item.get("id") or _item_id(), "values": item["values"]})
        else:
            values = {k: v for k, v in item.items() if k != "id"}
            out.append({"id": item.get("id") or _item_id(), "values": values})
    return out


def prepare_values(form: Form, raw: dict[str, Any], button: dict[str, Any], context: dict[str, Any]
                   ) -> tuple[dict[str, Any], dict[str, str]]:
    """Wendet Standardwerte an, wandelt in Typen um und prüft (L 4.6 Schritt 4).
    Rückgabe: (Werte nach Feld-Key, Fehler nach Feld-Key). Zeilenlisten: Liste von `{id, <spalte>…}`."""
    errors: dict[str, str] = {}
    out: dict[str, Any] = {}
    validate = button.get("validate", button.get("validate_", True))
    for key in raw:
        if key not in form.fields and key not in form.items:
            errors[key] = f"Das Formular hat kein Feld „{key}“"
    for key, f in form.fields.items():
        value = raw.get(key)
        if _blank(value) and f["default"] is not None:
            try:
                value = expressions.evaluate(f["default"], context) if isinstance(f["default"], str) else f["default"]
            except ExpressionError as exc:
                errors[key] = f"{f['label']}: Standardwert nicht auswertbar ({exc})"
                continue
        try:
            value = coerce_value(value, f["type"])
        except ValueError as exc:
            errors[key] = f"{f['label']}: {exc}"
            continue
        if validate and f["required"] and _blank(value):
            errors[key] = f"{f['label']} ist ein Pflichtfeld und darf nicht leer sein"
        out[key] = value
    for key, li in form.items.items():
        try:
            rows = normalize_items(raw.get(key))
        except ValueError as exc:
            errors[key] = f"{li['label']}: {exc}"
            continue
        prepared = []
        for i, row in enumerate(rows):
            unknown = [k for k in row["values"] if k not in li["columns"]]
            for k in unknown:
                errors[f"{key}[{i}].{k}"] = f"{li['label']}, Zeile {i + 1}: unbekannte Spalte „{k}“"
            cells: dict[str, Any] = {"id": row["id"]}
            for ckey, col in li["columns"].items():
                try:
                    cell = coerce_value(row["values"].get(ckey), col["type"])
                except ValueError as exc:
                    errors[f"{key}[{i}].{ckey}"] = f"{li['label']}, Zeile {i + 1}, {col['label']}: {exc}"
                    continue
                if validate and col["required"] and _blank(cell):
                    errors[f"{key}[{i}].{ckey}"] = f"{li['label']}, Zeile {i + 1}: {col['label']} ist ein Pflichtfeld"
                cells[ckey] = cell
            prepared.append(cells)
        if validate and li["min_rows"] and len(prepared) < li["min_rows"]:
            errors[key] = f"{li['label']}: mindestens {li['min_rows']} Zeile(n) nötig, es sind {len(prepared)}"
        out[key] = prepared
    if validate:
        for key in button.get("require") or []:
            if key not in form.fields and key not in form.items:
                errors[key] = f"Button „{button['label']}“ verlangt das unbekannte Feld „{key}“"
            elif key not in errors and _blank(out.get(key)):
                label = (form.fields.get(key) or form.items[key])["label"]
                errors[key] = f"{label} ist für „{button['label']}“ erforderlich"
    return out, errors


# ── Laden ────────────────────────────────────────────────────────────────────


async def load_form(s: AsyncSession, form_block: str, workspace: str = DEFAULT_WORKSPACE) -> Form:
    row = (await s.execute(text("""SELECT b.id, b.doc_id, b.type, b.props, d.owner_workflow, d.owner_step
                                   FROM blocks b JOIN documents d ON d.id = b.doc_id
                                   WHERE b.id = :id AND d.workspace_id = :ws"""),
                           {"id": form_block, "ws": workspace})).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Block '{form_block}' wurde nicht gefunden")
    if row["type"] != "form":
        raise PipelineError("VALIDATION", f"Block '{form_block}' ist kein Formular",
                            {"errors": {"form_block": f"Block '{form_block}' ist kein Formular"}})
    blocks = [{**dict(b), "props": _j(b["props"])} for b in (await s.execute(
        text("SELECT id, parent_id, position, type, props FROM blocks WHERE doc_id = :d"),
        {"d": row["doc_id"]})).mappings()]
    block = next(b for b in blocks if b["id"] == form_block)
    col_ids = {p["column"] for b in blocks if b["type"] in ("field", "line_items")
               for p in ([b["props"]] if b["type"] == "field" else b["props"].get("columns") or []) if p.get("column")}
    columns: dict[str, dict[str, Any]] = {}
    if col_ids:
        columns = {c["id"]: {**dict(c), "type": _j(c["type"])} for c in (await s.execute(
            text("SELECT id, key, name, type, required FROM columns WHERE id = ANY(CAST(:ids AS text[]))"),
            {"ids": sorted(col_ids)})).mappings()}
    owner = {"workflow": row["owner_workflow"], "step": row["owner_step"]} if row["owner_workflow"] else None
    return Form(block, blocks, columns, owner)


# ── Sichtbarkeit (L 4.3) ─────────────────────────────────────────────────────


def buttons_allowed(form: Form, run: str | None) -> list[dict[str, Any]]:
    """Buttons, die der Akteur sehen darf. Recht `submit`: in der Demo hat jeder angemeldete Akteur es (Rechte-
    Modell ist nicht im Scope). Ein Schritt-Dokument eines Workflows ist nur im Run absendbar, und die Run-Regeln
    (aktiver Schritt, `can_act`, kein wartender Sub-Run) kommen mit Task 4.3."""
    if run is not None or form.owner is not None:
        return []
    return form.buttons


async def visible_buttons(form_block: str, user: Actor, run: str | None = None, *,
                          session: AsyncSession | None = None) -> list[dict[str, Any]]:
    """Regel aus L 4.3: explizite Buttons oder automatischer „Speichern“, Recht `submit`, im Run: aktiver Schritt,
    `can_act` und kein wartender Sub-Run (Run-Teil: Task 4.3). Ohne `session` wird eine eigene geöffnet."""
    if session is not None:
        return buttons_allowed(await load_form(session, form_block), run)
    from app.db.session import SessionLocal

    async with SessionLocal() as own:
        return buttons_allowed(await load_form(own, form_block), run)


# ── Absenden (L 4.6) ─────────────────────────────────────────────────────────


async def _lookup_data(ctx: Any, keys: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Zeilen der für `lookup()` genannten Tabellen: Tabellen-Key -> Zeilen mit Spalten-Keys (plus `id`)."""
    data: dict[str, list[dict[str, Any]]] = {}
    for key in sorted(keys):
        table = (await ctx.session.execute(
            text("SELECT id FROM tables WHERE workspace_id = :ws AND key = :k"),
            {"ws": ctx.workspace_id, "k": key})).scalar_one_or_none()
        if table is None:
            continue  # die Auswertung meldet „Tabelle … ist unbekannt“
        cols = {c["id"]: c["key"] for c in (await ctx.session.execute(
            text("SELECT id, key FROM columns WHERE table_id = :t"), {"t": table})).mappings()}
        data[key] = [{"id": r["id"], **{cols[c]: v for c, v in _j(r["values"]).items() if c in cols}}
                     for r in (await ctx.session.execute(
                         text('SELECT id, "values" FROM rows WHERE table_id = :t ORDER BY position'),
                         {"t": table})).mappings()]
    return data


async def _user_context(ctx: Any) -> dict[str, Any]:
    member = ctx.actor.on_behalf_of or ctx.actor.id
    name = (await ctx.session.execute(text("SELECT name FROM users WHERE id = :id"), {"id": member})).scalar_one_or_none()
    return {"id": member, "name": name or ctx.actor.name or member}


def _action_error(key: str, exc: PipelineError) -> PipelineError:
    details = dict(exc.error.details or {})
    errors = {f"actions.{key}.{k}": v for k, v in (details.get("errors") or {}).items()}
    message = f"Aktion „{key}“: {exc.error.message}"
    details["errors"] = errors or {f"actions.{key}": exc.error.message}
    return PipelineError(exc.error.code, message, details)


def _eval(value: Any, context: dict[str, Any], path: str) -> Any:
    try:
        return expressions.evaluate_deep(value, context)
    except ExpressionError as exc:
        raise PipelineError("VALIDATION", f"{path}: {exc}", {"errors": {path: str(exc)}}) from exc


async def submit_form(ctx: Any, op: FormSubmit) -> dict[str, Any]:
    """Handler für `form.submit` (L 4.6): Sichtbarkeit prüfen, Werte aus Entwurf/`values`, Felder prüfen,
    Actions in einer Transaktion (erzeugt weitere Ops im selben Batch), Submission speichern (Doppelabsendung
    erkennen), im Run `workflows.complete_task` aufrufen. Rückgabe: `{results, errors?, run?}`.
    Fehler (Rechte, Eingaben, Actions) sind `PipelineError`: der Batch wird zurückgerollt, nichts ist gespeichert.
    Eine bekannte `submission_id` liefert das erste Ergebnis (`duplicate: true`) und führt nichts erneut aus."""
    from app.ops.handlers import HANDLERS, load_handlers
    from app.schemas.ops import RowDelete, RowInsert, RowUpdate
    from app.schemas.tables import NewRow

    load_handlers()
    s = ctx.session
    member = ctx.actor.on_behalf_of or ctx.actor.id
    await s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                    {"k": f"submission:{op.submission_id}"})
    prev = (await s.execute(text("SELECT form_block, actor, results FROM form_submissions WHERE id = :id"),
                            {"id": op.submission_id})).mappings().first()
    if prev is not None:
        who = (_j(prev["actor"]) or {}).get("id")
        if prev["form_block"] != op.form_block or who != ctx.actor.id:
            raise PipelineError("VALIDATION", f"submission_id '{op.submission_id}' ist schon vergeben",
                                {"errors": {"submission_id": "bereits für eine andere Absendung verwendet"}})
        return {"results": _j(prev["results"]), "duplicate": True}

    if op.run is not None:
        raise PipelineError("VALIDATION", "Absenden im Run-Kontext ist noch nicht verfügbar (Task 4.3)",
                            {"errors": {"run": "noch nicht verfügbar"}})
    form = await load_form(s, op.form_block, ctx.workspace_id)
    allowed = buttons_allowed(form, None)
    if not allowed:
        raise PipelineError("FORBIDDEN", "Dieses Formular kann hier nicht abgesendet werden "
                            "(keine Buttons oder ein Schritt-Dokument außerhalb eines Runs)", {"form_block": op.form_block})
    button = next((b for b in allowed if b["id"] == op.button), None)
    if button is None:
        raise PipelineError("VALIDATION", f"Das Formular hat keinen Button „{op.button}“",
                            {"errors": {"button": f"unbekannter Button „{op.button}“"}})
    unknown = [k for k in button.get("actions") or [] if k not in form.actions]
    if unknown:
        raise PipelineError("VALIDATION", f"Button „{button['id']}“ nennt unbekannte Actions: {', '.join(unknown)}",
                            {"errors": {"button": f"unbekannte Actions: {', '.join(unknown)}"}})
    actions = [form.actions[k] for k in button.get("actions") or []]

    # Kanäle der betroffenen Tabellen und des Entwurfs sortiert sperren (T 2.5)
    scope = f"user:{member}"
    reset = form.props.get("reset_after_submit")
    reset = True if reset is None else reset
    channels = {f"table:{a['table']}" for a in actions} | ({scope} if reset else set())
    for channel in sorted(channels):
        await ctx.lock_channel(channel)

    user = await _user_context(ctx)
    base_ctx: dict[str, Any] = {"user": user, "run": None, "results": {}, "fields": {},
                                "tables": await _lookup_data(ctx, form.lookup_tables)}
    if op.values is not None:
        raw = dict(op.values)
    else:
        found = (await s.execute(text('SELECT "values" FROM form_drafts WHERE form_block = :b AND scope = :s'),
                                 {"b": op.form_block, "s": scope})).scalar_one_or_none()
        raw = (_j(found) or {}) if found is not None else {}
    values, errors = prepare_values(form, raw, button, base_ctx)
    if errors:
        raise _fail(errors)
    base_ctx["fields"] = values

    results: dict[str, Any] = {}
    base_ctx["results"] = results
    for action in actions:
        key = action["key"]
        try:
            results[key] = await _run_action(ctx, HANDLERS, action, base_ctx, RowInsert, RowUpdate, RowDelete, NewRow)
        except PipelineError as exc:
            raise _action_error(key, exc) from exc

    await s.execute(
        text("""INSERT INTO form_submissions (id, form_block, run_id, button, "values", results, actor)
                VALUES (:id, :b, NULL, :button, CAST(:v AS jsonb), CAST(:r AS jsonb), CAST(:a AS jsonb))"""),
        {"id": op.submission_id, "b": op.form_block, "button": button["id"], "v": json.dumps(values),
         "r": json.dumps(results), "a": json.dumps(ctx.actor.model_dump(mode="json", exclude_none=True))})
    if reset:
        await s.execute(text("DELETE FROM form_drafts WHERE form_block = :b AND scope = :s"),
                        {"b": op.form_block, "s": scope})
    return {"results": results}


async def _run_action(ctx: Any, handlers: dict[str, Any], action: dict[str, Any], context: dict[str, Any],
                      RowInsert: Any, RowUpdate: Any, RowDelete: Any, NewRow: Any) -> dict[str, Any]:
    key, table = action["key"], action["table"]
    where = f"actions.{key}"
    kind = action["type"]

    def cell_values(ctx_: dict[str, Any], drop_none: bool) -> dict[str, Any]:
        evaluated = {col: _eval(v, ctx_, f"{where}.values.{col}") for col, v in (action.get("values") or {}).items()}
        return {c: v for c, v in evaluated.items() if v is not None} if drop_none else evaluated

    if kind == "create_row":
        row_id = new_id("row")
        await handlers["row.insert"](ctx, RowInsert(op="row.insert", table=table,
                                                    rows=[NewRow(id=row_id, values=cell_values(context, True))]))
        return {"id": row_id}
    if kind == "create_rows":
        items = _eval(action["for_each"], context, f"{where}.for_each")
        if items is None:
            items = []
        if not isinstance(items, list):
            raise PipelineError("VALIDATION", "for_each muss eine Liste ergeben",
                                {"errors": {f"{where}.for_each": "ergibt keine Liste"}})
        rows = [NewRow(id=new_id("row"), values=cell_values({**context, "item": item}, True)) for item in items]
        if rows:
            await handlers["row.insert"](ctx, RowInsert(op="row.insert", table=table, rows=rows))
        return {"ids": [r.id for r in rows]}
    row_id = _eval(action["row"], context, f"{where}.row")
    if not isinstance(row_id, str) or not row_id:
        raise PipelineError("VALIDATION", "row ergibt keine Zeilen-ID", {"errors": {f"{where}.row": "keine Zeilen-ID"}})
    if kind == "update_row":
        await handlers["row.update"](ctx, RowUpdate(op="row.update", table=table, row=row_id,
                                                    values=cell_values(context, False)))
    else:
        await handlers["row.delete"](ctx, RowDelete(op="row.delete", table=table, rows=[row_id]))
    return {"id": row_id}


def validate_form(blocks: list[dict[str, Any]], form_block: str) -> list[dict[str, Any]]:
    """Warnungen für Formulare (L 5.7 Daten, Task 3.5): Tippfehler in Ausdrücken, nicht befüllte Pflichtspalten,
    unbekannte Spalten. Eintrag: `{block, field, message}`."""
    ...
