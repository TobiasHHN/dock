"""Blöcke ⇄ Markdown mit Direktiven (L 8.2). Task 1.4.

Grundregel: **jede nicht leere Zeile ist ein Block**, die Block-ID steht am Zeilenende als `{#blk_…}`.

```
# Titel {#blk_h1}                                  Überschrift (# bis ###)
Absatz mit **fett**, *kursiv*, ~~durch~~, `code`,  Absatz; Inline: [Text](https://…), @[doc_…] (Erwähnung),
{{run.input.x}} (berechneter Wert)                 Sonderzeichen mit Backslash (\\*, \\[, \\{, \\n = Zeilenumbruch)
- Punkt {#li1 list=l1}                             Liste: `list=` nennt die ID der Liste (nur am ersten Punkt),
  1. verschachtelt {#li2 list=l2}                  Einrückung 2 Leerzeichen je Ebene, `- [x]` = abgehakt
:::quote{#q1} … :::                                Zitat, Kinder bis zum schließenden `:::`
:::form{#blk_form}                                 Formular (Actions und Buttons stehen nur im JSON)
::field{#blk_name key=name label="Name" column=bestellungen.name}
::line_items{#blk_items key=artikel label="Artikel" columns="artikelname,preis" from=artikel}
:::
```fence mit Sprache {#blk_c}                      Code (Zaun wird länger, wenn der Code ``` enthält)
--- {#blk_d}                                       Trennlinie
::table_view{#id table=artikel columns="a,b" editable=true}   weitere Blätter: image, workflow, table_view
```

Attribute: `schlüssel=wert`; Werte bare (`name`, `true`, `5`), `"Text mit Leerzeichen"` oder `'JSON'` für Listen/Objekte.
Fehlt eine ID, vergibt `markdown_to_blocks` eine neue. Der Parser wirft `ValueError` mit Zeilennummer.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.domain.documents import PROPS_MODEL, flat_to_tree
from app.domain.ids import new_id

COMPACT = {"field", "line_items"}  # aufeinanderfolgende Eingabefelder ohne Leerzeile
LEAF_DIRECTIVES = {"image", "table_view", "field", "line_items", "workflow"}
CONTAINERS = {"form", "quote"}
OMIT_PROPS = {"form": {"actions", "buttons"}}  # nur im JSON (8.2)
MARK_ORDER = ("bold", "italic", "code", "strike")
MARK_TOKEN = {"bold": "**", "italic": "*", "strike": "~~"}

# ── Attribute ────────────────────────────────────────────────────────────────

_BARE = re.compile(r"^[A-Za-z0-9_.:/@\-]+$")
_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def _enc(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        if _BARE.match(value) and value not in {"true", "false", "null"} and not _NUM.match(value):
            return value
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    blob = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "'" + blob.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _bare(token: str) -> Any:
    if token == "true":
        return True
    if token == "false":
        return False
    if token == "null":
        return None
    if _NUM.match(token):
        return float(token) if "." in token else int(token)
    return token


def _parse_attrs(body: str, line_no: int) -> tuple[str | None, dict[str, Any]]:
    """`#id key=wert …` -> (id, attrs)."""
    i, n = 0, len(body)
    block_id: str | None = None
    attrs: dict[str, Any] = {}
    while i < n:
        if body[i].isspace():
            i += 1
            continue
        if body[i] == "#":
            j = i
            while j < n and not body[j].isspace():
                j += 1
            block_id = body[i + 1:j]
            i = j
            continue
        j = i
        while j < n and body[j] != "=" and not body[j].isspace():
            j += 1
        key = body[i:j]
        i = j
        if i >= n or body[i] != "=":
            attrs[key] = True
            continue
        i += 1
        if i < n and body[i] in "\"'":
            quote, i = body[i], i + 1
            chars: list[str] = []
            while i < n and body[i] != quote:
                if body[i] == "\\" and i + 1 < n:
                    nxt = body[i + 1]
                    if quote == '"':
                        chars.append("\n" if nxt == "n" else nxt)
                    else:
                        chars.append(nxt if nxt in "\\'" else "\\" + nxt)
                    i += 2
                else:
                    chars.append(body[i])
                    i += 1
            if i >= n:
                raise ValueError(f"Zeile {line_no}: Anführungszeichen bei '{key}' nicht geschlossen")
            i += 1
            raw = "".join(chars)
            if quote == '"':
                attrs[key] = raw
            else:
                try:
                    attrs[key] = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Zeile {line_no}: Attribut '{key}' enthält kein gültiges JSON") from exc
        else:
            j = i
            while j < n and not body[j].isspace():
                j += 1
            attrs[key] = _bare(body[i:j])
            i = j
    return block_id, attrs


def _attr_string(block_id: str, attrs: dict[str, Any]) -> str:
    parts = [f"#{block_id}"] + [f"{k}={_enc(v)}" for k, v in attrs.items()]
    return " ".join(parts)


# ── Inline ───────────────────────────────────────────────────────────────────

_ESC = set("\\*`~[]{}")


def _esc(text: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(text):
        if ch == "\n":
            out.append("\\n")
        elif ch in _ESC or (ch == "@" and text[i + 1:i + 2] == "["):
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _marks(part: dict[str, Any]) -> frozenset[str]:
    return frozenset(part.get("marks") or [])


def _inline(content: list[dict[str, Any]]) -> str:
    out: list[str] = []
    active: frozenset[str] = frozenset()
    pending: list[dict[str, Any]] = []
    for part in content:  # gleiche Marks direkt hintereinander zusammenfassen
        if pending and part["t"] == "text" and pending[-1]["t"] == "text" and _marks(part) == _marks(pending[-1]):
            pending[-1] = {**pending[-1], "text": pending[-1]["text"] + part["text"]}
        else:
            pending.append(part)
    for part in pending:
        want = _marks(part) if part["t"] == "text" else frozenset()
        for mark in MARK_ORDER:  # schließen, dann öffnen: Schaltzeichen sind kommutativ
            if mark in MARK_TOKEN and mark in active and mark not in want:
                out.append(MARK_TOKEN[mark])
        for mark in MARK_ORDER:
            if mark in MARK_TOKEN and mark in want and mark not in active:
                out.append(MARK_TOKEN[mark])
        active = frozenset(m for m in want if m in MARK_TOKEN)
        if part["t"] == "text":
            out.append(f"`{_esc(part['text'])}`" if "code" in want else _esc(part["text"]))
        elif part["t"] == "link":
            href = part["href"].replace("\\", "\\\\").replace(")", "\\)")
            out.append(f"[{_esc(part['text'])}]({href})")
        elif part["t"] == "mention":
            out.append("@[" + part["target"].replace("\\", "\\\\").replace("]", "\\]") + "]")
        elif part["t"] == "value":
            expr = part["expr"]
            out.append(expr if expr.startswith("{{") and expr.endswith("}}") else "{{" + expr + "}}")
    for mark in MARK_ORDER:
        if mark in MARK_TOKEN and mark in active:
            out.append(MARK_TOKEN[mark])
    return "".join(out)


def _unescape_char(text: str, i: int) -> tuple[str, int]:
    """Bei `text[i] == "\\"`: (Zeichen, nächster Index)."""
    if i + 1 >= len(text):
        return "\\", i + 1
    nxt = text[i + 1]
    return ("\n" if nxt == "n" else nxt), i + 2


def _read_until(text: str, i: int, closer: str) -> tuple[str, int] | None:
    """Liest bis zum ersten unmaskierten `closer` (ab Index i), entmaskiert. Rückgabe (Text, Index nach closer)."""
    chars: list[str] = []
    while i < len(text):
        if text[i] == "\\":
            ch, i = _unescape_char(text, i)
            chars.append(ch)
        elif text.startswith(closer, i):
            return "".join(chars), i + len(closer)
        else:
            chars.append(text[i])
            i += 1
    return None


def _parse_inline(text: str) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    buf: list[str] = []
    state = {"bold": False, "italic": False, "strike": False}

    def marks(extra: str | None = None) -> list[str]:
        on = {m for m, v in state.items() if v} | ({extra} if extra else set())
        return [m for m in MARK_ORDER if m in on]

    def flush() -> None:
        if buf:
            parts.append({"t": "text", "text": "".join(buf), "marks": marks()})
            buf.clear()

    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            c, i = _unescape_char(text, i)
            buf.append(c)
        elif text.startswith("**", i) or text.startswith("~~", i) or ch == "*":
            flush()
            token = "**" if text.startswith("**", i) else "~~" if text.startswith("~~", i) else "*"
            name = {"**": "bold", "~~": "strike", "*": "italic"}[token]
            state[name] = not state[name]
            i += len(token)
        elif ch == "`":
            found = _read_until(text, i + 1, "`")
            if found is None:
                buf.append(ch)
                i += 1
            else:
                flush()
                parts.append({"t": "text", "text": found[0], "marks": marks("code")})
                i = found[1]
        elif ch == "[":
            label = _read_until(text, i + 1, "]")
            if label and text.startswith("(", label[1]):
                href = _read_until(text, label[1] + 1, ")")
                if href:
                    flush()
                    parts.append({"t": "link", "text": label[0], "href": href[0]})
                    i = href[1]
                    continue
            buf.append(ch)
            i += 1
        elif text.startswith("@[", i):
            found = _read_until(text, i + 2, "]")
            if found is None:
                buf.append(ch)
                i += 1
            else:
                flush()
                parts.append({"t": "mention", "target": found[0]})
                i = found[1]
        elif text.startswith("{{", i):
            end = text.find("}}", i + 2)
            if end < 0:
                buf.append(ch)
                i += 1
            else:
                flush()
                parts.append({"t": "value", "expr": text[i:end + 2]})
                i = end + 2
        else:
            buf.append(ch)
            i += 1
    flush()
    return parts


# ── Blöcke -> Markdown ───────────────────────────────────────────────────────


def _line_text(content: list[dict[str, Any]]) -> str:
    s = _inline(content)
    if s == " ":
        return "\\ "
    if s.startswith(" "):
        s = "\\" + s
    if s.endswith(" "):
        s = s[:-1] + "\\ "
    return s


def _lead_escape(s: str) -> str:
    if s and (s[0] in "#>-+:|" or re.match(r"\d+[.)]", s)):
        return "\\" + s
    return s


def _suffix(block_id: str, extra: str = "") -> str:
    return "{#" + block_id + (" " + extra if extra else "") + "}"


def _with_id(text: str, block_id: str, extra: str = "") -> str:
    return f"{text} {_suffix(block_id, extra)}" if text else _suffix(block_id, extra)


def _props_attrs(block_type: str, props: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, field in PROPS_MODEL[block_type].model_fields.items():
        if name in OMIT_PROPS.get(block_type, set()):
            continue
        if field.alias and field.alias in props:
            value = props[field.alias]
        else:
            value = props.get(name)
        if field.is_required():
            if value is None:
                continue
        elif value == field.get_default(call_default_factory=True):
            continue
        out[name] = value
    if block_type == "table_view":
        out = _comma_list(out, "columns")
    if block_type == "line_items" and "columns" in out:
        cols = out["columns"]
        simple = all(set(c) <= {"key", "label", "column", "input", "required"}
                     and not c.get("label") and not c.get("input") and not c.get("required") for c in cols)
        tables = {c["column"].partition(".")[0] for c in cols if c.get("column") and "." in c["column"]}
        qualified = all(c.get("column") and "." in c["column"] for c in cols) if cols else False
        unqualified = all(not c.get("column") for c in cols)
        if simple and (unqualified or (qualified and len(tables) == 1)) and all(_plain(c["key"]) for c in cols):
            out["columns"] = ",".join(c["key"] for c in cols)
            if qualified:
                out["from"] = tables.pop()
    return out


def _plain(key: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9_\-]+$", key))


def _comma_list(attrs: dict[str, Any], name: str) -> dict[str, Any]:
    value = attrs.get(name)
    if isinstance(value, list) and value and all(isinstance(v, str) and _plain(v) for v in value):
        attrs = {**attrs, name: ",".join(value)}
    return attrs


def _emit_list(node: dict[str, Any], level: int) -> list[str]:
    lines: list[str] = []
    ordered = bool(node["props"].get("ordered"))
    for index, item in enumerate((c for c in node.get("children", []) if c["type"] == "list_item")):
        marker = f"{index + 1}. " if ordered else "- "
        checked = item["props"].get("checked")
        box = "" if checked is None else "[x] " if checked else "[ ] "
        text = _line_text(item["props"].get("content") or [])
        extra = f"list={node['id']}" if index == 0 else ""
        tail = _suffix(item["id"], extra)
        lines.append("  " * level + marker + box + (text + " " if text else "") + tail)
        for child in item.get("children", []):
            if child["type"] == "list":
                lines += _emit_list(child, level + 1)
    return lines


def _emit_node(node: dict[str, Any]) -> list[str]:
    t, props, bid = node["type"], node["props"], node["id"]
    if t == "heading":
        level = min(max(int(props.get("level") or 1), 1), 3)
        return [f"{'#' * level} " + _with_id(_line_text(props.get("content") or []), bid)]
    if t == "paragraph":
        return [_with_id(_lead_escape(_line_text(props.get("content") or [])), bid)]
    if t == "list":
        return _emit_list(node, 0)
    if t == "list_item":  # außerhalb einer Liste nicht vorgesehen, verlustarm als Liste mit einem Punkt
        return _emit_list({"id": new_id("block"), "props": {"ordered": False}, "children": [node]}, 0)
    if t in CONTAINERS:
        attrs = _props_attrs(t, props)
        head = f":::{t}{{{_attr_string(bid, attrs)}}}"
        return [head, *_emit_nodes(node.get("children", [])), ":::"]
    if t == "code":
        text = props.get("text") or ""
        longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
        fence = "`" * max(3, longest + 1)
        lang = props.get("language") or ""
        lang = lang if re.match(r"^[A-Za-z0-9_+\-.]+$", lang) else ""
        return [fence + lang + " " + _suffix(bid), *(text.split("\n") if text else []), fence]
    if t == "divider":
        return ["--- " + _suffix(bid)]
    return [f"::{t}{{{_attr_string(bid, _props_attrs(t, props))}}}"]


def _emit_nodes(nodes: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    previous: str | None = None
    for node in nodes:
        if previous is not None and not (previous in COMPACT and node["type"] in COMPACT):
            lines.append("")
        lines += _emit_node(node)
        previous = node["type"]
    return lines


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Markdown mit Block-IDs `{#blk_…}`; Actions/Buttons stehen nur im JSON.
    `blocks`: flach (id, parent_id, position, type, props) oder bereits als Baum (children)."""
    tree = flat_to_tree(blocks) if blocks and "parent_id" in blocks[0] else blocks
    lines = _emit_nodes(tree)
    return "\n".join(lines) + "\n" if lines else ""


