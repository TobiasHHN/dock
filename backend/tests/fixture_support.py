"""Lader und Vergleichslogik für spec/fixtures (Regeln: spec/fixtures/README.md).
Das TypeScript-Gegenstück liegt in frontend/src/sync/fixtureSupport.ts, beide müssen sich gleich verhalten."""
import json
from pathlib import Path
from typing import Any

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "spec" / "fixtures"
KINDS = {"ops", "expression", "import"}


def load_all() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for p in sorted(FIXTURE_ROOT.rglob("*.json")):
        out.append((str(p.relative_to(FIXTURE_ROOT)), json.loads(p.read_text())))
    return out


def for_runner(runner: str = "pytest", kind: str | None = None):
    return [(n, f) for n, f in load_all() if runner in f.get("runners", []) and (kind is None or f["kind"] == kind)]


def matches(expected: Any, actual: Any, binds: dict[str, Any] | None = None, path: str = "$") -> list[str]:
    """Teilvergleich mit Platzhaltern. Gibt eine Liste von Abweichungen zurück (leer = passt)."""
    binds = {} if binds is None else binds
    if isinstance(expected, str) and expected == "<any>":
        return []
    if isinstance(expected, str) and expected.startswith("<bind:") and expected.endswith(">"):
        name = expected[6:-1]
        if name not in binds:
            binds[name] = actual
            return []
        return [] if binds[name] == actual else [f"{path}: {actual!r} != gebundener Wert {binds[name]!r} ({name})"]
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: Objekt erwartet, bekam {actual!r}"]
        errs: list[str] = []
        for k, v in expected.items():
            if k not in actual:
                errs.append(f"{path}.{k}: fehlt")
            else:
                errs += matches(v, actual[k], binds, f"{path}.{k}")
        return errs
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return [f"{path}: Liste der Länge {len(expected)} erwartet, bekam {actual!r}"]
        errs = []
        for i, (e, a) in enumerate(zip(expected, actual)):
            errs += matches(e, a, binds, f"{path}[{i}]")
        return errs
    if isinstance(expected, bool) or isinstance(actual, bool):
        return [] if expected is actual else [f"{path}: {actual!r} != {expected!r}"]
    return [] if expected == actual else [f"{path}: {actual!r} != {expected!r}"]


def check_ops_result(fx: dict[str, Any], state_after: dict[str, Any]) -> list[str]:
    """Prüft expect_state / expect_order / expect_block_ids gegen den Zustand nach den Ops."""
    errs: list[str] = []
    if "expect_state" in fx:
        errs += matches(fx["expect_state"], state_after)
    for o in fx.get("expect_order", []):
        doc = next(d for d in state_after.get("documents", []) if d["id"] == o["doc"])
        kids = sorted((b for b in doc["blocks"] if b.get("parent_id") == o["parent"]), key=lambda b: b["position"].encode())
        ids = [b["id"] for b in kids]
        if ids != o["ids"]:
            errs.append(f"Reihenfolge in {o['doc']}: {ids} != {o['ids']}")
    for doc_id, ids in fx.get("expect_block_ids", {}).items():
        doc = next(d for d in state_after.get("documents", []) if d["id"] == doc_id)
        got = sorted(b["id"] for b in doc["blocks"])
        if got != sorted(ids):
            errs.append(f"Blöcke in {doc_id}: {got} != {sorted(ids)}")
    return errs


def check_error(fx: dict[str, Any], code: str, message: str, fields: dict[str, Any] | None) -> list[str]:
    exp = fx["expect_error"]
    errs = []
    if code != exp["code"]:
        errs.append(f"Fehlercode {code} != {exp['code']}")
    for f in exp.get("fields", []):
        if f not in (fields or {}):
            errs.append(f"Feldfehler für '{f}' fehlt")
    if "message_contains" in exp and exp["message_contains"] not in message:
        errs.append(f"Meldung enthält nicht '{exp['message_contains']}': {message}")
    return errs


def check_warnings(fx: dict[str, Any], warnings: list[str]) -> list[str]:
    errs = []
    if "expect_warnings" in fx and warnings != fx["expect_warnings"]:
        errs.append(f"Warnungen {warnings} != {fx['expect_warnings']}")
    for s in fx.get("warnings_contain", []):
        if not any(s in w for w in warnings):
            errs.append(f"Warnung mit '{s}' fehlt in {warnings}")
    for s in fx.get("warnings_absent", []):
        if any(s in w for w in warnings):
            errs.append(f"Warnung mit '{s}' darf nicht vorkommen: {warnings}")
    return errs
