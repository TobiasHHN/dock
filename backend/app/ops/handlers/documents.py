"""Handler für `doc.*` und `block.*` (L 3, L 6.1; ohne `text.edit`). Task 1.4.

Regeln:
- Blöcke liegen flach in `blocks` (parent_id + position als Fractional Index). `after` nennt den Geschwisterblock,
  hinter den eingefügt wird. Fehlt `after`, wird ANS ENDE angehängt; `"^"` fügt an den ANFANG ein.
- Props werden gegen den API-Vertrag validiert und vollständig (mit Standardwerten) gespeichert. Keys in Props
  (table_view, Felder, Actions, workflow-Block) werden zu IDs aufgelöst, damit Umbenennen nichts bricht.
- Jeder Block meldet seine Verweise (L 9) mit `ctx.set_references("block", id, …)`.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text

from app.domain import documents as D
from app.domain import markdown as M
from app.domain import positions, references
from app.ops.context import OpContext
from app.ops.errors import PipelineError
from app.ops.handlers import register
from app.realtime import presence
from app.schemas.ops import BlockDelete, BlockInsert, BlockMove, BlockUpdate, DocCreate, DocDelete, DocUpdate


def _j(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _invalid(path: str, message: str) -> PipelineError:
    return PipelineError("VALIDATION", f"{path}: {message}" if path else message,
                         {"errors": {path or "op": message}})


def _from_pydantic(exc: ValidationError, prefix: str) -> PipelineError:
    errors = {".".join([prefix, *map(str, e["loc"])]): e["msg"] for e in exc.errors()}
    path, message = next(iter(errors.items()))
    return PipelineError("VALIDATION", f"{path}: {message}", {"errors": errors})


# ── Laden ────────────────────────────────────────────────────────────────────


async def _load_doc(ctx: OpContext, doc_id: str) -> dict[str, Any]:
    row = (await ctx.session.execute(
        text("SELECT id, title, owner_workflow, owner_step FROM documents WHERE id = :id AND workspace_id = :ws"),
        {"id": doc_id, "ws": ctx.workspace_id})).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Dokument '{doc_id}' wurde nicht gefunden")
    return dict(row)


async def _load_block(ctx: OpContext, block_id: str) -> dict[str, Any]:
    row = (await ctx.session.execute(
        text("""SELECT b.id, b.doc_id, b.parent_id, b.position, b.type, b.props, b.version
                FROM blocks b JOIN documents d ON d.id = b.doc_id
                WHERE b.id = :id AND d.workspace_id = :ws"""),
        {"id": block_id, "ws": ctx.workspace_id})).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Block '{block_id}' wurde nicht gefunden")
    found = dict(row)
    found["props"] = _j(found["props"])
    return found


async def _subtree(ctx: OpContext, block_id: str) -> list[dict[str, Any]]:
    rows = await ctx.session.execute(text("""
        WITH RECURSIVE sub AS (
          SELECT id, doc_id, parent_id, position, type, props FROM blocks WHERE id = :id
          UNION ALL
          SELECT b.id, b.doc_id, b.parent_id, b.position, b.type, b.props
          FROM blocks b JOIN sub s ON b.parent_id = s.id)
        SELECT * FROM sub"""), {"id": block_id})
    return [{**dict(r), "props": _j(r["props"])} for r in rows.mappings()]


async def _siblings(ctx: OpContext, doc_id: str, parent_id: str | None,
                    exclude: str | None = None) -> list[dict[str, Any]]:
    rows = await ctx.session.execute(
        text("""SELECT id, position FROM blocks
                WHERE doc_id = :doc AND parent_id IS NOT DISTINCT FROM CAST(:parent AS text)
                ORDER BY position"""), {"doc": doc_id, "parent": parent_id})
    return [dict(r) for r in rows.mappings() if r["id"] != exclude]


def _keys(n: int) -> list[str]:
    """n aufsteigende Positionen für neue Geschwister."""
    keys: list[str] = []
    for _ in range(n):
        keys.append(positions.between(keys[-1] if keys else None, None))
    return keys


def _position(siblings: list[dict[str, Any]], after: str | None, path: str = "after") -> str:
    ids = [s["id"] for s in siblings]
    if after is None:
        return positions.between(siblings[-1]["position"] if siblings else None, None)
    if after == "^":
        return positions.between(None, siblings[0]["position"] if siblings else None)
    if after not in ids:
        raise _invalid(path, f"'{after}' ist kein Geschwisterblock an dieser Stelle")
    index = ids.index(after)
    upper = siblings[index + 1]["position"] if index + 1 < len(siblings) else None
    return positions.between(siblings[index]["position"], upper)


async def _parent(ctx: OpContext, doc_id: str, parent: str | None, path: str = "parent") -> dict[str, Any] | None:
    if parent is None:
        return None
    found = await _load_block(ctx, parent)
    if found["doc_id"] != doc_id:
        raise _invalid(path, f"Block '{parent}' liegt in einem anderen Dokument")
    return found


def _touch_doc_sql(doc_id: str):
    return text("UPDATE documents SET updated_at = now() WHERE id = :id"), {"id": doc_id}


async def _touch_doc(ctx: OpContext, doc_id: str) -> None:
    await ctx.touch("document", doc_id, f"doc:{doc_id}")
    stmt, params = _touch_doc_sql(doc_id)
    await ctx.session.execute(stmt, params)


# ── Keys in Props auflösen (L 1) ─────────────────────────────────────────────


class _Refs:
    """Löst Tabellen-, Spalten- und Workflow-Referenzen in Block-Props zu IDs auf und prüft, dass sie existieren."""

    def __init__(self, ctx: OpContext):
        self.ctx = ctx
        self.tables: dict[str, str] = {}

    async def table(self, ref: str) -> str:
        if ref in self.tables:
            return self.tables[ref]
        table_id = await self.ctx.resolve("table", ref)
        found = await self.ctx.session.execute(text("SELECT 1 FROM tables WHERE id = :id"), {"id": table_id})
        if found.first() is None:
            raise PipelineError("NOT_FOUND", f"Tabelle '{ref}' wurde nicht gefunden")
        self.tables[ref] = table_id
        return table_id

    async def column(self, ref: str, table_id: str) -> str:
        column_id = await self.ctx.resolve("column", ref, table_id)
        found = await self.ctx.session.execute(
            text("SELECT 1 FROM columns WHERE id = :id AND table_id = :t"), {"id": column_id, "t": table_id})
        if found.first() is None:
            raise PipelineError("NOT_FOUND", f"Spalte '{ref}' gehört nicht zur Tabelle '{table_id}'")
        return column_id

    async def qualified(self, ref: str) -> str:
        """`tabelle.spalte` oder `col_…`."""
        if ref.startswith("col_"):
            row = (await self.ctx.session.execute(
                text("SELECT table_id FROM columns WHERE id = :id"), {"id": ref})).first()
            if row is None:
                raise PipelineError("NOT_FOUND", f"Spalte '{ref}' wurde nicht gefunden")
            return ref
        table, dot, column = ref.partition(".")
        if not dot or not column:
            raise PipelineError("VALIDATION", f"Spalte '{ref}': 'tabelle.spalte' oder die Spalten-ID angeben",
                                {"errors": {"column": f"'{ref}' braucht die Form tabelle.spalte"}})
        return await self.column(column, await self.table(table))

    async def workflow(self, ref: str) -> str:
        return ref if ref.startswith("wf_") else await self.ctx.resolve("workflow", ref)


async def resolve_props(ctx: OpContext, block_type: str, props: dict[str, Any]) -> dict[str, Any]:
    """Props mit Keys -> Props mit IDs (nur Verweise auf Tabellen, Spalten, Workflows)."""
    refs = _Refs(ctx)
    out = json.loads(json.dumps(props))
    if block_type == "table_view":
        table_id = out["table"] = await refs.table(out["table"])
        if out.get("columns"):
            out["columns"] = [await refs.column(c, table_id) for c in out["columns"]]
        for condition in out.get("filter") or []:
            condition["column"] = await refs.column(condition["column"], table_id)
        for sort in out.get("sort") or []:
            sort["column"] = await refs.column(sort["column"], table_id)
    elif block_type == "field":
        if out.get("column"):
            out["column"] = await refs.qualified(out["column"])
        if out.get("reference_table"):
            out["reference_table"] = await refs.table(out["reference_table"])
    elif block_type == "line_items":
        for column in out.get("columns") or []:
            if column.get("column"):
                column["column"] = await refs.qualified(column["column"])
    elif block_type == "form":
        for action in out.get("actions") or []:
            table_id = action["table"] = await refs.table(action["table"])
            if action.get("values"):
                action["values"] = {await refs.column(k, table_id): v for k, v in action["values"].items()}
    elif block_type == "workflow":
        out["workflow"] = await refs.workflow(out["workflow"])
    return out


# ── Bäume schreiben ──────────────────────────────────────────────────────────


async def _check_new_ids(ctx: OpContext, ids: list[str]) -> None:
    taken = (await ctx.session.execute(
        text("SELECT id, doc_id FROM blocks WHERE id = ANY(CAST(:ids AS text[]))"), {"ids": ids})).mappings().all()
    if taken:
        first = taken[0]
        raise _invalid("blocks", f"Block-ID '{first['id']}' existiert bereits (Dokument '{first['doc_id']}')")


async def _insert_nodes(ctx: OpContext, doc_id: str, parent_id: str | None, nodes: list[dict[str, Any]],
                        positions: list[str]) -> None:
    for node, position in zip(nodes, positions, strict=True):
        props = await resolve_props(ctx, node["type"], node["props"])
        await ctx.session.execute(
            text("""INSERT INTO blocks (id, doc_id, parent_id, position, type, props)
                    VALUES (:id, :doc, :parent, :pos, :type, CAST(:props AS jsonb))"""),
            {"id": node["id"], "doc": doc_id, "parent": parent_id, "pos": position, "type": node["type"],
             "props": json.dumps(props)})
        await ctx.touch("block", node["id"], created=True)
        ctx.set_references("block", node["id"], D.block_edges(node["type"], props))
        children = node.get("children") or []
        if children:
            await _insert_nodes(ctx, doc_id, node["id"], children, _keys(len(children)))


def _check_tree(nodes: list[dict[str, Any]], parent_type: str | None, path: str) -> list[str]:
    try:
        return D.validate_tree(nodes, parent_type, path)
    except D.NestingError as exc:
        raise _invalid(exc.path, str(exc)) from exc


def _dump_blocks(blocks: list[Any]) -> list[dict[str, Any]]:
    try:
        return D.normalize_nodes([b.model_dump(mode="json", by_alias=True) for b in blocks])
    except ValidationError as exc:
        raise _from_pydantic(exc, "blocks") from exc


# ── doc.* ────────────────────────────────────────────────────────────────────


@register("doc.create")
async def doc_create(ctx: OpContext, op: DocCreate):
    if op.blocks is not None and op.markdown is not None:
        raise _invalid("markdown", "'blocks' und 'markdown' schließen sich aus")
    if not op.title.strip():
        raise _invalid("title", "Der Titel darf nicht leer sein")
    exists = await ctx.session.execute(text("SELECT 1 FROM documents WHERE id = :id"), {"id": op.id})
    if exists.first() is not None:
        raise _invalid("id", f"Dokument-ID '{op.id}' existiert bereits")

    if op.markdown is not None:
        try:
            raw = M.markdown_to_blocks(op.markdown)
            nodes = D.normalize_nodes(raw)
        except ValueError as exc:
            if isinstance(exc, ValidationError):
                raise _from_pydantic(exc, "markdown") from exc
            raise _invalid("markdown", str(exc)) from exc
    else:
        nodes = _dump_blocks(op.blocks or [])
    ids = _check_tree(nodes, None, "markdown" if op.markdown is not None else "blocks")
    if ids:
        await _check_new_ids(ctx, ids)

    owner_workflow = owner_step = None
    if op.owner is not None:
        owner_workflow = op.owner.workflow if op.owner.workflow.startswith("wf_") \
            else await ctx.resolve("workflow", op.owner.workflow)
        owner_step = op.owner.step
    await ctx.session.execute(
        text("""INSERT INTO documents (id, workspace_id, title, owner_workflow, owner_step)
                VALUES (:id, :ws, :title, :wf, :step)"""),
        {"id": op.id, "ws": ctx.workspace_id, "title": op.title, "wf": owner_workflow, "step": owner_step})
    await ctx.touch("document", op.id, f"doc:{op.id}", created=True)
    await _insert_nodes(ctx, op.id, None, nodes, _keys(len(nodes)))
    ctx.add_inverse({"op": "doc.delete", "doc": op.id})
    return {"id": op.id, "block_ids": ids}


@register("doc.update")
async def doc_update(ctx: OpContext, op: DocUpdate):
    doc = await _load_doc(ctx, op.doc)
    if not op.title.strip():
        raise _invalid("title", "Der Titel darf nicht leer sein")
    await ctx.session.execute(text("UPDATE documents SET title = :t, updated_at = now() WHERE id = :id"),
                              {"t": op.title, "id": op.doc})
    await ctx.touch("document", op.doc, f"doc:{op.doc}")
    ctx.add_inverse({"op": "doc.update", "doc": op.doc, "title": doc["title"]})


@register("doc.delete")
async def doc_delete(ctx: OpContext, op: DocDelete):
    doc = await _load_doc(ctx, op.doc)
    blocks = [{**dict(r), "props": _j(r["props"])} for r in (await ctx.session.execute(
        text("SELECT id, parent_id, position, type, props FROM blocks WHERE doc_id = :id"),
        {"id": op.doc})).mappings()]
    block_ids = {b["id"] for b in blocks}
    blockers = [u for u in await references.usages(ctx, "document", op.doc)
                if u["source_kind"] == "workflow" or (u["source_kind"] == "block" and u["source_id"] not in block_ids
                                                      and u["via"] != "mention")]
    if blockers:
        listing = ", ".join(f"{u['source_kind']} {u['source_id']} ({u['via']})" for u in blockers)
        raise PipelineError("IN_USE", f"Dokument '{op.doc}' wird verwendet von: {listing}", {"usages": blockers})
    for block in blocks:
        ctx.set_references("block", block["id"], [])
        await ctx.touch("block", block["id"], deleted=True)
    await ctx.session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": op.doc})
    await ctx.touch("document", op.doc, f"doc:{op.doc}", deleted=True)
    owner = {"workflow": doc["owner_workflow"], "step": doc["owner_step"]} if doc["owner_workflow"] else None
    ctx.add_inverse({"op": "doc.create", "id": op.doc, "title": doc["title"], "owner": owner,
                     "blocks": D.flat_to_tree(blocks)})


# ── block.* ──────────────────────────────────────────────────────────────────


@register("block.insert")
async def block_insert(ctx: OpContext, op: BlockInsert):
    await _load_doc(ctx, op.doc)
    parent = await _parent(ctx, op.doc, op.parent)
    nodes = _dump_blocks([op.block])
    ids = _check_tree(nodes, parent["type"] if parent else None, "block")
    await _check_new_ids(ctx, ids)
    position = _position(await _siblings(ctx, op.doc, op.parent), op.after)
    await _insert_nodes(ctx, op.doc, op.parent, nodes, [position])
    await _touch_doc(ctx, op.doc)
    ctx.add_inverse({"op": "block.delete", "block": nodes[0]["id"]})
    return {"id": nodes[0]["id"], "position": position, "block_ids": ids}


@register("block.update")
async def block_update(ctx: OpContext, op: BlockUpdate):
    block = await _load_block(ctx, op.block)
    presence.check_block_free(f"doc:{block['doc_id']}", block["id"], ctx.actor)
    merged = {**block["props"], **op.props}
    try:
        props = D.normalize_props(block["type"], merged)
    except ValidationError as exc:
        raise _from_pydantic(exc, "props") from exc
    props = await resolve_props(ctx, block["type"], props)
    changed = [k for k in props if props.get(k) != block["props"].get(k)]
    if not changed:
        return {"id": op.block, "changed": []}
    await ctx.session.execute(text("UPDATE blocks SET props = CAST(:p AS jsonb) WHERE id = :id"),
                              {"p": json.dumps(props), "id": op.block})
    await ctx.touch("block", op.block)
    ctx.set_references("block", op.block, D.block_edges(block["type"], props))
    await _touch_doc(ctx, block["doc_id"])
    ctx.add_inverse({"op": "block.update", "block": op.block, "props": {k: block["props"].get(k) for k in changed}})
    return {"id": op.block, "changed": changed}


@register("block.move")
async def block_move(ctx: OpContext, op: BlockMove):
    block = await _load_block(ctx, op.block)
    presence.check_block_free(f"doc:{block['doc_id']}", block["id"], ctx.actor)
    parent = await _parent(ctx, block["doc_id"], op.parent)
    if parent is not None:
        ancestors = (await ctx.session.execute(text("""
            WITH RECURSIVE up AS (
              SELECT id, parent_id FROM blocks WHERE id = :id
              UNION ALL
              SELECT b.id, b.parent_id FROM blocks b JOIN up u ON b.id = u.parent_id)
            SELECT id FROM up"""), {"id": parent["id"]})).scalars().all()
        if block["id"] in ancestors:
            raise _invalid("parent", "Ein Block kann nicht in sich selbst oder einen seiner Nachfahren verschoben werden")
    try:
        D.check_nesting(parent["type"] if parent else None, block["type"])
    except ValueError as exc:
        raise _invalid("parent", str(exc)) from exc
    if op.after == op.block:
        raise _invalid("after", "Ein Block kann nicht hinter sich selbst stehen")

    old_siblings = await _siblings(ctx, block["doc_id"], block["parent_id"])
    old_ids = [s["id"] for s in old_siblings]
    previous = old_ids[old_ids.index(block["id"]) - 1] if old_ids.index(block["id"]) > 0 else "^"
    position = _position(await _siblings(ctx, block["doc_id"], op.parent, exclude=block["id"]), op.after)
    await ctx.session.execute(text("UPDATE blocks SET parent_id = :p, position = :pos WHERE id = :id"),
                              {"p": op.parent, "pos": position, "id": block["id"]})
    await ctx.touch("block", block["id"])
    await _touch_doc(ctx, block["doc_id"])
    ctx.add_inverse({"op": "block.move", "block": block["id"], "parent": block["parent_id"], "after": previous})
    return {"id": block["id"], "position": position}


@register("block.delete")
async def block_delete(ctx: OpContext, op: BlockDelete):
    block = await _load_block(ctx, op.block)
    subtree = await _subtree(ctx, op.block)
    for item in subtree:
        presence.check_block_free(f"doc:{block['doc_id']}", item["id"], ctx.actor)
    siblings = [s["id"] for s in await _siblings(ctx, block["doc_id"], block["parent_id"])]
    index = siblings.index(block["id"])
    previous = siblings[index - 1] if index > 0 else "^"
    tree = D.flat_to_tree([{**b, "parent_id": None if b["id"] == block["id"] else b["parent_id"]} for b in subtree])
    await ctx.session.execute(text("DELETE FROM blocks WHERE id = ANY(CAST(:ids AS text[]))"),
                              {"ids": [b["id"] for b in subtree]})
    for item in subtree:
        await ctx.touch("block", item["id"], deleted=True)
        ctx.set_references("block", item["id"], [])
    await _touch_doc(ctx, block["doc_id"])
    ctx.add_inverse({"op": "block.insert", "doc": block["doc_id"], "parent": block["parent_id"],
                     "after": previous, "block": tree[0]})
    return {"deleted": [b["id"] for b in subtree]}
