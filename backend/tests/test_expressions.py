"""Ausdrücke {{ }} (Task 3.2): Zusatzfälle zu spec/fixtures/expressions/ (die Fixtures laufen in test_fixtures.py)."""
import pytest

from app.domain.expressions import ExpressionError, evaluate, evaluate_deep, find_paths, lookup_tables, syntax_errors

CTX = {"fields": {"a": 2, "b": None, "liste": [{"p": 1.5}, {"p": "2,5"}, {"p": None}], "leer": ""},
       "item": {"p": 3}, "user": {"id": "u1", "name": "Ben"}, "tables": {"t": [{"k": 1, "v": "x"}]}}


def test_type_is_kept_only_for_pure_expression():
    assert evaluate("{{fields.a}}", CTX) == 2
    assert evaluate(" {{fields.a}} ", CTX) == 2
    assert evaluate("{{fields.a}}{{fields.a}}", CTX) == "22"
    assert evaluate("Nr. {{fields.a}}", CTX) == "Nr. 2"
    assert evaluate("{{fields.b}}", CTX) is None and evaluate("x{{fields.b}}y", CTX) == "xy"
    assert evaluate("kein Ausdruck", CTX) == "kein Ausdruck" and evaluate("1", {}) == "1"
    assert evaluate("{{true}}", {}) is True and evaluate("{{42}}", {}) == 42 and evaluate("{{null}}", {}) is None


def test_functions():
    assert evaluate('{{sum(fields.liste, "p")}}', CTX) == 4.0
    assert evaluate('{{sum(fields.nix, "p")}}', {"fields": {"nix": None}}) == 0
    assert evaluate("{{count(fields.liste)}}", CTX) == 3
    assert evaluate("{{coalesce(fields.b, fields.leer, fields.a)}}", CTX) == 2
    assert evaluate("{{coalesce(fields.unbekannt, 'x')}}", CTX) == "x"
    assert evaluate('{{lookup("t", "k", fields.a, "v")}}', CTX) is None
    assert evaluate('{{lookup("t", "k", "1", "v")}}', CTX) == "x"  # Zahl und Text gleichen sich an
    assert evaluate("{{item.p}}", CTX) == 3
    assert evaluate("{{today}}", {"today": "2026-01-02"}) == "2026-01-02"
    assert len(evaluate("{{today}}", {})) == 10 and "T" in evaluate("{{now}}", {})


@pytest.mark.parametrize("expr,part", [
    ("{{fields.zahl}}", "zahl"), ("{{run.id}}", "run"), ("{{nix.x}}", "nix"), ("{{foo(1)}}", "foo"),
    ("{{sum(fields.a)}}", "2 Argumente"), ('{{lookup("x","a","b","c")}}', "Tabelle 'x'"),
    ("{{concat(1,}}", "unvollständig"), ("{{fields.a +}}", "Zeichen"), ("{{}}", "Leer"),
    ("{{count(fields.a)}}", "Liste"), ("{{fields.liste}} x", "Liste")])
def test_errors(expr, part):
    with pytest.raises(ExpressionError) as exc:
        evaluate(expr, CTX)
    assert part in str(exc.value)


def test_no_python_evaluation():
    for expr in ("{{__import__('os')}}", "{{fields.a.__class__}}", "{{(1)}}"):
        with pytest.raises(ExpressionError):
            evaluate(expr, CTX)


def test_find_paths_and_helpers():
    text = '{{concat("a.b", run.steps.x.values.y, coalesce(fields.z, "…"))}} {{sum(fields.l, "preis")}} {{today}} {{true}}'
    assert find_paths(text) == ["run.steps.x.values.y", "fields.z", "fields.l"]
    assert find_paths("kein Ausdruck") == [] and find_paths("{{kaputt(}}") == []
    assert lookup_tables('{{lookup("kostenstellen", "n", fields.k, "v")}}') == {"kostenstellen"}
    assert syntax_errors("{{foo(1)}} und {{fields.a}}") and not syntax_errors("{{fields.a}}")
    assert syntax_errors("{{fields.a")


def test_evaluate_deep():
    assert evaluate_deep({"a": ["{{fields.a}}", "x"], "b": 1}, CTX) == {"a": [2, "x"], "b": 1}
