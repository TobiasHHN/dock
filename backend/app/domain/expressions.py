"""Ausdrücke `{{ }}` (L 4.5, T 2.1). Task 3.2. Fixtures: spec/fixtures/expressions/.

Bewusst klein: Pfade, Literale und die Funktionen `sum`, `count`, `concat`, `coalesce`, `lookup`. Kein `eval`.
Besteht ein Text nur aus einem `{{ … }}`, bleibt der Typ des Ergebnisses erhalten, sonst entsteht Text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any


class ExpressionError(ValueError):
    pass


_BLOCK = re.compile(r"\{\{(.*?)\}\}", re.S)
_TOKEN = re.compile(
    r"""\s*(?:
        (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
      | (?P<num>-?\d+(?:\.\d+)?)
      | (?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)
      | (?P<punct>[(),])
    )""", re.X)
_LITERALS = {"true": True, "false": False, "null": None}
FUNCTIONS = {"sum", "count", "concat", "coalesce", "lookup"}
ROOTS = {"fields", "item", "results", "run", "user", "now", "today"}


@dataclass
class _Lit:
    value: Any


@dataclass
class _Path:
    path: str


@dataclass
class _Call:
    name: str
    args: list[Any]


def _tokens(body: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    body = body.rstrip()
    while pos < len(body):
        m = _TOKEN.match(body, pos)
        if not m:
            raise ExpressionError(f"Unerwartetes Zeichen '{body[pos:].strip()[:1]}' in '{body.strip()}'")
        pos = m.end()
        out.append((m.lastgroup, m.group(m.lastgroup)))  # type: ignore[arg-type]
    return out


def _unquote(raw: str) -> str:
    return re.sub(r"\\(.)", r"\1", raw[1:-1])


def _parse(body: str) -> Any:
    toks = _tokens(body)
    if not toks:
        raise ExpressionError("Leerer Ausdruck '{{ }}'")
    pos = 0

    def expr() -> Any:
        nonlocal pos
        if pos >= len(toks):
            raise ExpressionError(f"Ausdruck '{body.strip()}' ist unvollständig")
        kind, val = toks[pos]
        pos += 1
        if kind == "str":
            return _Lit(_unquote(val))
        if kind == "num":
            return _Lit(float(val) if "." in val else int(val))
        if kind == "name":
            if pos < len(toks) and toks[pos] == ("punct", "("):
                if "." in val or val not in FUNCTIONS:
                    raise ExpressionError(f"Unbekannte Funktion '{val}'. Erlaubt: {', '.join(sorted(FUNCTIONS))}")
                pos += 1
                args: list[Any] = []
                if pos < len(toks) and toks[pos] == ("punct", ")"):
                    pos += 1
                    return _Call(val, args)
                while True:
                    args.append(expr())
                    if pos >= len(toks):
                        raise ExpressionError(f"Klammer in '{body.strip()}' nicht geschlossen")
                    sep = toks[pos][1]
                    pos += 1
                    if sep == ")":
                        return _Call(val, args)
                    if sep != ",":
                        raise ExpressionError(f"Erwartet ',' oder ')' in '{body.strip()}'")
            if val.lower() in _LITERALS:
                return _Lit(_LITERALS[val.lower()])
            return _Path(val)
        raise ExpressionError(f"Unerwartetes '{val}' in '{body.strip()}'")

    tree = expr()
    if pos != len(toks):
        raise ExpressionError(f"Unerwartetes '{toks[pos][1]}' in '{body.strip()}'")
    return tree


# ── Auswertung ───────────────────────────────────────────────────────────────


def _resolve(path: str, ctx: dict[str, Any]) -> Any:
    parts = path.split(".")
    root = parts[0]
    if root == "now":
        return ctx.get("now") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    if root == "today":
        return ctx.get("today") or date.today().isoformat()
    if root not in ROOTS:
        raise ExpressionError(f"Unbekannter Pfad '{path}': '{root}' ist keine Quelle. Erlaubt: {', '.join(sorted(ROOTS))}")
    cur: Any = ctx.get(root)
    if cur is None and root in ("run", "item"):
        raise ExpressionError(f"Unbekannter Pfad '{path}': '{root}' gibt es hier nicht (kein "
                              f"{'Run' if root == 'run' else 'Element einer Zeilenliste'} im Kontext)")
    walked = root
    for part in parts[1:]:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, dict):
            known = ", ".join(sorted(map(str, cur))) or "nichts"
            raise ExpressionError(f"Unbekannter Pfad '{path}': '{part}' gibt es unter '{walked}' nicht (bekannt: {known})")
        elif cur is None:
            return None
        else:
            raise ExpressionError(f"Unbekannter Pfad '{path}': unter '{walked}' gibt es kein '{part}'")
        walked += f".{part}"
    return cur


def _num(value: Any) -> int | float | Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ExpressionError(f"'{value}' ist keine Zahl")
    if isinstance(value, (int, float, Decimal)):
        return value
    try:
        return float(str(value).replace(",", "."))
    except ValueError as exc:
        raise ExpressionError(f"'{value}' ist keine Zahl") from exc


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (list, dict)):
        raise ExpressionError("Eine Liste oder ein Objekt lässt sich nicht als Text einsetzen")
    return str(value)


def _eval(node: Any, ctx: dict[str, Any], lenient: bool = False) -> Any:
    if isinstance(node, _Lit):
        return node.value
    if isinstance(node, _Path):
        try:
            return _resolve(node.path, ctx)
        except ExpressionError:
            if lenient:
                return None
            raise
    name, args = node.name, node.args
    if name == "coalesce":
        for arg in args:
            value = _eval(arg, ctx, lenient=True)
            if value is not None and value != "":
                return value
        return None
    vals = [_eval(a, ctx, lenient) for a in args]

    def arity(n: int) -> None:
        if len(vals) != n:
            raise ExpressionError(f"{name}() braucht {n} Argumente, nicht {len(vals)}")

    if name == "concat":
        return "".join(_text(v) for v in vals)
    if name == "count":
        arity(1)
        if vals[0] is None:
            return 0
        if not isinstance(vals[0], list):
            raise ExpressionError("count() erwartet eine Liste")
        return len(vals[0])
    if name == "sum":
        arity(2)
        items, key = vals
        if items is None:
            return 0
        if not isinstance(items, list):
            raise ExpressionError("sum() erwartet eine Liste als erstes Argument")
        total: Any = 0
        for item in items:
            n = _num(item.get(key) if isinstance(item, dict) else None)
            if n is not None:
                total += n
        return total
    arity(4)  # lookup
    table, column, value, result = vals
    tables = ctx.get("tables") or {}
    if table not in tables:
        raise ExpressionError(f"lookup(): Tabelle '{table}' ist unbekannt")
    for row in tables[table]:
        found = row.get(column)
        if found == value or (found is not None and value is not None and str(found) == str(value)):
            return row.get(result)
    return None


def evaluate(expr: str, context: dict[str, Any]) -> Any:
    """Wertet einen Text aus. Besteht er nur aus einem `{{ … }}`-Ausdruck, bleibt der Typ erhalten, sonst Text.
    `context`: fields, item, results, run, user, now, today, tables (für `lookup`: Key -> Zeilen mit Spalten-Keys).
    Wirft ExpressionError bei unbekannten Pfaden oder Funktionen. In `coalesce` zählen unbekannte Pfade als leer."""
    if not isinstance(expr, str) or "{{" not in expr:
        return expr
    matches = list(_BLOCK.finditer(expr))
    if len(matches) == 1 and not expr[:matches[0].start()].strip() and not expr[matches[0].end():].strip():
        return _eval(_parse(matches[0].group(1)), context)
    out, pos = [], 0
    for m in matches:
        out.append(expr[pos:m.start()])
        out.append(_text(_eval(_parse(m.group(1)), context)))
        pos = m.end()
    out.append(expr[pos:])
    return "".join(out)


def evaluate_deep(value: Any, context: dict[str, Any]) -> Any:
    """Wertet alle Texte in einer verschachtelten Struktur (Listen, Objekte) aus."""
    if isinstance(value, str):
        return evaluate(value, context)
    if isinstance(value, list):
        return [evaluate_deep(v, context) for v in value]
    if isinstance(value, dict):
        return {k: evaluate_deep(v, context) for k, v in value.items()}
    return value


def _walk(node: Any, out: list[str]) -> None:
    if isinstance(node, _Path):
        if node.path.split(".")[0] not in ("now", "today"):
            out.append(node.path)
    elif isinstance(node, _Call):
        for a in node.args:
            _walk(a, out)


def find_paths(expr: str) -> list[str]:
    """Alle Pfade in einem Text, z. B. für `validate_form` und `validate_workflow` (Tippfehler finden).
    Funktionsnamen, Literale, `now` und `today` zählen nicht; Text mit Syntaxfehlern liefert nur die Pfade
    der intakten Ausdrücke (Syntaxfehler meldet `syntax_errors`)."""
    out: list[str] = []
    if isinstance(expr, str):
        for m in _BLOCK.finditer(expr):
            try:
                _walk(_parse(m.group(1)), out)
            except ExpressionError:
                continue
    return out


def lookup_tables(expr: str) -> set[str]:
    """Tabellen-Keys, die `lookup("<key>", …)` im Text mit Literalen nennt (zum Vorladen der Daten)."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, _Call):
            if node.name == "lookup" and node.args and isinstance(node.args[0], _Lit):
                found.add(str(node.args[0].value))
            for a in node.args:
                walk(a)

    for m in _BLOCK.finditer(expr or ""):
        try:
            walk(_parse(m.group(1)))
        except ExpressionError:
            continue
    return found


def syntax_errors(expr: str) -> list[str]:
    """Meldungen zu Ausdrücken im Text, die sich nicht lesen lassen (unbekannte Funktion, offene Klammer, …)."""
    out: list[str] = []
    if isinstance(expr, str):
        if expr.count("{{") != expr.count("}}"):
            out.append(f"'{expr}': '{{{{' und '}}}}' passen nicht zusammen")
        for m in _BLOCK.finditer(expr):
            try:
                _parse(m.group(1))
            except ExpressionError as exc:
                out.append(str(exc))
    return out