# ── Markdown -> Blöcke ───────────────────────────────────────────────────────

_ID_TAIL = re.compile(r"^(.*?)(?:\s|^)\{#([A-Za-z0-9_\-]+)(?:\s+list=([A-Za-z0-9_\-]+))?\}\s*$")
_FENCE = re.compile(r"^(`{3,})([^`\s{]*)\s*(?:\{#([A-Za-z0-9_\-]+)\})?\s*$")
_CONTAINER = re.compile(r"^:::([a-z_]+)(?:\{(.*)\})?\s*$")
_LEAF = re.compile(r"^::([a-z_]+)(?:\{(.*)\})?\s*$")
_ITEM = re.compile(r"^( *)(?:[-*+]|\d+[.)])\s+(.*)$")
_ORDERED = re.compile(r"^ *\d+[.)]\s")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_DIVIDER = re.compile(r"^---+\s*(?:\{#([A-Za-z0-9_\-]+)\})?\s*$")


def _split_id(line: str) -> tuple[str, str | None, str | None]:
    found = _ID_TAIL.match(line)
    if not found:
        return _rstrip_escaped(line.lstrip()), None, None
    return _rstrip_escaped(found.group(1).lstrip()), found.group(2), found.group(3)


def _rstrip_escaped(text: str) -> str:
    stripped = text.rstrip()
    trailing = len(stripped) - len(stripped.rstrip("\\"))
    return stripped + " " if trailing % 2 == 1 and len(stripped) < len(text) else stripped


