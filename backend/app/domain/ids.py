"""IDs: Präfix + ULID, Key-Auflösung (L 1). Wird in Task 1.2 um die Key-Auflösung gegen die DB ergänzt."""
from ulid import ULID

PREFIXES = {
    "user": "usr", "agent": "agt", "role": "rol", "table": "tbl", "column": "col", "row": "row",
    "document": "doc", "block": "blk", "workflow": "wf", "run": "run", "task": "tsk",
    "batch": "b", "import": "imp", "event": "evt", "notification": "ntf",
}


def new_id(kind: str) -> str:
    return f"{PREFIXES[kind]}_{ULID()}"


def prefix_of(id_: str) -> str | None:
    head, sep, _ = id_.partition("_")
    return head if sep else None
