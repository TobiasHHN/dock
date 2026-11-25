"""Abschnitte bilden (T 3.1). Reine Funktionen ohne DB, damit sie einfach testbar sind."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable

MAX_TOKENS = 500  # grob: Wörter getrennt durch Leerraum


@dataclass
class Chunk:
    content: str
    block_ids: list[str] = field(default_factory=list)

    @property
    def chunk_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def count_tokens(text: str) -> int:
    return len(text.split())


# ── Text aus Blöcken ─────────────────────────────────────────────────────────


def inline_text(content: Iterable[dict[str, Any]] | None) -> str:
    parts: list[str] = []
    for run in content or []:
        if isinstance(run, dict) and run.get("t") in ("text", "link") and run.get("text"):
            parts.append(run["text"])
    return "".join(parts).strip()


def block_text(block: dict[str, Any]) -> str:
    """Durchsuchbarer Text eines einzelnen Blocks (ohne Kinder)."""
    typ = block["type"]
    props = block.get("props") or {}
    if typ in ("heading", "paragraph", "list_item"):
        return inline_text(props.get("content"))
    if typ == "code":
        return (props.get("text") or "").strip()
    if typ == "table_view":
        return f"Tabelle {props['table']}" if props.get("table") else ""
    if typ == "field":
        return " ".join(x for x in (props.get("label"), props.get("key")) if x)
    if typ == "line_items":
        labels = [props.get("label") or props.get("key") or ""]
        for col in props.get("columns") or []:
            labels.append(col.get("label") or col.get("key") or "")
        return " ".join(x for x in labels if x)
    if typ == "form":
        return " ".join(b["label"] for b in props.get("buttons") or [] if b.get("label"))
    if typ == "image":
        return (props.get("alt") or "").strip()
    return ""  # list, quote, divider, workflow: nur Kinder


def flatten(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flach gespeicherte Blöcke (parent_id + position) in Baum-Reihenfolge bringen (Tiefensuche)."""
    ids = {b["id"] for b in blocks}
    children: dict[str | None, list[dict[str, Any]]] = {}
    for b in blocks:
        parent = b.get("parent_id")
        children.setdefault(parent if parent in ids else None, []).append(b)
    for lst in children.values():
        lst.sort(key=lambda b: b["position"])
    out: list[dict[str, Any]] = []

    def walk(parent: str | None) -> None:
        for b in children.get(parent, []):
            out.append(b)
            walk(b["id"])

    walk(None)
    return out


# ── Dokumente ────────────────────────────────────────────────────────────────


def _split(prefix: str, entries: list[tuple[str, str]], head_id: str | None) -> list[Chunk]:
    """entries: (Text, block_id). Teilt bei MAX_TOKENS in mehrere Chunks; jeder Chunk bekommt den Präfix."""
    chunks: list[Chunk] = []
    lines: list[str] = []
    ids: list[str] = [head_id] if head_id else []
    base = count_tokens(prefix)
    used = base

    def flush() -> None:
        if lines:
            chunks.append(Chunk(content="\n".join([prefix, *lines]), block_ids=list(ids)))
        lines.clear()
        ids.clear()
        if head_id:
            ids.append(head_id)

    for text, bid in entries:
        words = text.split()
        pieces = [" ".join(words[i : i + MAX_TOKENS]) for i in range(0, len(words), MAX_TOKENS)]
        for piece in pieces:
            n = len(piece.split())
            if lines and used + n > MAX_TOKENS:
                flush()
                used = base
            lines.append(piece)
            if bid not in ids:
                ids.append(bid)
            used += n
    flush()
    return chunks


def chunk_document(title: str, blocks: list[dict[str, Any]]) -> list[Chunk]:
    """Abschnitt = Überschrift plus folgende Blöcke bis zur nächsten Überschrift gleicher oder höherer Ebene.
    Inhalt vor der ersten Überschrift bildet einen eigenen Abschnitt (Titel = Dokumenttitel).
    Eine Überschrift der tieferen Ebene beginnt einen eigenen Abschnitt, der Pfad steht im Präfix."""
    # Abschnitt: [Pfad, head_id, Einträge]
    sections: list[list[Any]] = [[[], None, []]]
    path: list[tuple[int, str]] = []
    for b in flatten(blocks):
        text = block_text(b)
        if b["type"] == "heading":
            level = int((b.get("props") or {}).get("level", 1))
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, text))
            sections.append([[p[1] for p in path], b["id"], []])
        elif text:
            sections[-1][2].append((text, b["id"]))

    chunks: list[Chunk] = []
    for heading_path, head_id, entries in sections:
        if not entries and not (head_id and heading_path and heading_path[-1]):
            continue
        prefix = " > ".join([title, *[h for h in heading_path if h]])
        if entries:
            chunks.extend(_split(prefix, entries, head_id))
        else:  # Überschrift ohne Inhalt
            chunks.append(Chunk(content=prefix, block_ids=[head_id]))
    return chunks


# ── Tabellen und Workflows ───────────────────────────────────────────────────


def _col_type(t: Any) -> str:
    return t.get("kind", "") if isinstance(t, dict) else str(t or "")


def chunk_table(name: str, key: str, columns: list[dict[str, Any]], description: str | None = None) -> list[Chunk]:
    lines = [f"Tabelle {name} ({key})"]
    if description:
        lines.append(description)
    if columns:
        lines.append("Spalten: " + ", ".join(f"{c['name']} ({c['key']}, {_col_type(c.get('type'))})" for c in columns))
    return [Chunk(content="\n".join(lines))]


def chunk_workflow(
    name: str, key: str, steps: list[dict[str, Any]], step_docs: dict[str, str], description: str | None = None
) -> list[Chunk]:
    """steps: Step-Dicts der Definition; step_docs: doc_id -> Text des Schritt-Dokuments."""
    lines = [f"Workflow {name} ({key})"]
    if description:
        lines.append(description)
    if steps:
        lines.append("Schritte: " + ", ".join(f"{s['name']} ({s['key']})" for s in steps))
    for s in steps:
        text = step_docs.get(s.get("document", ""), "")
        if text:
            lines.append(f"Schritt {s['name']}: {text}")
    content = "\n".join(lines)
    if count_tokens(content) <= MAX_TOKENS:
        return [Chunk(content=content)]
    toks = content.split()
    return [Chunk(content=" ".join(toks[i : i + MAX_TOKENS])) for i in range(0, len(toks), MAX_TOKENS)]


def document_plain_text(blocks: list[dict[str, Any]]) -> str:
    return "\n".join(t for t in (block_text(b) for b in flatten(blocks)) if t)
