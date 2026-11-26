"""Excel -> Ops (L 8.3, T 2.9). Reine Funktion ohne FastAPI/DB (Task 3.6).

Jedes Blatt wird eine Tabelle (`table.create` + `row.insert`). Die erste Zeile liefert die Spaltennamen, der
Spaltentyp wird aus den Werten abgeleitet. Der Parser vergibt die IDs selbst, damit `created` sie vor der
Ausführung nennen kann.
"""
from __future__ import annotations

import datetime as dt
import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

from openpyxl import load_workbook

from app.domain.ids import new_id

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 10_000
MAX_COLUMNS = 100
MAX_UNCOMPRESSED = 300 * 1024 * 1024  # Schutz vor Zip-Bomben
LONG_TEXT_LENGTH = 200
INSERT_CHUNK = 500  # Zeilen pro `row.insert`
_ERROR_VALUES = {"#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#REF!", "#VALUE!"}


class ImportFileError(ValueError):
    """Die Datei lässt sich nicht importieren (kaputt, passwortgeschützt, zu groß). Die Meldung ist für Nutzer
    und Agenten gedacht."""


@dataclass
class ImportResult:
    ops: list[dict[str, Any]] = field(default_factory=list)
    created: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def slug(text: str, fallback: str) -> str:
    """Key-Regel `^[a-z][a-z0-9_]{0,62}$` aus einem beliebigen Namen."""
    s = re.sub(r"[^a-z0-9]+", "_", text.translate(_UMLAUTS).lower()).strip("_")
    if not s:
        s = fallback
    if not s[0].isalpha():
        s = f"{fallback}_{s}"
    return s[:63].rstrip("_") or fallback


def _unique(key: str, taken: set[str]) -> str:
    candidate, n = key, 2
    while candidate in taken:
        suffix = f"_{n}"
        candidate = key[: 63 - len(suffix)] + suffix
        n += 1
    taken.add(candidate)
    return candidate


def _check_file(data: bytes) -> None:
    if not data:
        raise ImportFileError("Die Datei ist leer.")
    if len(data) > MAX_BYTES:
        raise ImportFileError(f"Die Datei ist zu groß ({len(data) // (1024 * 1024)} MB, erlaubt sind 10 MB).")
    if data[:8] == bytes.fromhex("D0CF11E0A1B11AE1"):
        raise ImportFileError("Die Datei ist passwortgeschützt oder im alten .xls-Format. Bitte als .xlsx "
                              "ohne Passwort speichern.")
    if data[:2] != b"PK":
        raise ImportFileError("Das ist keine gültige .xlsx-Datei (kein Excel-Arbeitsmappen-Format).")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED:
                raise ImportFileError("Die Datei ist entpackt zu groß.")
    except zipfile.BadZipFile as exc:
        raise ImportFileError("Die Datei ist beschädigt und lässt sich nicht öffnen.") from exc
    if "xl/workbook.xml" not in names:
        raise ImportFileError("Das ist keine gültige .xlsx-Datei (xl/workbook.xml fehlt).")


def _open(data: bytes, data_only: bool):
    try:
        return load_workbook(io.BytesIO(data), read_only=True, data_only=data_only)
    except ImportFileError:
        raise
    except Exception as exc:
        raise ImportFileError(f"Die Excel-Datei lässt sich nicht lesen: {exc}") from exc


def _is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


@dataclass
class _Col:
    index: int
    name: str
    key: str = ""
    letter: str = ""
    values: list[Any] = field(default_factory=list)  # je Datenzeile
    formats: list[str] = field(default_factory=list)


def _letter(index: int) -> str:
    n, out = index + 1, ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _currency_of(fmt: str) -> str | None:
    if "€" in fmt or "EUR" in fmt:
        return "EUR"
    if "$" in fmt or "USD" in fmt:
        return "USD"
    return None


