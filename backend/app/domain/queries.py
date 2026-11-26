"""Lesende Abfragen für REST und Snapshots (Task 1.4): Dokumente, Markdown-Ansicht, Tabellen, gefilterte Zeilen.

Alle Funktionen bekommen eine offene `AsyncSession` und liefern JSON-fähige Dicts nach den Schemas
(`DocumentOut`, `Table`, `RowsPage`). Nicht gefunden -> `PipelineError("NOT_FOUND")`.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import expressions
from app.domain import markdown as M
from app.ops.context import DEFAULT_WORKSPACE
from app.ops.errors import PipelineError

_JSON = {"props", "values", "type", "default", "created_by", "updated_by"}
NUMERIC = {"integer", "number", "currency"}
MAX_LIMIT = 1000


def _row(mapping: Any) -> dict[str, Any]:
    out = dict(mapping)
    for key in _JSON & out.keys():
        # `type` ist bei Blöcken Text, bei Spalten jsonb. `default` kommt vom Treiber schon dekodiert und darf ein
        # String sein ("eingereicht", "{{user.id}}"), also nicht noch einmal parsen.
        if key == "default":
            continue
        if isinstance(out[key], str) and (key != "type" or out[key].startswith("{")):
            out[key] = json.loads(out[key])
    return out


async def _all(s: AsyncSession, sql: str, **params: Any) -> list[dict[str, Any]]:
    return [_row(r) for r in (await s.execute(text(sql), params)).mappings().all()]


# ── Dokumente ────────────────────────────────────────────────────────────────


def _document(row: dict[str, Any]) -> dict[str, Any]:
    owner = {"workflow": row["owner_workflow"], "step": row["owner_step"]} if row.get("owner_workflow") else None
    return {"id": row["id"], "title": row["title"], "owner": owner, "version": row["version"],
            "updated_at": row["updated_at"]}


async def list_documents(s: AsyncSession) -> list[dict[str, Any]]:
    rows = await _all(s, """SELECT id, title, owner_workflow, owner_step, version, updated_at FROM documents
                            WHERE workspace_id = :ws ORDER BY title, id""", ws=DEFAULT_WORKSPACE)
    return [{k: v for k, v in _document(r).items() if k != "version"} for r in rows]


def _preorder(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for b in blocks:
        by_parent.setdefault(b["parent_id"], []).append(b)
    out: list[dict[str, Any]] = []

    def visit(parent: str | None) -> None:
        for b in sorted(by_parent.get(parent, []), key=lambda x: x["position"]):
            out.append(b)
            visit(b["id"])

    visit(None)
    return out


async def fetch_document(s: AsyncSession, doc_id: str) -> dict[str, Any]:
    """`{"document": …, "blocks": […]}`, Blöcke flach in Dokumentreihenfolge (Eltern vor Kindern)."""
    docs = await _all(s, """SELECT id, title, owner_workflow, owner_step, version, updated_at FROM documents
                            WHERE id = :id AND workspace_id = :ws""", id=doc_id, ws=DEFAULT_WORKSPACE)
    if not docs:
        raise PipelineError("NOT_FOUND", f"Dokument '{doc_id}' wurde nicht gefunden")
    blocks = await _all(s, """SELECT id, doc_id, parent_id, position, type, props, version FROM blocks
                              WHERE doc_id = :id""", id=doc_id)
    return {"document": _document(docs[0]), "blocks": _preorder(blocks)}


async def _key_maps(s: AsyncSession) -> tuple[dict[str, str], dict[str, tuple[str, str]], dict[str, str]]:
    tables = {r["id"]: r["key"] for r in await _all(
        s, "SELECT id, key FROM tables WHERE workspace_id = :ws", ws=DEFAULT_WORKSPACE)}
    columns = {r["id"]: (r["table_id"], r["key"]) for r in await _all(
        s, "SELECT c.id, c.table_id, c.key FROM columns c JOIN tables t ON t.id = c.table_id "
           "WHERE t.workspace_id = :ws", ws=DEFAULT_WORKSPACE)}
    workflows = {r["id"]: r["key"] for r in await _all(
        s, "SELECT id, key FROM workflows WHERE workspace_id = :ws", ws=DEFAULT_WORKSPACE)}
    return tables, columns, workflows


def humanize_props(block_type: str, props: dict[str, Any], tables: dict[str, str],
                   columns: dict[str, tuple[str, str]], workflows: dict[str, str]) -> dict[str, Any]:
    """IDs in Props durch lesbare Keys ersetzen (Gegenstück zu `resolve_props` im Handler). Unbekannte bleiben."""
    out = json.loads(json.dumps(props))

    def table(ref: str) -> str:
        return tables.get(ref, ref)

    def column(ref: str) -> str:
        return columns[ref][1] if ref in columns else ref

    def qualified(ref: str) -> str:
        if ref in columns:
            table_id, key = columns[ref]
            return f"{tables.get(table_id, table_id)}.{key}"
        return ref

    if block_type == "table_view":
        out["table"] = table(out["table"])
        out["columns"] = [column(c) for c in out["columns"]] if out.get("columns") else out.get("columns")
        for item in (out.get("filter") or []) + (out.get("sort") or []):
            item["column"] = column(item["column"])
    elif block_type == "field":
        if out.get("column"):
            out["column"] = qualified(out["column"])
        if out.get("reference_table"):
            out["reference_table"] = table(out["reference_table"])
    elif block_type == "line_items":
        for col in out.get("columns") or []:
            if col.get("column"):
                col["column"] = qualified(col["column"])
    elif block_type == "form":
        for action in out.get("actions") or []:
            action["values"] = {column(k): v for k, v in (action.get("values") or {}).items()}
            action["table"] = table(action["table"])
    elif block_type == "workflow":
        out["workflow"] = workflows.get(out["workflow"], out["workflow"])
    return out


async def fetch_document_markdown(s: AsyncSession, doc_id: str) -> dict[str, Any]:
    """`{"document": …, "markdown": …}` mit Block-IDs und lesbaren Tabellen-/Spalten-Keys (L 8.2)."""
    found = await fetch_document(s, doc_id)
    maps = await _key_maps(s)
    blocks = [{**b, "props": humanize_props(b["type"], b["props"], *maps)} for b in found["blocks"]]
    return {"document": found["document"], "markdown": M.blocks_to_markdown(blocks)}


# ── Tabellen ─────────────────────────────────────────────────────────────────


async def _find_table(s: AsyncSession, ref: str) -> dict[str, Any]:
    rows = await _all(s, """SELECT id, key, name, display_column, version FROM tables
                            WHERE workspace_id = :ws AND (id = :ref OR key = :ref)""", ws=DEFAULT_WORKSPACE, ref=ref)
    if not rows:
        raise PipelineError("NOT_FOUND", f"Tabelle '{ref}' wurde nicht gefunden")
    return rows[0]


async def fetch_table(s: AsyncSession, ref: str) -> dict[str, Any]:
    """Tabellenschema mit Spalten (nach `position`); `ref` ist ID oder Key."""
    table = await _find_table(s, ref)
    table["columns"] = await _all(
        s, 'SELECT id, key, name, type, required, "unique", "default", position FROM columns '
           "WHERE table_id = :id ORDER BY position", id=table["id"])
    return table


async def list_tables(s: AsyncSession) -> list[dict[str, Any]]:
    out = []
    for t in await _all(s, "SELECT id FROM tables WHERE workspace_id = :ws ORDER BY name, id", ws=DEFAULT_WORKSPACE):
        full = await fetch_table(s, t["id"])
        out.append({k: full[k] for k in ("id", "key", "name", "columns", "version")})
    return out


def _col_expr(column: dict[str, Any], name: str) -> tuple[str, str]:
    """(SQL-Ausdruck, Typ-Kategorie) für den Wert einer Spalte; `name` ist der Parametername der Spalten-ID."""
    raw = f'r."values" -> CAST(:{name} AS text)'
    kind = column["type"]["kind"]
    if kind in NUMERIC:
        return f"CASE WHEN jsonb_typeof({raw}) = 'number' THEN ({raw} #>> '{{}}')::numeric END", "num"
    if kind == "boolean":
        return f"CASE WHEN jsonb_typeof({raw}) = 'boolean' THEN ({raw} #>> '{{}}')::boolean END", "bool"
    return f"({raw} #>> '{{}}')", "text"


def _convert(value: Any, category: str, field: str, context: dict[str, Any] | None = None) -> Any:
    if isinstance(value, str) and "{{" in value:
        try:
            value = expressions.evaluate(value, context or {})
        except expressions.ExpressionError as exc:
            raise PipelineError("VALIDATION", f"Filter '{field}': {exc}",
                                {"errors": {f"filter.{field}": str(exc)}}) from exc
    try:
        if category == "num":
            return float(str(value).replace(",", ".")) if not isinstance(value, (int, float)) else value
        if category == "bool":
            if isinstance(value, str):
                return value.strip().lower() in {"true", "1", "ja"}
            return bool(value)
    except ValueError as exc:
        raise PipelineError("VALIDATION", f"Filter '{field}': '{value}' ist kein gültiger Wert",
                            {"errors": {f"filter.{field}": "ungültiger Wert"}}) from exc
    return str(value)


def _like(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


async def query_rows(s: AsyncSession, ref: str, filters: list[dict[str, Any]], sorts: list[dict[str, Any]],
                     limit: int = 100, offset: int = 0,
                     context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Zeilen einer Tabelle mit einfachen Feldfiltern (Spaltentyp-gerecht) und Sortierung; `{table, rows, total}`.
    Filter: `column` (ID oder Key), `op` (eq, ne, gt, gte, lt, lte, contains, in, is_null), `value`.
    Ausdrücke `{{ }}` in Filterwerten werden mit `context` (z. B. user, run, now, today) ausgewertet; ein Fehler
    darin ist `VALIDATION` (422)."""
    table = await fetch_table(s, ref)
    by_ref = {c["id"]: c for c in table["columns"]} | {c["key"]: c for c in table["columns"]}
    params: dict[str, Any] = {"t": table["id"]}
    where = ["r.table_id = :t"]

    def column(name: str, path: str) -> dict[str, Any]:
        if name not in by_ref:
            raise PipelineError("VALIDATION", f"{path}: Spalte '{name}' gehört nicht zur Tabelle '{table['key']}'",
                                {"errors": {path: f"unbekannte Spalte '{name}'"}})
        return by_ref[name]

    for i, cond in enumerate(filters):
        col = column(cond["column"], f"filter[{i}].column")
        params[f"c{i}"] = col["id"]
        expr, cat = _col_expr(col, f"c{i}")
        op, value = cond.get("op", "eq"), cond.get("value")
        if op == "is_null":
            wants_null = value is None or value is True or str(value).lower() in {"true", "1"}
            where.append(f"({expr} IS NULL)" if wants_null else f"({expr} IS NOT NULL)")
        elif op == "in":
            values = [_convert(v, cat, cond["column"], context) for v in (value if isinstance(value, list) else [value])]
            params[f"v{i}"] = values
            cast = {"num": "numeric[]", "bool": "boolean[]", "text": "text[]"}[cat]
            where.append(f"{expr} = ANY(CAST(:v{i} AS {cast}))")
        elif op == "contains":
            params[f"v{i}"] = _like(str(_convert(value, "text", cond["column"], context)))
            where.append(f"(({expr})::text ILIKE :v{i} ESCAPE '\\')")
        else:
            sql_op = {"eq": "=", "ne": "IS DISTINCT FROM", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
            params[f"v{i}"] = _convert(value, cat, cond["column"], context)
            cast = {"num": "numeric", "bool": "boolean", "text": "text"}[cat]
            where.append(f"{expr} {sql_op} CAST(:v{i} AS {cast})")

    order = []
    for i, spec in enumerate(sorts):
        col = column(spec["column"], f"sort[{i}].column")
        params[f"s{i}"] = col["id"]
        expr, _ = _col_expr(col, f"s{i}")
        order.append(f"{expr} {'DESC' if spec.get('dir') == 'desc' else 'ASC'} NULLS LAST")
    order += ["r.position", "r.id"]

    clause = " AND ".join(where)
    total = (await s.execute(text(f"SELECT count(*) FROM rows r WHERE {clause}"), params)).scalar_one()
    params["limit"] = max(1, min(limit, MAX_LIMIT))
    params["offset"] = max(0, offset)
    rows = await _all(
        s, f'SELECT r.id, r.table_id, r.position, r."values", r.version, r.created_at, r.created_by, r.updated_at, '
           f"r.updated_by FROM rows r WHERE {clause} ORDER BY {', '.join(order)} LIMIT :limit OFFSET :offset",
        **params)
    return {"table": table["id"], "rows": rows, "total": int(total)}


async def fetch_table_snapshot(s: AsyncSession, table_id: str) -> dict[str, Any]:
    """`{"table": …mit Spalten, "rows": alle Zeilen}` für den Kanal `table:<id>`."""
    table = await fetch_table(s, table_id)
    rows = await _all(
        s, 'SELECT id, table_id, position, "values", version, created_at, created_by, updated_at, updated_by '
           "FROM rows WHERE table_id = :id ORDER BY position, id", id=table["id"])
    return {"table": table, "rows": rows}


__all__ = ["list_documents", "fetch_document", "fetch_document_markdown", "fetch_table", "list_tables",
           "query_rows", "fetch_table_snapshot", "humanize_props"]


# ── Workflows (Task 4.1) ─────────────────────────────────────────────────────


def _workflow(row: dict[str, Any]) -> dict[str, Any]:
    draft = row["draft"]
    return {"id": row["id"], "key": row["key"], "name": row["name"],
            "draft": json.loads(draft) if isinstance(draft, str) else draft,
            "latest_version": row["latest_version"]}


async def list_workflows(s: AsyncSession) -> list[dict[str, Any]]:
    return await _all(s, """SELECT id, key, name, latest_version FROM workflows
                            WHERE workspace_id = :ws ORDER BY name, id""", ws=DEFAULT_WORKSPACE)


async def fetch_workflow(s: AsyncSession, ref: str) -> dict[str, Any]:
    """Workflow per ID oder Key, mit Entwurf (`Workflow`)."""
    rows = await _all(s, """SELECT id, key, name, draft, latest_version FROM workflows
                            WHERE workspace_id = :ws AND (id = :ref OR key = :ref)""", ws=DEFAULT_WORKSPACE, ref=ref)
    if not rows:
        raise PipelineError("NOT_FOUND", f"Workflow '{ref}' wurde nicht gefunden")
    return _workflow(rows[0])


async def validate_workflow(s: AsyncSession, actor: Any, workflow: str | None,
                            definition: dict[str, Any] | None) -> dict[str, Any]:
    """`POST /api/workflows/validate`: Entwurf eines bestehenden Workflows oder eine freie Definition prüfen (L 5.7).
    Eine Definition, die schon am Schema scheitert, liefert `ok = false` mit Code `SCHEMA` pro Feld."""
    from pydantic import ValidationError

    from app.domain import workflows as W
    from app.ops.context import OpContext
    from app.ops.handlers.workflows import resolve_definition
    from app.schemas.workflows import WorkflowDefinition

    ctx = OpContext(session=s, actor=actor)
    workflow_id = None
    if workflow is not None:
        found = await fetch_workflow(s, workflow)
        workflow_id, definition = found["id"], found["draft"]
    try:
        parsed = WorkflowDefinition.model_validate(definition)
    except ValidationError as exc:
        return {"ok": False, "issues": [
            {"severity": "error", "code": "SCHEMA", "field": ".".join(map(str, e["loc"])),
             "message": f"{'.'.join(map(str, e['loc']))}: {e['msg']}"} for e in exc.errors()]}
    parsed = await resolve_definition(ctx, parsed)
    return (await W.check_workflow(ctx, parsed, workflow_id)).model_dump(exclude_none=True)
