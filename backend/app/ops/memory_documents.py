"""In-Memory-Fassung der Dokument-Ops für die gemeinsamen Fixtures (Task 1.4, Gegenstück zu
`ops/handlers/documents.py`). Zustand: `documents: [{id, title, owner?, version, blocks: [flache Blöcke]}]`.
Keys in Props werden hier nicht aufgelöst (kein Katalog nötig), Regeln und Normalisierung kommen aus
`app.domain.documents`."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.domain import documents as D
from app.domain import positions, text_ot
from app.domain.tables import DomainError
from app.ops.memory import Mem, memory_op


def _invalid(path: str, message: str) -> DomainError:
    return DomainError("VALIDATION", f"{path}: {message}", {path: message})


def _doc(mem: Mem, ref: str) -> dict[str, Any]:
    for doc in mem.state["documents"]:
        if doc["id"] == ref:
            doc.setdefault("blocks", [])
            return doc
    raise DomainError("NOT_FOUND", f"Dokument '{ref}' wurde nicht gefunden")


def _block(mem: Mem, ref: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for doc in mem.state["documents"]:
        for block in doc.get("blocks", []):
            if block["id"] == ref:
                return doc, block
    raise DomainError("NOT_FOUND", f"Block '{ref}' wurde nicht gefunden")


def _siblings(doc: dict[str, Any], parent: str | None, exclude: str | None = None) -> list[dict[str, Any]]:
    kids = [b for b in doc["blocks"] if b.get("parent_id") == parent and b["id"] != exclude]
    return sorted(kids, key=lambda b: b["position"].encode())


def _position(siblings: list[dict[str, Any]], after: str | None) -> str:
    if after is None:
        return positions.between(siblings[-1]["position"] if siblings else None, None)
    if after == "^":
        return positions.between(None, siblings[0]["position"] if siblings else None)
    ids = [s["id"] for s in siblings]
    if after not in ids:
        raise _invalid("after", f"'{after}' ist kein Geschwisterblock an dieser Stelle")
    i = ids.index(after)
    return positions.between(siblings[i]["position"], siblings[i + 1]["position"] if i + 1 < len(ids) else None)


def _bump(mem: Mem, doc: dict[str, Any], block: dict[str, Any] | None = None) -> None:
    """Versionen steigen je Batch genau einmal (wie `_bump_versions` der Pipeline)."""
    seen: set[str] = mem.__dict__.setdefault("_doc_bumped", set())
    if doc["id"] not in seen and ("document", doc["id"]) not in mem.created:
        doc["version"] = doc.get("version", 1) + 1
        seen.add(doc["id"])
    if block is not None and block["id"] not in seen and ("block", block["id"]) not in mem.created:
        block["version"] = block.get("version", 1) + 1
        seen.add(block["id"])


def _nodes(raw: list[Any], path: str) -> list[dict[str, Any]]:
    try:
        return D.normalize_nodes(raw)
    except ValidationError as exc:
        e = exc.errors()[0]
        loc = ".".join([path, *map(str, e["loc"])])
        raise _invalid(loc, e["msg"]) from exc


def _add_nodes(mem: Mem, doc: dict[str, Any], parent: str | None, nodes: list[dict[str, Any]],
               positions_: list[str]) -> None:
    for node, position in zip(nodes, positions_, strict=True):
        doc["blocks"].append({"id": node["id"], "parent_id": parent, "position": position, "type": node["type"],
                              "props": node["props"], "version": 1})
        mem.touch("block", node["id"], created=True)
        kids = node["children"]
        keys: list[str] = []
        prev = None
        for _ in kids:
            prev = positions.between(prev, None)
            keys.append(prev)
        _add_nodes(mem, doc, node["id"], kids, keys)


def _check_ids(mem: Mem, ids: list[str]) -> None:
    taken = {b["id"] for d in mem.state["documents"] for b in d.get("blocks", [])}
    for i in ids:
        if i in taken:
            raise _invalid("blocks", f"Block-ID '{i}' existiert bereits")


def _tree_ids(nodes: list[dict[str, Any]], parent_type: str | None, path: str) -> list[str]:
    try:
        return D.validate_tree(nodes, parent_type, path)
    except D.NestingError as exc:
        raise _invalid(exc.path, str(exc)) from exc


@memory_op("doc.create")
def doc_create(mem: Mem, op: dict[str, Any]) -> None:
    if any(d["id"] == op["id"] for d in mem.state["documents"]):
        raise _invalid("id", f"Dokument-ID '{op['id']}' existiert bereits")
    nodes = _nodes(op.get("blocks") or [], "blocks")
    ids = _tree_ids(nodes, None, "blocks")
    _check_ids(mem, ids)
    doc = {"id": op["id"], "title": op["title"], "version": 1, "blocks": []}
    if op.get("owner"):
        doc["owner"] = op["owner"]
    mem.state["documents"].append(doc)
    mem.touch("document", doc["id"], created=True)
    keys, prev = [], None
    for _ in nodes:
        prev = positions.between(prev, None)
        keys.append(prev)
    _add_nodes(mem, doc, None, nodes, keys)


@memory_op("doc.update")
def doc_update(mem: Mem, op: dict[str, Any]) -> None:
    doc = _doc(mem, op["doc"])
    doc["title"] = op["title"]
    _bump(mem, doc)


@memory_op("doc.delete")
def doc_delete(mem: Mem, op: dict[str, Any]) -> None:
    doc = _doc(mem, op["doc"])
    mem.state["documents"].remove(doc)


@memory_op("block.insert")
def block_insert(mem: Mem, op: dict[str, Any]) -> None:
    doc = _doc(mem, op["doc"])
    parent = op.get("parent")
    parent_type = None
    if parent:
        owner, found = _block(mem, parent)
        if owner is not doc:
            raise _invalid("parent", f"Block '{parent}' liegt in einem anderen Dokument")
        parent_type = found["type"]
    nodes = _nodes([op["block"]], "block")
    ids = _tree_ids(nodes, parent_type, "block")
    _check_ids(mem, ids)
    position = _position(_siblings(doc, parent), op.get("after"))
    _add_nodes(mem, doc, parent, nodes, [position])
    _bump(mem, doc)


@memory_op("block.update")
def block_update(mem: Mem, op: dict[str, Any]) -> None:
    doc, block = _block(mem, op["block"])
    try:
        props = D.normalize_props(block["type"], {**block["props"], **op["props"]})
    except ValidationError as exc:
        e = exc.errors()[0]
        raise _invalid(".".join(["props", *map(str, e["loc"])]), e["msg"]) from exc
    if props != block["props"]:
        block["props"] = props
        mem.touch("block", block["id"])
        _bump(mem, doc, block)


@memory_op("block.move")
def block_move(mem: Mem, op: dict[str, Any]) -> None:
    doc, block = _block(mem, op["block"])
    parent = op.get("parent")
    parent_type = None
    if parent:
        owner, found = _block(mem, parent)
        if owner is not doc:
            raise _invalid("parent", f"Block '{parent}' liegt in einem anderen Dokument")
        parent_type = found["type"]
        cursor: str | None = parent
        while cursor:
            if cursor == block["id"]:
                raise _invalid("parent", "Ein Block kann nicht in sich selbst oder einen seiner Nachfahren "
                                         "verschoben werden")
            cursor = next((b.get("parent_id") for b in doc["blocks"] if b["id"] == cursor), None)
    try:
        D.check_nesting(parent_type, block["type"])
    except ValueError as exc:
        raise _invalid("parent", str(exc)) from exc
    if op.get("after") == block["id"]:
        raise _invalid("after", "Ein Block kann nicht hinter sich selbst stehen")
    block["position"] = _position(_siblings(doc, parent, exclude=block["id"]), op.get("after"))
    block["parent_id"] = parent
    mem.touch("block", block["id"])
    _bump(mem, doc, block)


@memory_op("block.delete")
def block_delete(mem: Mem, op: dict[str, Any]) -> None:
    doc, block = _block(mem, op["block"])
    doomed = {block["id"]}
    grew = True
    while grew:
        grew = False
        for b in doc["blocks"]:
            if b.get("parent_id") in doomed and b["id"] not in doomed:
                doomed.add(b["id"])
                grew = True
    doc["blocks"] = [b for b in doc["blocks"] if b["id"] not in doomed]
    for i in doomed:
        mem.touch("block", i, deleted=True)
    _bump(mem, doc)


@memory_op("text.edit")
def text_edit(mem: Mem, op: dict[str, Any]) -> None:
    """Wendet den (vom Server bereits transformierten) Edit an; die Transformation braucht das Op-Log und
    ist eigens getestet (`spec/fixtures/text_ot/`)."""
    doc, block = _block(mem, op["block"])
    if block["type"] not in D.TEXT_TYPES:
        raise _invalid("block", f"'{block['type']}' hat keinen Text, text.edit gilt nur für "
                                f"{', '.join(sorted(D.TEXT_TYPES))}")
    content = text_ot.apply_edit(block["props"].get("content") or [], op)
    props = D.normalize_props(block["type"], {**block["props"], "content": content})
    if props != block["props"]:
        block["props"] = props
        mem.touch("block", block["id"])
        _bump(mem, doc, block)
