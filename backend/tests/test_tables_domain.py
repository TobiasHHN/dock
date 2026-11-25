"""Reine Fachlogik der Tabellen (Task 1.3, L 2.2) und Fractional Indexes, ohne Datenbank."""
import pytest

from app.domain import positions
from app.domain.tables import (
    DomainError, check_key, coerce_value, convert_values, plan_row_delete, drive_sync, prepare_values,
)

COLS = [
    {"id": "col_n", "key": "name", "name": "Name", "type": {"kind": "text"}, "required": True},
    {"id": "col_p", "key": "preis", "name": "Preis", "type": {"kind": "currency"}},
]


@pytest.mark.parametrize("value,type_,expected", [
    ("12,50", {"kind": "currency"}, 12.5),
    ("1.234,56 €", {"kind": "currency"}, 1234.56),
    ("1,234.56", {"kind": "number", "decimals": 1}, 1234.6),
    ("1.234", {"kind": "integer"}, 1234),  # Tausenderpunkt
    ("12.5", {"kind": "number"}, 12.5),
    ("0.125", {"kind": "number", "decimals": 3}, 0.125),
    ("1.234.567", {"kind": "integer"}, 1234567),
    (" 7 ", {"kind": "integer"}, 7),
    (3.0, {"kind": "integer"}, 3),
    ("ja", {"kind": "boolean"}, True),
    ("Nein", {"kind": "boolean"}, False),
    ("24.12.2026", {"kind": "date"}, "2026-12-24"),
    ("2026-12-24T10:30:00", {"kind": "datetime"}, "2026-12-24T10:30:00"),
    ("24.12.2026 10:30", {"kind": "datetime"}, "2026-12-24T10:30:00"),
    ("Offen", {"kind": "select", "options": [{"id": "o1", "label": "offen"}]}, "o1"),
    ("", {"kind": "integer"}, None),
    (None, {"kind": "text"}, None),
    (12, {"kind": "text"}, "12"),
])
def test_coerce_ok(value, type_, expected):
    assert coerce_value(value, type_) == expected


@pytest.mark.parametrize("value,type_,fragment", [
    ("abc", {"kind": "currency"}, "kein gültiger Betrag"),
    ("2,5", {"kind": "integer"}, "keine ganze Zahl"),
    (0, {"kind": "integer", "min": 1}, "mindestens 1"),
    (11, {"kind": "integer", "max": 10}, "höchstens 10"),
    (True, {"kind": "integer"}, "keine ganze Zahl"),
    ("vielleicht", {"kind": "boolean"}, "weder ja noch nein"),
    ("31.02.2026", {"kind": "date"}, "kein gültiges Datum"),
    ("x", {"kind": "select", "options": [{"id": "o1", "label": "offen"}]}, "erlaubt: offen"),
    ("anna", {"kind": "user"}, "Nutzer-ID"),
    ({"a": 1}, {"kind": "text"}, "kein Text"),
])
def test_coerce_errors_are_readable(value, type_, fragment):
    with pytest.raises(ValueError, match=fragment):
        coerce_value(value, type_)


def test_prepare_values_reports_every_field():
    with pytest.raises(DomainError) as e:
        prepare_values(COLS, {"col_p": "abc"}, insert=True)
    assert e.value.code == "VALIDATION" and set(e.value.fields) == {"preis", "name"}
    assert prepare_values(COLS, {"col_n": "x"}, insert=True) == {"col_n": "x"}
    assert prepare_values(COLS, {"col_p": None}, insert=False) == {"col_p": None}  # leeren erlaubt, nicht bei Pflicht
    with pytest.raises(DomainError):
        prepare_values(COLS, {"col_n": ""}, insert=False)


def test_check_key_rejects_id_prefix_and_dots():
    assert check_key("table", "bestellungen") is None
    assert check_key("table", "tbl_x") and check_key("column", "col_x") and check_key("column", "a.b")
    assert check_key("column", "tbl_x") is None  # nur das eigene Präfix ist reserviert


def test_convert_values_nulls_what_does_not_fit():
    converted, lost = convert_values({"r1": "5", "r2": "x", "r3": None}, {"kind": "integer"})
    assert converted == {"r1": 5, "r2": None} and set(lost) == {"r2"}


def test_plan_row_delete_follows_on_delete_rules():
    links = [("c1", "col_cascade", "p1"), ("g1", "col_restrict", "c1"), ("n1", "col_null", "p1"),
             ("keep", "col_restrict", "p2")]

    def incoming(ids):
        return [link for link in links if link[2] in ids]

    mode = {"col_cascade": "cascade", "col_restrict": "restrict", "col_null": "set_null"}
    plan = drive_sync(plan_row_delete(["p1"], mode.__getitem__), incoming)
    assert plan.delete == ["p1", "c1"]  # c1 per cascade
    assert plan.blocked == [("g1", "col_restrict", "c1")]  # g1 verweist auf die kaskadierte Zeile
    assert plan.set_null == [("n1", "col_null")]
    both = drive_sync(plan_row_delete(["p1", "g1"], mode.__getitem__), incoming)
    assert both.blocked == []  # g1 wird selbst gelöscht


def test_positions_order_and_between():
    a = positions.between(None, None)
    b = positions.between(a, None)
    mid = positions.between(a, b)
    first = positions.between(None, a)
    assert first < a < mid < b
    last = a
    for _ in range(100):  # wiederholtes Anhängen und Einfügen bleibt geordnet
        last = positions.between(last, None)
    assert positions.between(a, mid) > a
    with pytest.raises(ValueError):
        positions.between(b, a)