def _props_from_attrs(block_type: str, attrs: dict[str, Any], line_no: int) -> dict[str, Any]:
    props = dict(attrs)
    if block_type == "table_view" and isinstance(props.get("columns"), str):
        props["columns"] = [c.strip() for c in props["columns"].split(",") if c.strip()]
    if block_type == "line_items":
        source = props.pop("from", None)
        if isinstance(props.get("columns"), str):
            keys = [c.strip() for c in props["columns"].split(",") if c.strip()]
            props["columns"] = [{"key": k, **({"column": f"{source}.{k}"} if source else {})} for k in keys]
        elif source is not None:
            raise ValueError(f"Zeile {line_no}: 'from' gehört zu 'columns' als kommagetrennte Liste")
    return props


def markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    """Gegenstück: Markdown (inkl. `:::form`, `::field`, `::line_items`) -> Baum aus {id, type, props, children}.
    Ohne `{#…}` vergibt der Parser neue IDs, mit `{#…}` bleibt die ID erhalten (Hin- und Rückweg ergeben dieselben
    Blöcke). Das Ergebnis ist noch nicht gegen den API-Vertrag geprüft (`documents.normalize_nodes`)."""
    root: list[dict[str, Any]] = []
    containers: list[dict[str, Any]] = []  # offene :::form / :::quote
    open_lists: list[dict[str, Any]] = []  # offene Listen je Einrückungsebene
    last_items: list[dict[str, Any]] = []

    def target() -> list[dict[str, Any]]:
        return containers[-1]["children"] if containers else root

    def node(block_type: str, props: dict[str, Any], block_id: str | None) -> dict[str, Any]:
        return {"id": block_id or new_id("block"), "type": block_type, "props": props, "children": []}

    def reset_lists() -> None:
        open_lists.clear()
        last_items.clear()

    lines = markdown.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i]
        line_no = i + 1
        i += 1
        line = raw.rstrip()
        if not line.strip():
            continue

        fence = _FENCE.match(line.strip())
        if fence:
            reset_lists()
            body: list[str] = []
            while i < len(lines) and not re.match(rf"^\s*`{{{len(fence.group(1))},}}\s*$", lines[i]):
                body.append(lines[i].rstrip("\r"))
                i += 1
            if i >= len(lines):
                raise ValueError(f"Zeile {line_no}: Codeblock nicht geschlossen")
            i += 1
            props = {"text": "\n".join(body)}
            if fence.group(2):
                props["language"] = fence.group(2)
            target().append(node("code", props, fence.group(3)))
            continue

        if re.match(r"^:::\s*$", line.strip()):
            reset_lists()
            if not containers:
                raise ValueError(f"Zeile {line_no}: ':::' schließt nichts")
            containers.pop()
            continue

        container = _CONTAINER.match(line.strip())
        if container:
            reset_lists()
            name = container.group(1)
            if name not in CONTAINERS:
                raise ValueError(f"Zeile {line_no}: unbekannter Container ':::{name}' (erlaubt: form, quote)")
            block_id, attrs = _parse_attrs(container.group(2) or "", line_no)
            created = node(name, attrs, block_id)
            target().append(created)
            containers.append(created)
            continue

        leaf = _LEAF.match(line.strip())
        if leaf:
            reset_lists()
            name = leaf.group(1)
            if name not in LEAF_DIRECTIVES:
                raise ValueError(f"Zeile {line_no}: unbekannte Direktive '::{name}' "
                                 f"(erlaubt: {', '.join(sorted(LEAF_DIRECTIVES))})")
            block_id, attrs = _parse_attrs(leaf.group(2) or "", line_no)
            target().append(node(name, _props_from_attrs(name, attrs, line_no), block_id))
            continue

        divider = _DIVIDER.match(line.strip())
        if divider:
            reset_lists()
            target().append(node("divider", {}, divider.group(1)))
            continue

        item = _ITEM.match(line)
        if item:
            depth = len(item.group(1)) // 2
            depth = min(depth, len(open_lists))
            text, block_id, list_id = _split_id(item.group(2))
            checked = None
            box = re.match(r"^\[( |x|X)\]\s?(.*)$", text)
            if box:
                checked = box.group(1) != " "
                text = box.group(2)
            ordered = bool(_ORDERED.match(line))
            del open_lists[depth + 1:]
            del last_items[depth:]
            current = open_lists[depth] if depth < len(open_lists) else None
            if current is None or list_id or bool(current["props"]["ordered"]) != ordered:
                parent_children = target() if depth == 0 else last_items[depth - 1]["children"]
                current = node("list", {"ordered": ordered}, list_id)
                parent_children.append(current)
                del open_lists[depth:]
                open_lists.append(current)
            props: dict[str, Any] = {"content": _parse_inline(text)}
            if checked is not None:
                props["checked"] = checked
            entry = node("list_item", props, block_id)
            current["children"].append(entry)
            del last_items[depth:]
            last_items.append(entry)
            continue

        reset_lists()
        heading = _HEADING.match(line)
        if heading:
            text, block_id, _ = _split_id(heading.group(2))
            target().append(node("heading", {"level": min(len(heading.group(1)), 3),
                                             "content": _parse_inline(text)}, block_id))
            continue

        text, block_id, _ = _split_id(line)
        target().append(node("paragraph", {"content": _parse_inline(text)}, block_id))

    if containers:
        raise ValueError(f"Container ':::{containers[-1]['type']}' ist nicht geschlossen")
    return root
