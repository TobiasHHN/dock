"""Prüft die Demo-Dateien aus demo/ (demo/make_demo_files.py, demo/prompts.md §3).
Strukturtests laufen immer. Import-Tests laufen mit den Parsern aus 3.6/3.7."""
import datetime as dt
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path

import pytest
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook

from app.imports.docx import parse_docx
from app.imports.xlsx import parse_xlsx

DEMO = Path(__file__).resolve().parents[2] / "demo"
XLSX = DEMO / "Bestelluebersicht.xlsx"
DOCX = DEMO / "Bestellformular.docx"
FIELD = re.compile(r"^(?P<label>[^:]{1,60}):\s*(_{3,}|\.{3,}|\[\s*\])\s*$")


# ── Strukturtests ────────────────────────────────────────────────────────────


def test_xlsx_structure():
    wb = load_workbook(XLSX)
    assert wb.sheetnames == ["Bestellungen"]
    ws = wb["Bestellungen"]
    assert [c.value for c in ws[1]] == ["Name", "Kostenstelle", "Bestelldatum", "Gesamtbetrag"]
    assert ws.max_row == 4  # Kopf + 3 Zeilen, keine Leerzeilen
    assert ws.max_column == 4

    names = [ws.cell(r, 1).value for r in range(2, 5)]
    assert names == ["Anna Beispiel", "Ben Mitarbeiter", "Anna Beispiel"]

    for r in range(2, 5):
        ks = ws.cell(r, 2)
        assert isinstance(ks.value, str) and ks.value.isdigit()
        assert ks.number_format == "@"

        datum = ws.cell(r, 3)
        assert isinstance(datum.value, dt.datetime)
        assert datum.number_format == "DD.MM.YYYY"

        betrag = ws.cell(r, 4)
        assert isinstance(betrag.value, (int, float)) and not isinstance(betrag.value, bool)
        assert betrag.number_format == '#,##0.00 "€"'

    assert [ws.cell(r, 2).value for r in range(2, 5)] == ["4710", "4711", "4712"]
    assert [ws.cell(r, 3).value.date() for r in range(2, 5)] == [
        dt.date(2026, 11, 3), dt.date(2026, 11, 10), dt.date(2026, 11, 17)]
    assert [ws.cell(r, 4).value for r in range(2, 5)] == [498.0, 125.5, 39.9]

    # keine Formeln
    assert not any(isinstance(c.value, str) and c.value.startswith("=") for row in ws.iter_rows() for c in row)


def _docx_body():
    doc = Document(DOCX)
    out = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append(Paragraph(child, doc))
        elif tag == "tbl":
            out.append(Table(child, doc))
    return out


def test_docx_structure_order_and_styles():
    body = _docx_body()
    paras = [b for b in body if isinstance(b, Paragraph)]
    tables = [b for b in body if isinstance(b, Table)]
    assert len(tables) == 1

    # Reihenfolge: Überschrift, Einleitung, Name, Kostenstelle, Tabelle, Bemerkung, Vielen Dank
    kinds = ["table" if isinstance(b, Table) else b.text for b in body]
    assert kinds == [
        "Bestellformular",
        "Bitte Name, Kostenstelle und die benötigten Artikel angeben.",
        "Name*: ____",
        "Kostenstelle*: ____",
        "table",
        "Bemerkung: ____",
        "Vielen Dank.",
    ]
    assert paras[0].style.name == "Heading 1"
    for p in paras[1:]:
        assert p.style.name == "Normal"

    # keine Bilder, Kopf-/Fußzeilen oder Kommentare
    doc = Document(DOCX)
    assert not doc.inline_shapes
    assert not any(p.text for s in doc.sections for p in s.header.paragraphs + s.footer.paragraphs)
    assert not any("graphic" in el.tag for el in doc.element.iter())
    assert "comments" not in [rel.reltype.rsplit("/", 1)[-1] for rel in doc.part.rels.values()]


def test_docx_field_lines_match_regex():
    labels = []
    for p in (b for b in _docx_body() if isinstance(b, Paragraph)):
        m = FIELD.match(p.text)
        if m:
            labels.append(m.group("label"))
    assert labels == ["Name*", "Kostenstelle*", "Bemerkung"]


def test_docx_table_header_and_empty_rows():
    table = next(b for b in _docx_body() if isinstance(b, Table))
    assert [c.text for c in table.rows[0].cells] == ["Artikelname", "Artikelnummer", "Preis", "Anzahl"]
    assert len(table.rows) == 4  # Kopf + 3 Zeilen
    for row in table.rows[1:]:
        assert all(cell.text == "" for cell in row.cells)


# ── Import-Tests (aktiv, sobald die Parser implementiert sind) ───────────────


def _as_dict(result):
    return asdict(result) if is_dataclass(result) else result


def test_xlsx_imports_without_warnings():
    try:
        result = parse_xlsx(XLSX.read_bytes())
    except NotImplementedError:
        result = None
    if result is None:
        pytest.skip("parse_xlsx noch nicht implementiert (Task 3.6)")
    assert _as_dict(result)["warnings"] == []


def test_docx_imports_with_single_warning():
    result = _as_dict(parse_docx(DOCX.read_bytes()))
    warnings = result["warnings"]
    assert len(warnings) == 1
    assert "Formular schreibt nirgends hin" in warnings[0]
    doc = result["ops"][-1]
    assert doc["title"] == "Bestellformular"
    form = next(b for b in doc["blocks"] if b["type"] == "form")
    kinds = [(c["type"], c["props"]["key"]) for c in form["children"]]
    assert kinds == [("field", "name"), ("field", "kostenstelle"), ("line_items", "artikelname"),
                     ("field", "bemerkung")]
    assert [c["props"]["required"] for c in form["children"] if c["type"] == "field"] == [True, True, False]
    items = form["children"][2]["props"]["columns"]
    assert [(c["key"], c["input"]) for c in items] == [
        ("artikelname", "text"), ("artikelnummer", "text"), ("preis", "currency"), ("anzahl", "integer")]
