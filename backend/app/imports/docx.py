"""Word -> Ops (L 8.3, T 2.9). Reine Funktion ohne FastAPI/DB (Task 3.7).

Die Datei wird von oben nach unten gelesen. Überschriften, Absätze (mit Marks und Links) und Listen werden Blöcke.
Zeilen der Form „Bezeichnung: ____“ und Kontrollkästchen werden Felder, Tabellen mit leeren Zeilen unter dem Kopf
werden Zeilenlisten (`line_items`), Tabellen mit Inhalt eigene Tabellen samt `table_view`. Alle Felder und
Zeilenlisten landen in **einem** `form`-Block an der Stelle des ersten Feldes (Text dazwischen steht dahinter).
Der Parser vergibt die IDs selbst, damit `created` sie vor der Ausführung nennen kann.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any

from docx import Document
from docx.table import Table, _Cell
from docx.text.hyperlink import Hyperlink
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from app.domain.ids import new_id

from .xlsx import (INSERT_CHUNK, MAX_BYTES, MAX_COLUMNS, MAX_ROWS, MAX_UNCOMPRESSED, ImportFileError, ImportResult,
                   _unique, slug)

FIELD = re.compile(r"^(?P<label>[^:]{1,60}):\s*(_{3,}|\.{3,}|…+|\[\s*\])\s*$")
CHECKBOX = re.compile(r"^\s*(?:[☐□❑❏☑☒]|\[\s?[xX ]?\s?\])\s*(?P<label>\S.*?)\s*$")
HEADING_ID = re.compile(r"^(?:Heading|berschrift)\s*(\d)$", re.IGNORECASE)
MONO_FONTS = {"consolas", "courier", "courier new", "menlo", "monaco"}
NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

NO_WRITE_WARNING = ("Formular schreibt nirgends hin: Es hat keine Actions und keine Buttons. Mit bind_table oder im "
                    "Batch (create_row/create_rows und Buttons) ergänzen")


# ── Datei prüfen ─────────────────────────────────────────────────────────────


def _check_file(data: bytes) -> None:
    if not data:
        raise ImportFileError("Die Datei ist leer.")
    if len(data) > MAX_BYTES:
        raise ImportFileError(f"Die Datei ist zu groß ({len(data) // (1024 * 1024)} MB, erlaubt sind 10 MB).")
    if data[:8] == bytes.fromhex("D0CF11E0A1B11AE1"):
        raise ImportFileError("Die Datei ist passwortgeschützt oder im alten .doc-Format. Bitte als .docx "
                              "ohne Passwort speichern.")
    if data[:2] != b"PK":
        raise ImportFileError("Das ist keine gültige .docx-Datei (kein Word-Dokument-Format).")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED:
                raise ImportFileError("Die Datei ist entpackt zu groß.")
    except zipfile.BadZipFile as exc:
        raise ImportFileError("Die Datei ist beschädigt und lässt sich nicht öffnen.") from exc
    if "word/document.xml" not in names:
        raise ImportFileError("Das ist keine gültige .docx-Datei (word/document.xml fehlt).")


# ── Absätze lesen ────────────────────────────────────────────────────────────


def _heading_level(p: Paragraph) -> int | None:
    style = p.style
    if style is None:
        return None
    name = style.name or ""
    m = re.match(r"^Heading\s*(\d)$", name, re.IGNORECASE) or HEADING_ID.match(style.style_id or "")
    if m:
        return min(max(int(m.group(1)), 1), 3)
    if name.lower() == "title":
        return 1
    return None


def _numbering_format(doc, num_id: str, ilvl: str) -> str | None:
    try:
        numbering = doc.part.numbering_part.element
        for num in numbering.findall(f"{NS_W}num"):
            if num.get(f"{NS_W}numId") != num_id:
                continue
            abstract_id = num.find(f"{NS_W}abstractNumId").get(f"{NS_W}val")
            for abstract in numbering.findall(f"{NS_W}abstractNum"):
                if abstract.get(f"{NS_W}abstractNumId") != abstract_id:
                    continue
                for lvl in abstract.findall(f"{NS_W}lvl"):
                    if lvl.get(f"{NS_W}ilvl") == ilvl:
                        fmt = lvl.find(f"{NS_W}numFmt")
                        return fmt.get(f"{NS_W}val") if fmt is not None else None
    except Exception:  # fehlende Nummerierungsdefinition: als Aufzählung behandeln
        return None
    return None


def _list_kind(doc, p: Paragraph) -> str | None:
    """`bullet`, `ordered` oder None."""
    name = (p.style.name if p.style is not None else "") or ""
    if name.startswith("List Bullet"):
        return "bullet"
    if name.startswith("List Number"):
        return "ordered"
    for ppr in (p._p.pPr, getattr(getattr(p.style, "element", None), "pPr", None)):
        num_pr = getattr(ppr, "numPr", None)
        if num_pr is None or num_pr.numId is None or num_pr.numId.val == 0:
            continue
        ilvl = num_pr.ilvl.val if num_pr.ilvl is not None else 0
        fmt = _numbering_format(doc, str(num_pr.numId.val), str(ilvl))
        return "bullet" if fmt in (None, "bullet", "none") else "ordered"
    return None


def _marks(run: Run) -> list[str]:
    marks: list[str] = []
    style = (run.style.name if run.style is not None else "") or ""
    if run.bold or style == "Strong":
        marks.append("bold")
    if run.italic or style in ("Emphasis", "Intense Emphasis"):
        marks.append("italic")
    if run.font.strike:
        marks.append("strike")
    if (run.font.name or "").lower() in MONO_FONTS:
        marks.append("code")
    return marks


def _inline(p: Paragraph) -> list[dict[str, Any]]:
    """Inline-Inhalt: Textläufe mit Marks (benachbarte gleiche Läufe zusammengefasst) und Links."""
    out: list[dict[str, Any]] = []
    for item in p.iter_inner_content():
        if isinstance(item, Hyperlink):
            text = item.text
            if not text:
                continue
            if item.address:
                out.append({"t": "link", "text": text, "href": item.address})
                continue
            parts = [(r.text, _marks(r)) for r in item.runs]  # interner Sprungmarker: nur Text
        else:
            parts = [(item.text, _marks(item))]
        for text, marks in parts:
            if not text:
                continue
            last = out[-1] if out else None
            if last and last["t"] == "text" and last.get("marks", []) == marks:
                last["text"] += text
            else:
                piece: dict[str, Any] = {"t": "text", "text": text}
                if marks:
                    piece["marks"] = marks
                out.append(piece)
    return out


def _plain(content: list[dict[str, Any]]) -> str:
    return "".join(i.get("text", "") for i in content)


# ── Felder erkennen ──────────────────────────────────────────────────────────


def _input_for(label: str) -> str:
    low = label.lower()
    if "datum" in low or re.search(r"\bam\b", low):
        return "date"
    if "menge" in low or "anzahl" in low:
        return "integer"
    if any(w in low for w in ("preis", "betrag", "summe")):
        return "currency"
    return "text"


def _split_required(label: str) -> tuple[str, bool]:
    label = label.strip()
    required = label.endswith("*")
    return label.rstrip("*").strip(), required


# ── Tabellen lesen ───────────────────────────────────────────────────────────


def _cells(table: Table, row) -> list[str]:
    return [_Cell(tc, table).text.strip() for tc in row._tr.tc_lst]  # verbundene Zellen nur einmal


def _read_table(table: Table, name: str) -> tuple[list[str], list[list[str]]]:
    rows = [_cells(table, r) for r in table.rows]
    if not rows:
        return [], []
    if len(rows[0]) > MAX_COLUMNS:
        raise ImportFileError(f"Tabelle '{name}' hat mehr als {MAX_COLUMNS} Spalten.")
    if len(rows) - 1 > MAX_ROWS:
        raise ImportFileError(f"Tabelle '{name}' hat mehr als {MAX_ROWS} Zeilen.")
    return rows[0], rows[1:]


# ── Parser ───────────────────────────────────────────────────────────────────


class _Parser:
    def __init__(self, doc, bind_table: str | None, tables: list[dict[str, Any]] | None):
        self.doc, self.bind_table = doc, bind_table
        self.existing = tables or []
        self.result = ImportResult()
        self.blocks: list[dict[str, Any]] = []
        self.form: dict[str, Any] | None = None
        self.form_keys: set[str] = set()
        self.fields: list[dict[str, Any]] = []  # Felder und Zeilenlisten für `created`
        self.table_keys = {t["key"] for t in self.existing if t.get("key")}
        self.new_tables: list[dict[str, Any]] = []
        self.current_list: dict[str, Any] | None = None
        self.last_heading: str | None = None
        self.first_heading: str | None = None
        self.images = 0
        self.bound: dict[str, str] | None = None

    # -- Blöcke --

    def add(self, block: dict[str, Any]) -> None:
        self.current_list = None
        self.blocks.append(block)

    def form_block(self) -> dict[str, Any]:
        if self.form is None:
            self.form = {"id": new_id("block"), "type": "form", "props": {"actions": [], "buttons": []},
                         "children": []}
            self.add(self.form)
        return self.form

    def field_key(self, label: str, what: str) -> str:
        base = slug(label, "feld")
        key = _unique(base, self.form_keys)
        if key != base:
            self.result.warnings.append(f"{what} '{label}' kommt mehrfach vor, der Key ist '{key}'")
        return key

    # -- Absatz --

    def paragraph(self, p: Paragraph) -> None:
        self.images += len(p._p.xpath(".//w:drawing | .//w:pict"))
        content = _inline(p)
        text = _plain(content).strip()
        level = _heading_level(p)
        if level is not None:
            if not text:
                return
            self.last_heading = text
            self.first_heading = self.first_heading or text
            self.add({"id": new_id("block"), "type": "heading", "props": {"level": level, "content": content}})
            return
        if not text:
            return
        kind = _list_kind(self.doc, p)
        if kind is not None:
            ordered = kind == "ordered"
            if self.current_list is None or self.current_list["props"]["ordered"] != ordered:
                self.add({"id": new_id("block"), "type": "list", "props": {"ordered": ordered}, "children": []})
                self.current_list = self.blocks[-1]
            self.current_list["children"].append(
                {"id": new_id("block"), "type": "list_item", "props": {"content": content}})
            return
        m = FIELD.match(text)
        if m:
            label, required = _split_required(m.group("label"))
            if label:
                self.add_field(label, _input_for(label), required)
                return
        m = CHECKBOX.match(text)
        if m:
            label, required = _split_required(m.group("label"))
            if label:
                self.add_field(label, "boolean", required)
                return
        self.add({"id": new_id("block"), "type": "paragraph", "props": {"content": content}})

    def add_field(self, label: str, input_: str, required: bool) -> None:
        form = self.form_block()
        key = self.field_key(label, "Feld")
        block_id = new_id("block")
        props: dict[str, Any] = {"key": key, "label": label, "input": input_, "required": required}
        form["children"].append({"id": block_id, "type": "field", "props": props})
        self.fields.append({"kind": "field", "key": key, "label": label, "block": block_id})

    # -- Tabelle --

    def table(self, table: Table) -> None:
        self.images += len(table._tbl.xpath(".//w:drawing | .//w:pict"))
        name = self.last_heading or "Tabelle"
        header, body = _read_table(table, name)
        if not any(header):
            self.result.warnings.append(f"Eine Tabelle nach '{name}' hat keine Kopfzeile und wurde ausgelassen")
            return
        cols = [(i, h) for i, h in enumerate(header) if h]
        skipped = len(header) - len(cols)
        if skipped:
            self.result.warnings.append(f"Tabelle '{name}': {skipped} Spalte(n) ohne Spaltenkopf übersprungen")
        body = [r for r in body if any(r)]
        if not body:
            self.line_items(cols)
        else:
            self.filled_table(name, cols, body)

    def line_items(self, cols: list[tuple[int, str]]) -> None:
        form = self.form_block()
        label = cols[0][1]
        key = self.field_key(label, "Zeilenliste")
        keys: set[str] = set()
        columns = [{"key": _unique(slug(h, "spalte"), keys), "label": h, "input": _input_for(h)} for _, h in cols]
        block_id = new_id("block")
        form["children"].append({"id": block_id, "type": "line_items",
                                 "props": {"key": key, "label": label, "columns": columns}})
        self.fields.append({"kind": "line_items", "key": key, "label": label, "block": block_id,
                            "columns": [c["key"] for c in columns]})

    def filled_table(self, name: str, cols: list[tuple[int, str]], body: list[list[str]]) -> None:
        base = slug(name, "tabelle")
        key = _unique(base, self.table_keys)
        table_name = name
        if key != base:
            table_name = f"{name} {key.rsplit('_', 1)[-1]}"
            self.result.warnings.append(f"Tabelle '{name}': der Key '{base}' ist schon vergeben, "
                                        f"die Tabelle heißt '{key}'")
        col_keys: set[str] = set()
        columns = [{"id": new_id("column"), "key": _unique(slug(h, "spalte"), col_keys), "name": h,
                    "type": {"kind": "text"}} for _, h in cols]
        table_id = new_id("table")
        self.result.ops.append({"op": "table.create", "id": table_id, "key": key, "name": table_name,
                                "display_column": columns[0]["id"], "columns": columns})
        rows = []
        for r in body:
            values = {c["key"]: r[i] for c, (i, _) in zip(columns, cols) if i < len(r) and r[i]}
            rows.append({"id": new_id("row"), "values": values})
        for start in range(0, len(rows), INSERT_CHUNK):
            self.result.ops.append({"op": "row.insert", "table": table_id, "rows": rows[start:start + INSERT_CHUNK]})
        self.new_tables.append({"id": table_id, "key": key, "name": table_name, "columns": columns, "rows": len(rows)})
        self.add({"id": new_id("block"), "type": "table_view", "props": {"table": table_id}})

    # -- Bindung an eine Tabelle (bind_table) --

    def find_table(self) -> dict[str, Any] | None:
        ref = (self.bind_table or "").strip().lower()
        for t in [*self.new_tables, *self.existing]:  # zuerst Tabellen aus demselben Import
            if ref in ((t.get("key") or "").lower(), (t.get("name") or "").lower(), (t.get("id") or "").lower()):
                return t
        return None

    def bind(self) -> None:
        warnings = self.result.warnings
        if self.form is None:
            warnings.append(f"bind_table '{self.bind_table}': Das Dokument hat kein Formular, es wurde nichts "
                            "gebunden")
            return
        table = self.find_table()
        if table is None:
            warnings.append(f"bind_table '{self.bind_table}': Tabelle nicht gefunden, das Formular bleibt ohne "
                            "Actions. Die Tabelle zuerst anlegen oder importieren")
            warnings.append(NO_WRITE_WARNING)
            return
        by_name: dict[str, dict[str, Any]] = {}
        for col in table.get("columns") or []:
            for alias in (str(col.get("name", "")).lower(), str(col.get("key", "")).lower(),
                          slug(str(col.get("name", "")), "x")):
                by_name.setdefault(alias, col)
        used: set[str] = set()
        values: dict[str, str] = {}
        blocks = {c["id"]: c for c in self.form["children"]}
        for f in self.fields:
            if f["kind"] != "field":
                continue
            col = by_name.get(f["label"].lower()) or by_name.get(f["key"])
            if col is None or col["id"] in used:
                warnings.append(f"Feld '{f['label']}' passt zu keiner Spalte der Tabelle '{table['key']}' und wird "
                                "nicht gespeichert")
                continue
            used.add(col["id"])
            blocks[f["block"]]["props"]["column"] = col["id"]
            values[col["id"]] = "{{fields." + f["key"] + "}}"
        for f in self.fields:
            if f["kind"] == "line_items":
                warnings.append(f"Zeilenliste '{f['label']}' wird von 'Speichern' nicht geschrieben (dafür im Batch "
                                "eine Action create_rows ergänzen)")
        for col in table.get("columns") or []:
            if col.get("required") and col["id"] not in used and col.get("default") in (None, ""):
                warnings.append(f"Spalte '{col['name']}' der Tabelle '{table['key']}' ist Pflicht, hat aber kein "
                                "Feld im Formular")
        if not values:
            warnings.append(NO_WRITE_WARNING)
            return
        props = self.form["props"]
        props["actions"] = [{"key": "save", "type": "create_row", "table": table["id"], "values": values}]
        props["buttons"] = [{"id": "save", "label": "Speichern", "style": "primary", "actions": ["save"]}]
        self.bound = {"id": table["id"], "key": table["key"]}


def _owner_dict(owner: Any) -> dict[str, str] | None:
    if not owner:
        return None
    if isinstance(owner, dict):
        d = {"workflow": owner.get("workflow"), "step": owner.get("step")}
    else:
        text = str(owner).strip()
        try:
            loaded = json.loads(text)
        except ValueError:
            loaded = None
        if isinstance(loaded, dict):
            d = {"workflow": loaded.get("workflow"), "step": loaded.get("step")}
        else:
            wf, sep, step = text.partition(":" if ":" in text else "/")
            d = {"workflow": wf.strip(), "step": step.strip()} if sep else {}
    if not d.get("workflow") or not d.get("step"):
        raise ImportFileError("owner muss Workflow und Schritt nennen, z. B. 'bestellfreigabe:erfassen' oder "
                              '{"workflow": "bestellfreigabe", "step": "erfassen"}.')
    return {"workflow": str(d["workflow"]), "step": str(d["step"])}


def parse_docx(data: bytes, title: str | None = None, owner: dict[str, str] | str | None = None,
               bind_table: str | None = None, tables: list[dict[str, Any]] | None = None,
               filename: str | None = None) -> ImportResult:
    """Überschriften, Absätze, Listen, Felder („Bezeichnung: ____“), Kontrollkästchen, Tabellen -> `doc.create`.

    `tables`: vorhandene Tabellen (`id`, `key`, `name`, `columns[id,key,name,required,default]`) für `bind_table`
    und gegen Key-Kollisionen. Der Parser selbst greift nicht auf die Datenbank zu."""
    _check_file(data)
    owner_in = _owner_dict(owner)
    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:
        raise ImportFileError(f"Die Word-Datei lässt sich nicht lesen: {exc}") from exc
    p = _Parser(doc, bind_table, tables)
    try:
        for item in doc.iter_inner_content():
            if isinstance(item, Paragraph):
                p.paragraph(item)
            elif isinstance(item, Table):
                p.table(item)
    except ImportFileError:
        raise
    except Exception as exc:
        raise ImportFileError(f"Die Word-Datei lässt sich nicht lesen: {exc}") from exc
    if not p.blocks:
        raise ImportFileError("Die Datei enthält keine importierbaren Inhalte (kein Text, keine Tabelle).")

    warnings = p.result.warnings
    if bind_table:
        p.bind()
    elif p.form is not None:
        warnings.append(NO_WRITE_WARNING)
    if p.images:
        warnings.append(f"{p.images} Bild(er) ausgelassen (Bilder werden nicht importiert)")
    try:
        if any(par.text.strip() for s in doc.sections for part in (s.header, s.footer) for par in part.paragraphs):
            warnings.append("Kopf-/Fußzeilen ausgelassen")
        if any(rel.reltype.endswith("/comments") for rel in doc.part.rels.values()):
            warnings.append("Kommentare ausgelassen")
    except Exception:  # Zusatzhinweise sind nie ein Grund abzulehnen
        pass

    doc_title = (title or "").strip() or p.first_heading \
        or re.sub(r"\.docx$", "", (filename or "").strip(), flags=re.IGNORECASE) or "Importiertes Dokument"
    doc_id = new_id("document")
    op: dict[str, Any] = {"op": "doc.create", "id": doc_id, "title": doc_title, "blocks": p.blocks}
    if owner_in:
        op["owner"] = owner_in
    p.result.ops.append(op)
    form_info = None
    if p.form is not None:
        form_info = {"block": p.form["id"], "fields": {f["key"]: f["block"] for f in p.fields if f["kind"] == "field"},
                     "line_items": {f["key"]: {"block": f["block"], "columns": f["columns"]}
                                    for f in p.fields if f["kind"] == "line_items"},
                     "actions": [a["key"] for a in p.form["props"]["actions"]]}
    created: dict[str, Any] = {
        "tables": [{"id": t["id"], "key": t["key"], "name": t["name"], "columns": [c["key"] for c in t["columns"]],
                    "column_ids": {c["key"]: c["id"] for c in t["columns"]}, "rows": t["rows"]}
                   for t in p.new_tables],
        "documents": [{"id": doc_id, "title": doc_title, "form": form_info}]}
    if p.bound:
        created["bound_table"] = p.bound
    p.result.created = created
    return p.result
