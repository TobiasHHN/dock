"""Erzeugt die kleinen Beispieldateien für die Import-Fixtures (spec/fixtures/files/).
Aufruf: backend/.venv/bin/python spec/make_sample_files.py"""
from pathlib import Path

from docx import Document
from openpyxl import Workbook

OUT = Path(__file__).parent / "fixtures" / "files"
OUT.mkdir(parents=True, exist_ok=True)

# 1) Übersicht: saubere Typen (Text, Ganzzahl, Währung, Datum)
wb = Workbook()
ws = wb.active
ws.title = "Bestellungen"
ws.append(["Name", "Kostenstelle", "Anzahl", "Betrag", "Datum"])
import datetime as dt

rows = [("Anna Beispiel", "4711", 2, 498.0, dt.date(2026, 11, 3)),
        ("Ben Mitarbeiter", "4712", 5, 125.5, dt.date(2026, 11, 10))]
for r in rows:
    ws.append(list(r))
for i in range(2, 2 + len(rows)):
    ws.cell(row=i, column=4).number_format = '#,##0.00 "€"'
    ws.cell(row=i, column=5).number_format = "DD.MM.YYYY"
wb.save(OUT / "uebersicht.xlsx")

# 2) Randfälle: gemischte Spalte, leere Zeile, leeres zweites Blatt
wb = Workbook()
ws = wb.active
ws.title = "Daten"
ws.append(["Titel", "Wert"])
ws.append(["a", 1])
ws.append(["b", "zwei"])
ws.append([None, None])
ws.append(["c", 3])
wb.create_sheet("Leer")
wb.save(OUT / "randfaelle.xlsx")

# 3) Formular mit Feldern, Pflichtfeld, Kontrollkästchen und leerer Artikeltabelle
d = Document()
d.add_heading("Bestellformular", level=1)
d.add_paragraph("Bitte alle Felder ausfüllen.")
d.add_paragraph("Name*: ____")
d.add_paragraph("Kostenstelle: ____")
t = d.add_table(rows=3, cols=3)
for c, h in enumerate(["Artikel", "Preis", "Anzahl"]):
    t.cell(0, c).text = h
d.add_paragraph("☐ Lieferung eilig")
d.add_paragraph("Vielen Dank.")
d.save(OUT / "formular.docx")

# 4) Dokument mit fettem Text, Liste und ausgefüllter Tabelle (wird Tabelle + table_view)
d = Document()
d.add_heading("Preisliste", level=1)
p = d.add_paragraph("Alle Preise ")
p.add_run("netto").bold = True
d.add_paragraph("Monitor", style="List Bullet")
d.add_paragraph("Tastatur", style="List Bullet")
t = d.add_table(rows=3, cols=2)
t.cell(0, 0).text, t.cell(0, 1).text = "Artikel", "Preis"
t.cell(1, 0).text, t.cell(1, 1).text = "Monitor", "249,00"
t.cell(2, 0).text, t.cell(2, 1).text = "Tastatur", "39,90"
d.save(OUT / "preisliste.docx")
print("ok")
