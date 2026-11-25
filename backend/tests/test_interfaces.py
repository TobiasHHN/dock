"""Stellt sicher, dass alle Schnittstellen aus Task 0.5 importierbar sind und ihre Signaturen stabil bleiben."""
import importlib
import inspect

import pytest

# (Modul, Funktion, erwartete Parameternamen)
SIGNATURES = [
    ("app.ops.pipeline", "apply_batch", ["batch", "actor", "session"]),
    ("app.realtime.hub", "publish", ["channel", "event"]),
    ("app.domain.expressions", "evaluate", ["expr", "context"]),
    ("app.domain.forms", "submit_form", ["ctx", "op"]),
    ("app.domain.forms", "validate_form", ["blocks", "form_block"]),
    ("app.domain.workflows", "validate_workflow", ["ctx", "definition"]),
    ("app.domain.workflows", "publish_workflow", ["ctx", "workflow_id"]),
    ("app.domain.workflows", "start_run", ["ctx", "run_id", "workflow", "input", "actor"]),
    ("app.domain.tasks", "resolve_assignees", ["ctx", "step", "run"]),
    ("app.domain.tasks", "can_act", ["actor", "actor_roles", "task"]),
    ("app.search.embeddings", "enqueue_reembed", ["source_kind", "source_id"]),
]


@pytest.mark.parametrize("module,name,params", SIGNATURES)
def test_signature(module, name, params):
    fn = getattr(importlib.import_module(module), name)
    assert list(inspect.signature(fn).parameters) == params


def test_ids():
    from app.domain.ids import new_id, prefix_of

    i = new_id("block")
    assert i.startswith("blk_") and prefix_of(i) == "blk"
