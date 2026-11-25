"""Dokumente: Blockbaum, Verschachtelungsregeln (L 3). Task 1.4.

Reine Logik ohne Datenbank: Verschachtelung prüfen, flache Blöcke in einen Baum umwandeln, Props normalisieren
und die Verweise eines Blocks (L 9) aus seinen aufgelösten Props ableiten.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel, TypeAdapter

from app.schemas import blocks as B

# Welche Kinder ein Blocktyp haben darf (L 3.2). Typen ohne Eintrag sind Blätter.
ALLOWED_CHILDREN: dict[str, set[str]] = {
    "list": {"list_item"},
    "list_item": {"list"},
    "quote": {"paragraph", "heading", "list"},
    "form": {"heading", "paragraph", "list", "quote", "code", "divider", "image", "table_view", "field",
             "line_items", "workflow"},
}

# Typen, die nur direkt unter einem bestimmten Elternblock stehen dürfen
ONLY_INSIDE: dict[str, str] = {"field": "form", "line_items": "form", "list_item": "list"}

PROPS_MODEL: dict[str, type[BaseModel]] = {
    "heading": B.HeadingProps, "paragraph": B.ParagraphProps, "list": B.ListProps, "list_item": B.ListItemProps,
    "quote": B.QuoteProps, "code": B.CodeProps, "divider": B.DividerProps, "image": B.ImageProps,
    "table_view": B.TableViewProps, "form": B.FormProps, "field": B.FieldProps,
    "line_items": B.LineItemsProps, "workflow": B.WorkflowBlockProps,
}
TEXT_TYPES = {"heading", "paragraph", "list_item"}  # Blöcke mit Inline-Inhalt

BLOCKS_ADAPTER: TypeAdapter[Any] = TypeAdapter(list[B.BlockIn])


class NestingError(ValueError):
    """Verletzte Verschachtelungs- oder Baumregel. `path` zeigt auf die Stelle im Baum (z. B. `blocks[0].children[2]`)."""

    def __init__(self, message: str, path: str = ""):
        super().__init__(message)
        self.path = path


def check_nesting(parent_type: str | None, child_type: str) -> None:
    """Wirft ValueError, wenn `child_type` unter `parent_type` nicht erlaubt ist (z. B. `field` nur in `form`)."""
    only = ONLY_INSIDE.get(child_type)
    if parent_type is None:
        if only:
            raise ValueError(f"'{child_type}' darf nur innerhalb von '{only}' stehen, nicht auf oberster Ebene")
        return
    if child_type in ALLOWED_CHILDREN.get(parent_type, set()):
        return
    if only:
        raise ValueError(f"'{child_type}' darf nur innerhalb von '{only}' stehen, nicht in '{parent_type}'")
    if parent_type not in ALLOWED_CHILDREN:
        raise ValueError(f"'{parent_type}' darf keine Kinder haben (hier: '{child_type}')")
    allowed = ", ".join(sorted(ALLOWED_CHILDREN[parent_type]))
    raise ValueError(f"'{child_type}' ist in '{parent_type}' nicht erlaubt (erlaubt: {allowed})")


def validate_tree(nodes: list[dict[str, Any]], parent_type: str | None = None, path: str = "blocks") -> list[str]:
    """Prüft Verschachtelung und eindeutige IDs eines Baums (Knoten: id, type, props, children).
    Gibt alle Block-IDs in Dokumentreihenfolge zurück, wirft NestingError mit Pfad."""
    ids: list[str] = []
    seen: set[str] = set()

    def visit(items: list[dict[str, Any]], parent: str | None, where: str) -> None:
        for i, node in enumerate(items):
            here = f"{where}[{i}]"
            try:
                check_nesting(parent, node["type"])
            except ValueError as exc:
                raise NestingError(str(exc), here) from exc
            if node["id"] in seen:
                raise NestingError(f"Block-ID '{node['id']}' kommt mehrfach vor", f"{here}.id")
            seen.add(node["id"])
            ids.append(node["id"])
            visit(node.get("children") or [], node["type"], f"{here}.children")

    visit(nodes, parent_type, path)
    return ids


def flat_to_tree(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flache Blöcke (id, parent_id, position, type, props) -> Baum aus {id, type, props, children}, Geschwister
    nach `position` sortiert. Das Ergebnis ist als `BlockIn` (doc.create, block.insert) wiederverwendbar."""
    by_parent: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        by_parent[block.get("parent_id")].append(block)

    def build(parent: str | None) -> list[dict[str, Any]]:
        kids = sorted(by_parent.get(parent, []), key=lambda b: b["position"])
        return [{"id": b["id"], "type": b["type"], "props": b["props"], "children": build(b["id"])} for b in kids]

    return build(None)


def walk(nodes: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Alle Knoten eines Baums in Dokumentreihenfolge (Vorordnung)."""
    for node in nodes:
        yield node
        yield from walk(node.get("children") or [])


def normalize_nodes(raw: list[Any]) -> list[dict[str, Any]]:
    """Prüft rohe Blöcke (Dicts oder Modelle) gegen den API-Vertrag und liefert normalisierte Knoten, deren Props
    vollständig (mit Standardwerten) und JSON-fähig sind. Wirft pydantic.ValidationError."""
    models = BLOCKS_ADAPTER.validate_python(raw)
    return [_dump_node(m) for m in models]


def _dump_node(model: Any) -> dict[str, Any]:
    return {"id": model.id, "type": model.type,
            "props": model.props.model_dump(mode="json", by_alias=True),
            "children": [_dump_node(c) for c in model.children]}


def normalize_props(block_type: str, props: dict[str, Any]) -> dict[str, Any]:
    """Validiert Props eines Typs und liefert die vollständige Form. Wirft pydantic.ValidationError."""
    model = PROPS_MODEL[block_type].model_validate(props)
    return model.model_dump(mode="json", by_alias=True)


# ── Verweise eines Blocks (L 9) ──────────────────────────────────────────────

_MENTION = re.compile(r"\b(doc|tbl|row|usr|wf)_[A-Za-z0-9]+")
_MENTION_KIND = {"doc": "document", "tbl": "table", "row": "row", "usr": "user", "wf": "workflow"}


def block_edges(block_type: str, props: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Kanten (target_kind, target_id, via) eines Blocks aus seinen AUFGELÖSTEN Props (IDs statt Keys)."""
    edges: list[tuple[str, str, str]] = []
    if block_type == "table_view":
        edges.append(("table", props["table"], "table_view"))
        edges += [("column", c, "table_view") for c in props.get("columns") or []]
        edges += [("column", f["column"], "filter") for f in props.get("filter") or []]
        edges += [("column", s["column"], "table_view") for s in props.get("sort") or []]
    elif block_type == "field":
        if props.get("column"):
            edges.append(("column", props["column"], "field.column"))
        if props.get("reference_table"):
            edges.append(("table", props["reference_table"], "field.column"))
    elif block_type == "line_items":
        edges += [("column", c["column"], "field.column") for c in props.get("columns") or [] if c.get("column")]
    elif block_type == "form":
        for action in props.get("actions") or []:
            edges.append(("table", action["table"], "action.table"))
            edges += [("column", col, "action.value") for col in (action.get("values") or {})]
    elif block_type == "workflow":
        edges.append(("workflow", props["workflow"], "workflow_block"))
    if block_type in TEXT_TYPES:
        for part in props.get("content") or []:
            if part.get("t") == "mention":
                found = _MENTION.search(part["target"])
                if found:
                    edges.append((_MENTION_KIND[found.group(1)], found.group(0), "mention"))
    return edges
