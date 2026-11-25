"""Erzeugt die Demo-Dateien Bestelluebersicht.xlsx und Bestellformular.docx (demo/prompts.md §3, T 2.9).
Aufruf: backend/.venv/bin/python demo/make_demo_files.py"""
import datetime as dt
from pathlib import Path

from docx import Document
from docx.shared import Pt
from openpyxl import Workbook

OUT = Path(__file__).parent
EURO_FORMAT = '#,##0.00 "€"'
DATE_FORMAT = "DD.MM.YYYY"

# 1) Bestelluebersicht.xlsx: ein Blatt "Bestellungen", keine Formeln, keine Leerzeilen
wb = Workbook()
ws = wb.active
ws.title = "Bestellungen"
ws.append(["Name", "Kostenstelle", "Bestelldatum", "Gesamtbetrag"])
rows = [
    ("Anna Beispiel", "4710", dt.date(2026, 11, 3), 498.00),
    ("Ben Mitarbeiter", "4711", dt.date(2026, 11, 10), 125.50),
    ("Anna Beispiel", "4712", dt.date(2026, 11, 17), 39.90),
]
for name, kostenstelle, datum, betrag in rows:
    ws.append([name, kostenstelle, datum, betrag])
for row in range(2, 2 + len(rows)):
    ws.cell(row=row, column=2).number_format = "@"
    ws.cell(row=row, column=3).number_format = DATE_FORMAT
    ws.cell(row=row, column=4).number_format = EURO_FORMAT
wb.save(OUT / "Bestelluebersicht.xlsx")

# 2) Bestellformular.docx: Überschrift, Felder, leere Artikeltabelle, Bemerkung
d = Document()
d.core_properties.title = "Bestellformular"
d.core_properties.author = "Demo"
d.add_heading("Bestellformular", level=1)
d.add_paragraph("Bitte Name, Kostenstelle und die benötigten Artikel angeben.")
d.add_paragraph("Name*: ____")
d.add_paragraph("Kostenstelle*: ____")
table = d.add_table(rows=4, cols=4)
table.style = d.styles["Table Grid"]
for col, header in enumerate(["Artikelname", "Artikelnummer", "Preis", "Anzahl"]):
    table.cell(0, col).text = header
    for run in table.cell(0, col).paragraphs[0].runs:
        run.bold = True
d.add_paragraph("Bemerkung: ____")
d.add_paragraph("Vielen Dank.")
d.save(OUT / "Bestellformular.docx")

print("ok")
