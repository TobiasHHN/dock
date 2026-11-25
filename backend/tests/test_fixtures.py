"""Lädt spec/fixtures. Formtests laufen immer; Ausführungstests sind übersprungen, bis die jeweilige
Implementierung existiert (siehe spec/fixtures/README.md), und werden dann automatisch aktiv."""
import importlib
from dataclasses import asdict, is_dataclass

import pytest

from app.schemas.ops import OpBatch

from .fixture_support import (
    FIXTURE_ROOT, KINDS, check_error, check_ops_result, check_warnings, for_runner, load_all, matches,
)

ALL = load_all()


def _optional(module: str, attr: str):
    try:
        return getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError):
        return None


def test_fixture_counts():
    kinds = [f["kind"] for _, f in ALL]
    for kind in ("ops", "expression", "import"):
        assert kinds.count(kind) >= 2, kind
    for sub in ("tables", "documents", "expressions", "imports"):
        assert len([n for n, _ in ALL if n.startswith(sub + "/")]) >= 2, sub


@pytest.mark.parametrize("name,fx", ALL, ids=[n for n, _ in ALL])
def test_shape(name, fx):
    assert fx["kind"] in KINDS and fx["name"] and set(fx["runners"]) <= {"pytest", "vitest"}
    if fx["kind"] == "ops":
        OpBatch.model_validate({"batch_id": "b_fixture", "ops": fx["ops"]})  # Ops gehören zum API-Vertrag
        assert any(k in fx for k in ("expect_state", "expect_order", "expect_block_ids", "expect_error"))
    elif fx["kind"] == "expression":
        assert fx["cases"] and all("expr" in c and ("expect" in c or "expect_error" in c) for c in fx["cases"])
    else:
        assert (FIXTURE_ROOT / fx["file"]).exists() and fx["expect_ops"]


@pytest.mark.parametrize("name,fx", for_runner("pytest", "ops"), ids=lambda x: x if isinstance(x, str) else "")
def test_ops_fixture(name, fx):
    apply_ops = _optional("app.ops.memory", "apply_ops")
    op_error = _optional("app.ops.memory", "OpError")
    if apply_ops is None:
        pytest.skip("app.ops.memory.apply_ops noch nicht implementiert (Task 1.2–1.4)")
    import copy

    state = copy.deepcopy(fx["state"])
    if "expect_error" in fx:
        with pytest.raises(op_error) as exc:
            apply_ops(copy.deepcopy(state), fx["ops"])
        assert not check_error(fx, exc.value.code, str(exc.value), getattr(exc.value, "fields", {}))
        after = state  # unverändert (Atomarität)
    else:
        after = apply_ops(state, fx["ops"])
    assert not check_ops_result(fx, after)


@pytest.mark.parametrize("name,fx", for_runner("pytest", "expression"), ids=lambda x: x if isinstance(x, str) else "")
def test_expression_fixture(name, fx):
    evaluate = _optional("app.domain.expressions", "evaluate")
    if evaluate is None or evaluate("1", {}) is None:
        pytest.skip("Ausdrücke noch nicht implementiert (Task 3.2)")
    for case in fx["cases"]:
        if "expect_error" in case:
            with pytest.raises(Exception) as exc:
                evaluate(case["expr"], fx["context"])
            assert case["expect_error"] in str(exc.value)
        else:
            assert evaluate(case["expr"], fx["context"]) == case["expect"], case["expr"]


@pytest.mark.parametrize("name,fx", for_runner("pytest", "import"), ids=lambda x: x if isinstance(x, str) else "")
def test_import_fixture(name, fx):
    parser = _optional(f"app.imports.{fx['source']}", f"parse_{fx['source']}")
    data = (FIXTURE_ROOT / fx["file"]).read_bytes()
    result = parser(data, **fx["params"]) if parser else None
    if result is None:
        pytest.skip(f"parse_{fx['source']} noch nicht implementiert (Task 3.6/3.7)")
    res = asdict(result) if is_dataclass(result) else result
    assert not matches(fx["expect_ops"], res["ops"])
    if "expect_created" in fx:
        assert not matches(fx["expect_created"], res["created"])
    assert not check_warnings(fx, res["warnings"])


# ── Der Vergleich selbst ─────────────────────────────────────────────────────


def test_matcher_semantics():
    assert not matches({"a": 1}, {"a": 1, "b": 2})  # Teilvergleich
    assert matches({"a": 1}, {"b": 2})
    assert not matches([1, {"x": "<any>"}], [1, {"x": "q"}])
    assert matches([1, 2], [1, 2, 3])  # Länge muss passen
    assert not matches(498, 498.0)
    assert not matches(["<bind:t>", "<bind:t>"], ["a", "a"])
    assert matches(["<bind:t>", "<bind:t>"], ["a", "b"])


def test_import_files_are_readable():
    xlsx = _optional("openpyxl", "load_workbook")
    wb = xlsx(FIXTURE_ROOT / "files" / "uebersicht.xlsx", data_only=True)
    assert wb.sheetnames == ["Bestellungen"]