def _kind(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "integer" if v.is_integer() else "number"
    if isinstance(v, dt.datetime):
        return "datetime"
    if isinstance(v, dt.date):
        return "date"
    if isinstance(v, dt.time):
        return "time"
    return "text"


def _as_text(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, dt.datetime):
        return v.isoformat(sep=" ") if v.time() != dt.time() else v.date().isoformat()
    if isinstance(v, (dt.date, dt.time)):
        return v.isoformat()
    return str(v)


def _infer(col: _Col, sheet: str, warnings: list[str]) -> tuple[dict[str, Any], list[Any]]:
    """Spaltentyp und umgewandelte Werte (gleich lang wie `col.values`)."""
    present = [(v, f) for v, f in zip(col.values, col.formats) if not _is_empty(v)]
    kinds = {_kind(v) for v, _ in present}
    where = f"Blatt '{sheet}', Spalte {col.letter} ('{col.name}')"

    def keep(fn):
        return [None if _is_empty(v) else fn(v) for v in col.values]

    if not present:
        return {"kind": "text"}, [None] * len(col.values)
    numeric = kinds <= {"integer", "number"}
    if numeric:
        currencies = {_currency_of(f) for _, f in present}
        if len(currencies) == 1 and None not in currencies:
            return {"kind": "currency", "currency": currencies.pop()}, keep(float)
        if kinds == {"integer"}:
            return {"kind": "integer"}, keep(int)
        return {"kind": "number", "decimals": 2}, keep(float)
    if kinds == {"boolean"}:
        return {"kind": "boolean"}, keep(bool)
    if kinds == {"date"} or (kinds == {"datetime"} and all(v.time() == dt.time() for v, _ in present)):
        return {"kind": "date"}, keep(lambda v: (v.date() if isinstance(v, dt.datetime) else v).isoformat())
    if kinds <= {"date", "datetime"}:
        return {"kind": "datetime"}, keep(lambda v: (v if isinstance(v, dt.datetime)
                                                     else dt.datetime.combine(v, dt.time())).isoformat())
    if len(kinds) > 1:
        warnings.append(f"{where}: gemischte Werte ({', '.join(sorted(kinds))}), als text angelegt")
    texts = keep(lambda v: v if isinstance(v, str) else _as_text(v))
    long = any(isinstance(t, str) and (len(t) > LONG_TEXT_LENGTH or "\n" in t) for t in texts)
    return {"kind": "long_text" if long else "text"}, texts


def _read_rows(ws, sheet_title: str) -> list[list[Any]]:
    """Alle Zeilen als Listen von Zellen (Werte und Formate), ohne die Grenzen zu überschreiten."""
    rows: list[list[Any]] = []
    non_empty = 0
    for row in ws.iter_rows():
        cells = list(row)
        while cells and _is_empty(getattr(cells[-1], "value", None)):
            cells.pop()  # leere Zellen am Zeilenende (Excel meldet oft große Bereiche)
        if len(cells) > MAX_COLUMNS:
            raise ImportFileError(f"Blatt '{sheet_title}' hat mehr als {MAX_COLUMNS} Spalten.")
        rows.append(cells)
        if cells:
            non_empty += 1
            if non_empty > MAX_ROWS + 1:
                raise ImportFileError(f"Blatt '{sheet_title}' hat mehr als {MAX_ROWS} Zeilen.")
    return rows


def _formula_counts(data: bytes, sheets: list[str]) -> dict[str, int]:
    """Anzahl Formeln je Blatt (zweiter, formelerhaltender Durchlauf)."""
    wb = _open(data, data_only=False)
    counts: dict[str, int] = {}
    try:
        for name in sheets:
            n = 0
            for row in wb[name].iter_rows():
                for c in row:
                    if getattr(c, "data_type", None) == "f":
                        n += 1
            counts[name] = n
    finally:
        wb.close()
    return counts


def parse_xlsx(data: bytes, sheet: str | None = None) -> ImportResult:
    """Blatt -> `table.create` + `row.insert`; Typableitung aus den Werten; Limits 10 MB / 10 000 Zeilen / 100 Spalten."""
    _check_file(data)
    wb = _open(data, data_only=True)
    try:
        names = list(wb.sheetnames)
        if sheet is not None:
            if sheet not in names:
                raise ImportFileError(f"Blatt '{sheet}' existiert nicht. Vorhandene Blätter: {', '.join(names)}.")
            names = [sheet]
        if not names:
            raise ImportFileError("Die Arbeitsmappe enthält kein Blatt.")
        try:
            formulas = _formula_counts(data, names)
        except ImportFileError:
            formulas = {}
        result = ImportResult()
        tables_created: list[dict[str, Any]] = []
        table_keys: set[str] = set()
        for name in names:
            try:
                rows = _read_rows(wb[name], name)
            except ImportFileError:
                raise
            except Exception as exc:
                raise ImportFileError(f"Blatt '{name}' lässt sich nicht lesen: {exc}") from exc
            _convert_sheet(name, rows, formulas.get(name, 0), result, tables_created, table_keys)
        if not tables_created:
            raise ImportFileError("Die Datei enthält keine importierbaren Daten (alle Blätter sind leer).")
        result.created = {"tables": tables_created}
        return result
    finally:
        wb.close()


def _convert_sheet(name: str, rows: list[list[Any]], formula_count: int, result: ImportResult,
                   tables_created: list[dict[str, Any]], table_keys: set[str]) -> None:
    warnings = result.warnings
    body = [r for r in rows if any(not _is_empty(getattr(c, "value", None)) for c in r)]
    if not body:
        warnings.append(f"Blatt '{name}' ist leer, keine Tabelle angelegt")
        return
    skipped_rows = len(rows) - len(body)
    header_row = body[0]
    data_rows = body[1:]
    if skipped_rows:
        warnings.append(f"Blatt '{name}': {skipped_rows} leere Zeile(n) übersprungen")
    if formula_count:
        warnings.append(f"Blatt '{name}': Formel verloren in {formula_count} Zelle(n), der zuletzt berechnete Wert "
                        "wurde übernommen")

    cols: list[_Col] = []
    keys: set[str] = set()
    for i, cell in enumerate(header_row):
        value = getattr(cell, "value", None)
        if _is_empty(value):
            warnings.append(f"Blatt '{name}': Spalte {_letter(i)} hat keinen Spaltenkopf und wurde übersprungen")
            continue
        text = str(value).strip()
        col = _Col(index=i, name=text, letter=_letter(i))
        col.key = _unique(slug(text, "spalte"), keys)
        cols.append(col)
    if not cols:
        warnings.append(f"Blatt '{name}' hat keine Spaltenköpfe, keine Tabelle angelegt")
        return
    for row in data_rows:
        for col in cols:
            cell = row[col.index] if col.index < len(row) else None
            col.values.append(getattr(cell, "value", None))
            col.formats.append(getattr(cell, "number_format", "") or "")
    if any(isinstance(v, str) and v in _ERROR_VALUES for c in cols for v in c.values):
        warnings.append(f"Blatt '{name}': enthält Excel-Fehlerwerte (z. B. #DIV/0!), sie wurden als Text übernommen")
    if not data_rows:
        warnings.append(f"Blatt '{name}' hat nur eine Kopfzeile, die Tabelle bleibt ohne Zeilen")

    table_id = new_id("table")
    columns, typed = [], []
    for col in cols:
        type_, values = _infer(col, name, warnings)
        col_id = new_id("column")
        columns.append({"id": col_id, "key": col.key, "name": col.name, "type": type_})
        typed.append((col.key, values))
    table_key = _unique(slug(name, "tabelle"), table_keys)
    result.ops.append({"op": "table.create", "id": table_id, "key": table_key, "name": name.strip() or table_key,
                       "display_column": columns[0]["id"], "columns": columns})
    new_rows = []
    for r in range(len(data_rows)):
        values = {key: vals[r] for key, vals in typed if vals[r] is not None}
        new_rows.append({"id": new_id("row"), "values": values})
    for start in range(0, len(new_rows), INSERT_CHUNK):
        result.ops.append({"op": "row.insert", "table": table_id, "rows": new_rows[start:start + INSERT_CHUNK]})
    tables_created.append({"id": table_id, "key": table_key, "name": name, "columns": [c["key"] for c in columns],
                           "column_ids": {c["key"]: c["id"] for c in columns}, "rows": len(new_rows)})
