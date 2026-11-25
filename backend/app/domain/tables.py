"""Tabellen: Typumwandlung, Pflicht/Unique/Min/Max, on_delete (L 2.2). Implementierung: Task 1.3 (P1).

Reine Fachlogik ohne Datenbank. Die Handler in `ops/handlers/tables.py` (Postgres) und `ops/memory.py`
(Fixtures) rufen dieselben Funktionen auf, damit beide Seiten gleich entscheiden. Spalten sind hier einfache
Dicts mit den Schlüsseln `id, key, name, type, required, unique, default` (Typ als Dict oder Pydantic-Modell).
"""
from __future__ import annotations

import re
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, TypeAdapter

from app.schemas.tables import ColumnType

_TYPE_ADAPTER = TypeAdapter(ColumnType)

KEY_PREFIXES = {"table": "tbl_", "column": "col_"}


class DomainError(Exception):
    """Fachlicher Fehler. `fields` bildet Pfad/Spaltenkey -> Meldung ab (L 2.2), `details` ergänzt z. B. die
    Verwendungen bei IN_USE. Handler übersetzen in `PipelineError`, `ops.memory` in `OpError`."""

    def __init__(self, code: str, message: str, fields: dict[str, str] | None = None,
                 details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or {}
        self.details = details or {}


def validation_error(fields: dict[str, str], subject: str = "Die Eingabe") -> DomainError:
    return DomainError("VALIDATION", f"{subject} ist ungültig: " + "; ".join(fields.values()), fields)


# ── Typen ────────────────────────────────────────────────────────────────────


def type_dict(type_: Any) -> dict[str, Any]:
    """Spaltentyp als Dict (akzeptiert Dict oder Pydantic-Modell, prüft über das Schema)."""
    if isinstance(type_, BaseModel):
        return type_.model_dump(mode="json")
    return _TYPE_ADAPTER.validate_python(type_).model_dump(mode="json")


def _fmt(value: Any) -> str:
    return f"„{value}“"


_TRUE = {"true", "ja", "j", "yes", "y", "1", "wahr", "x", "an"}
_FALSE = {"false", "nein", "n", "no", "0", "falsch", "aus"}
_CURRENCY_WORDS = re.compile(r"(?i)\b(eur|usd|chf|gbp)\b|[€$£]")


def parse_decimal(value: Any) -> Decimal | None:
    """Liest Zahlen in deutscher und englischer Schreibweise ("12,50", "1.234,56", "1,234.56", "12.5 €").
    Ein einzelner Punkt mit genau drei Nachkommastellen ("1.234") gilt als Tausenderpunkt, sonst als Dezimalpunkt."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value)) if value == value and value not in (float("inf"), float("-inf")) else None
    if not isinstance(value, str):
        return None
    s = _CURRENCY_WORDS.sub("", value).replace(" ", "").replace(" ", "").replace("'", "")
    if not s:
        return None
    comma, dot = s.count(","), s.count(".")
    if comma and dot:
        decimal_sep = "," if s.rfind(",") > s.rfind(".") else "."
        thousands = "." if decimal_sep == "," else ","
        s = s.replace(thousands, "").replace(decimal_sep, ".")
    elif comma:
        s = s.replace(",", "") if comma > 1 else s.replace(",", ".")
    elif dot > 1:
        s = s.replace(".", "")
    elif dot == 1 and re.fullmatch(r"[+-]?[1-9]\d{0,2}\.\d{3}", s):
        s = s.replace(".", "")  # "1.234" ist im Deutschen 1234 (Tausenderpunkt); "0.125" und "12.5" bleiben Dezimalzahlen
    if not re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)", s):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _quantize(d: Decimal, decimals: int) -> float:
    return float(d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP))


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    s = value.strip()
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    try:
        if m:
            return date(int(m[3]), int(m[2]), int(m[1]))
        return date.fromisoformat(s[:10]) if re.fullmatch(r"\d{4}-\d{2}-\d{2}([T ].*)?", s) else None
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if not isinstance(value, str):
        return None
    s = value.strip()
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?", s)
    try:
        if m:
            return datetime(int(m[3]), int(m[2]), int(m[1]), int(m[4] or 0), int(m[5] or 0), int(m[6] or 0))
        return datetime.fromisoformat(s) if re.match(r"\d{4}-\d{2}-\d{2}([T ]|$)", s) else None
    except ValueError:
        return None


def coerce_value(value: Any, type_: ColumnType) -> Any:
    """Wandelt in den Spaltentyp um (z. B. "12,50" -> 12.5 bei currency). Wirft ValueError mit Meldung pro Feld.

    `None` (bei Nicht-Text auch leerer Text) bleibt `None`; ob ein Wert Pflicht ist, prüft `prepare_values`.
    Min/Max von `integer` und die Optionen von `select` werden hier mitgeprüft. Bei `reference` wird nur die
    Form geprüft, ob die Zeile existiert, entscheidet der Handler (braucht die Datenbank)."""
    t = type_dict(type_)
    kind = t["kind"]
    text_kind = kind in ("text", "long_text")
    if value is None or (isinstance(value, str) and not value.strip() and not text_kind):
        return None
    if text_kind:
        if isinstance(value, bool):
            return "ja" if value else "nein"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return value
        raise ValueError(f"{_fmt(value)} ist kein Text")
    if kind == "integer":
        d = parse_decimal(value)
        if d is None:
            raise ValueError(f"{_fmt(value)} ist keine ganze Zahl")
        if d != d.to_integral_value():
            raise ValueError(f"{_fmt(value)} ist keine ganze Zahl (Nachkommastellen sind nicht erlaubt)")
        n = int(d)
        if t.get("min") is not None and n < t["min"]:
            raise ValueError(f"{n} ist zu klein, erlaubt ist mindestens {t['min']}")
        if t.get("max") is not None and n > t["max"]:
            raise ValueError(f"{n} ist zu groß, erlaubt ist höchstens {t['max']}")
        return n
    if kind in ("number", "currency"):
        d = parse_decimal(value)
        if d is None:
            raise ValueError(f"{_fmt(value)} ist {'kein gültiger Betrag' if kind == 'currency' else 'keine gültige Zahl'}")
        return _quantize(d, 2 if kind == "currency" else int(t.get("decimals", 2)))
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            s = value.strip().lower()
            if s in _TRUE:
                return True
            if s in _FALSE:
                return False
        raise ValueError(f"{_fmt(value)} ist weder ja noch nein")
    if kind == "date":
        d = _parse_date(value)
        if d is None:
            raise ValueError(f"{_fmt(value)} ist kein gültiges Datum (erwartet JJJJ-MM-TT oder TT.MM.JJJJ)")
        return d.isoformat()
    if kind == "datetime":
        dt = _parse_datetime(value)
        if dt is None:
            raise ValueError(f"{_fmt(value)} ist keine gültige Zeitangabe (erwartet z. B. 2026-03-01T14:30)")
        return dt.isoformat()
    if kind == "select":
        options = t["options"]
        if isinstance(value, str):
            s = value.strip()
            for o in options:
                if o["id"] == s:
                    return o["id"]
            for o in options:
                if o["label"].casefold() == s.casefold():
                    return o["id"]
        raise ValueError(f"{_fmt(value)} ist keine gültige Auswahl (erlaubt: "
                         + ", ".join(o["label"] for o in options) + ")")
    if kind == "user":
        if isinstance(value, str) and value.startswith("usr_") and len(value) > 4:
            return value
        raise ValueError(f"{_fmt(value)} ist keine gültige Nutzer-ID")
    if kind == "reference":
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError(f"{_fmt(value)} ist kein gültiger Verweis auf eine Zeile")
    raise ValueError(f"Unbekannter Spaltentyp '{kind}'")


# ── Spaltendefinition prüfen ─────────────────────────────────────────────────


def check_key(kind: str, key: str) -> str | None:
    """Meldung, wenn der Key unbrauchbar ist. Keys mit ID-Präfix würden bei `ctx.resolve` als ID gelesen."""
    label = "Tabellen" if kind == "table" else "Spalten"
    if not key or key != key.strip() or re.search(r"[\s.]", key):
        return f"Der {label}-Key {_fmt(key)} darf nicht leer sein und keine Leerzeichen oder Punkte enthalten"
    if key.startswith(KEY_PREFIXES[kind]):
        return (f"Der {label}-Key {_fmt(key)} darf nicht mit {_fmt(KEY_PREFIXES[kind])} beginnen "
                "(das Präfix ist für IDs reserviert)")
    return None


def check_column_definition(column: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Prüft eine Spaltendefinition (`ColumnIn` als Dict). Fehler als `{pfad: meldung}`."""
    errors: dict[str, str] = {}
    if msg := check_key("column", column["key"]):
        errors[f"{prefix}key"] = msg
    if not column["name"].strip():
        errors[f"{prefix}name"] = "Der Spaltenname darf nicht leer sein"
    t = type_dict(column["type"])
    if t["kind"] == "select":
        ids = [o["id"] for o in t["options"]]
        if not ids:
            errors[f"{prefix}type"] = "Eine Auswahl-Spalte braucht mindestens eine Option"
        elif len(set(ids)) != len(ids) or len({o["label"].casefold() for o in t["options"]}) != len(ids):
            errors[f"{prefix}type"] = "Die Optionen einer Auswahl-Spalte müssen eindeutige IDs und Namen haben"
    if t["kind"] == "integer" and t.get("min") is not None and t.get("max") is not None and t["min"] > t["max"]:
        errors[f"{prefix}type"] = f"Min ({t['min']}) darf nicht größer sein als Max ({t['max']})"
    if t["kind"] == "number" and not 0 <= int(t["decimals"]) <= 10:
        errors[f"{prefix}type"] = "Die Nachkommastellen müssen zwischen 0 und 10 liegen"
    if column.get("default") is not None and f"{prefix}type" not in errors:
        try:
            resolve_default(column["default"], t)
        except ValueError as exc:
            errors[f"{prefix}default"] = f"Standardwert: {exc}"
    return errors


def resolve_default(default: Any, type_: Any, *, now: datetime | None = None, user_id: str | None = None) -> Any:
    """Standardwert der Spalte. `{{now}}` und `{{user.id}}` werden beim Anlegen der Zeile aufgelöst."""
    if default is None:
        return None
    t = type_dict(type_)
    if isinstance(default, str) and default.strip().startswith("{{"):
        expr = default.strip()
        if expr == "{{now}}":
            moment = now or datetime.now(timezone.utc)
            if t["kind"] == "date":
                return moment.date().isoformat()
            if t["kind"] in ("datetime", "text", "long_text"):
                return moment.isoformat()
            raise ValueError("{{now}} passt nur zu Datum, Zeitpunkt oder Text")
        if expr == "{{user.id}}":
            if t["kind"] not in ("user", "text"):
                raise ValueError("{{user.id}} passt nur zu Nutzer oder Text")
            return user_id
        raise ValueError(f"Unbekannter Ausdruck {_fmt(expr)} (erlaubt: {{{{now}}}}, {{{{user.id}}}})")
    return coerce_value(default, t)  # type: ignore[arg-type]


# ── Zeilenwerte ──────────────────────────────────────────────────────────────


def _blank(value: Any) -> bool:
    return value is None or value == ""


def prepare_values(columns: list[dict[str, Any]], values: dict[str, Any], *, insert: bool,
                   now: datetime | None = None, user_id: str | None = None,
                   subject: str = "Die Zeile") -> dict[str, Any]:
    """Wandelt Zeilenwerte (Schlüssel = Spalten-ID) in die Spaltentypen um und prüft Pflichtfelder.

    `insert=True`: fehlende Spalten bekommen den Standardwert, Pflichtspalten ohne Wert sind ein Fehler;
    Spalten ohne Wert fehlen im Ergebnis. `insert=False`: nur die übergebenen Spalten, `None` leert eine Zelle
    (steht dann als `None` im Ergebnis). Fehler: `DomainError(VALIDATION)` mit einer Meldung pro Spalten-Key."""
    by_id = {c["id"]: c for c in columns}
    errors: dict[str, str] = {}
    out: dict[str, Any] = {}
    for col_id, raw in values.items():
        col = by_id.get(col_id)
        if col is None:
            errors[col_id] = f"Unbekannte Spalte {_fmt(col_id)}"
            continue
        try:
            out[col_id] = coerce_value(raw, col["type"])
        except ValueError as exc:
            errors[col["key"]] = f"{col['name']}: {exc}"
    if insert:
        for col in columns:
            if col["id"] in values:
                continue
            try:
                default = resolve_default(col.get("default"), col["type"], now=now, user_id=user_id)
            except ValueError:
                default = None
            if default is not None:
                out[col["id"]] = default
    for col in columns:
        if not col.get("required") or col["key"] in errors:
            continue
        if (insert or col["id"] in values) and _blank(out.get(col["id"])):
            errors[col["key"]] = f"{col['name']} ist ein Pflichtfeld und darf nicht leer sein"
    if errors:
        raise validation_error(errors, subject)
    if insert:
        out = {k: v for k, v in out.items() if v is not None}
    return out


def convert_values(values: dict[str, Any], new_type: Any) -> tuple[dict[str, Any], dict[str, str]]:
    """Typwechsel einer Spalte (L 2.2): konvertiert `{row_id: wert}`, nicht Konvertierbares wird `None`.
    Rückgabe: neue Werte (nur Zeilen mit vorhandenem Wert) und `{row_id: grund}` der verworfenen Werte."""
    converted: dict[str, Any] = {}
    lost: dict[str, str] = {}
    for row_id, value in values.items():
        if value is None:
            continue
        try:
            converted[row_id] = coerce_value(value, new_type)
        except ValueError as exc:
            converted[row_id] = None
            lost[row_id] = str(exc)
    return converted, lost


def find_duplicates(values: dict[str, Any]) -> dict[str, list[str]]:
    """Gleiche Werte in `{row_id: wert}` (None zählt nicht) -> `{wert: [row_ids]}`."""
    seen: dict[str, list[str]] = {}
    for row_id, value in values.items():
        if value is not None:
            seen.setdefault(str(value), []).append(row_id)
    return {k: v for k, v in seen.items() if len(v) > 1}


# ── Löschschutz (L 9) und on_delete (L 2.2) ──────────────────────────────────

_SOURCE_LABELS = {
    ("block", "table_view"): "Ansicht", ("block", "field.column"): "Formularfeld", ("block", "filter"): "Filter",
    ("block", "action.table"): "Formular", ("block", "action.value"): "Formular",
    ("column", "reference_column"): "Referenzspalte", ("row", "reference_column"): "Zeile",
}


def describe_usages(usages: list[dict[str, Any]]) -> str:
    parts = []
    for u in usages:
        label = _SOURCE_LABELS.get((u["source_kind"], u["via"]), u["source_kind"].capitalize())
        parts.append(f"{label} {u['source_id']} ({u['via']})")
    return ", ".join(parts)


def in_use_error(subject: str, usages: list[dict[str, Any]]) -> DomainError:
    return DomainError("IN_USE", f"{subject} wird noch verwendet von: {describe_usages(usages)}. "
                       "Entferne zuerst diese Verwendungen.", details={"usages": usages})


Link = tuple[str, str, str]  # (from_row, column_id, to_row)


@dataclass
class RowDeletePlan:
    delete: list[str]  # Zeilen, die verschwinden (Auswahl + per cascade betroffene)
    set_null: list[tuple[str, str]] = field(default_factory=list)  # (from_row, column_id) wird geleert
    blocked: list[Link] = field(default_factory=list)  # restrict: verweisende Zeilen, die bleiben würden


PlanGen = Generator[set[str], list[Link], RowDeletePlan]


def plan_row_delete(ids: list[str], on_delete_of: Callable[[str], str]) -> PlanGen:
    """Plant das Löschen von Zeilen entlang der `on_delete`-Regeln der Referenzspalten, die auf sie zeigen.

    Generator: gibt Mengen von Zeilen-IDs aus, für die der Treiber die eingehenden Verweise `(from_row,
    column_id, to_row)` zurücksenden muss (`drive_sync` für In-Memory, ein async-Treiber für Postgres)."""
    deleting: dict[str, None] = dict.fromkeys(ids)
    frontier = set(ids)
    set_null: dict[tuple[str, str], None] = {}
    restrict: dict[Link, None] = {}
    while frontier:
        links = yield frontier
        frontier = set()
        for link in links:
            from_row, column_id, _ = link
            mode = on_delete_of(column_id)
            if mode == "cascade":
                if from_row not in deleting:
                    deleting[from_row] = None
                    frontier.add(from_row)
            elif mode == "set_null":
                set_null[(from_row, column_id)] = None
            else:
                restrict[link] = None
    gone = set(deleting)
    return RowDeletePlan(
        delete=list(deleting),
        set_null=[k for k in set_null if k[0] not in gone],
        blocked=[k for k in restrict if k[0] not in gone],
    )


def drive_sync(gen: PlanGen, incoming: Callable[[set[str]], list[Link]]) -> RowDeletePlan:
    try:
        need = next(gen)
        while True:
            need = gen.send(incoming(need))
    except StopIteration as stop:
        return stop.value


def blocked_error(plan: RowDeletePlan, describe: Callable[[Link], str]) -> DomainError:
    usages = [{"source_kind": "row", "source_id": f, "via": "reference_column", "column": c, "target": t}
              for f, c, t in plan.blocked]
    lines = "; ".join(describe(link) for link in plan.blocked)
    return DomainError("IN_USE", f"Die Zeile kann nicht gelöscht werden, weil sie noch verwendet wird: {lines}. "
                       "Lösche oder ändere zuerst diese Zeilen.", details={"usages": usages})
